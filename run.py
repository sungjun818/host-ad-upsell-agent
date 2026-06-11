"""
호스트 광고 업셀 자동화 에이전트

Usage:
  python run.py                          # 드라이런 (Slack + 이메일 시뮬레이션)
  python run.py --stage 1                # Slack 리포트만 발송 (이메일 미리보기 포함)
  python run.py --stage 2                # 이메일만 (전체 A/B급)
  python run.py --stage all              # Slack + 이메일
  python run.py --execute                # 실제 발송 (드라이런 해제)
  python run.py --stage 2 --execute --acm-ids 123,456   # 버튼 클릭 시 호출
"""
from __future__ import annotations

import argparse
import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(_dir, ".env"))
load_dotenv(os.path.join(_dir, "..", ".env"))

import db
import scorer
import claude_client
import stage1_slack
import stage2_email


def main():
    parser = argparse.ArgumentParser(description="호스트 광고 업셀 에이전트")
    parser.add_argument("--stage", default="all", choices=["1", "2", "all"],
                        help="실행 단계: 1=Slack리포트, 2=이메일, all=전체 (기본)")
    parser.add_argument("--execute", action="store_true",
                        help="실제 발송 (기본: 드라이런)")
    parser.add_argument("--limit", type=int, default=50,
                        help="분석 대상 숙소 수 (기본 50)")
    parser.add_argument("--acm-ids", dest="acm_ids", default="",
                        help="발송 대상 숙소 ID comma-separated. 지정 시 해당 숙소만 이메일 발송")
    parser.add_argument("--schedule-slack", dest="schedule_slack", action="store_true",
                        help="Slack 메인 리포트를 월요일 11시에 예약 발송 (이메일 미리보기는 즉시 발송)")
    parser.add_argument("--test-to", dest="test_to", default="",
                        help="테스트 발송 이메일 주소 (지정 시 호스트 대신 이 주소로 발송, 제목에 [테스트] 접두어)")
    args = parser.parse_args()

    dry_run   = not args.execute
    run_slack = args.stage in ("1", "all")
    run_email = args.stage in ("2", "all")

    # --acm-ids 지정 시: 버튼 클릭으로 승인된 이메일 발송 전용 모드
    target_acm_ids: set[int] = set()
    if args.acm_ids:
        target_acm_ids = {int(x.strip()) for x in args.acm_ids.split(",") if x.strip()}
        run_slack = False
        run_email = True
        print(f"=== 호스트 업셀 이메일 발송 (버튼 승인) ===")
        print(f"DRY_RUN={dry_run} | 대상 숙소 {len(target_acm_ids)}개: {target_acm_ids}\n")
    else:
        print(f"=== 호스트 광고 업셀 에이전트 ===")
        print(f"DRY_RUN={dry_run} | STAGE={args.stage} | LIMIT={args.limit}\n")

    slack_channel = os.environ.get("UPSELL_SLACK_CHANNEL_ID", "")
    slack_token   = os.environ.get("AGENT_BOT_TOKEN", "")

    # ── 1. DB 분석 ───────────────────────────────────────────────────────
    print("📊 DB 분석 중...")
    conn = db.connect()
    no_ad_raw   = db.get_no_ad_targets(conn, limit=args.limit)
    upgrade_raw = db.get_upgrade_targets(conn, limit=20)
    print(f"  ✓ 광고 미가입 타겟: {len(no_ad_raw)}개 | 업그레이드 타겟: {len(upgrade_raw)}개")

    all_regions = list({t.get("region", "") for t in no_ad_raw + upgrade_raw if t.get("region")})
    region_avgs = {r: db.get_region_ad_avg(conn, r) for r in all_regions}
    conn.close()
    print(f"  ✓ 지역 비교 데이터: {len(region_avgs)}개 지역")

    # ── 2. 스코어링 ──────────────────────────────────────────────────────
    print("\n🏆 우선순위 스코어링 중...")
    no_ad_targets   = scorer.score_targets(no_ad_raw,   target_type="no_ad")
    upgrade_targets = scorer.score_targets(upgrade_raw, target_type="upgrade")
    all_targets     = no_ad_targets + upgrade_targets

    grade_counts = {}
    for t in all_targets:
        grade_counts[t["grade"]] = grade_counts.get(t["grade"], 0) + 1
    print(f"  ✓ 등급 분포: {grade_counts}")

    if target_acm_ids:
        all_targets     = [t for t in all_targets     if t["acm_id"] in target_acm_ids]
        no_ad_targets   = [t for t in no_ad_targets   if t["acm_id"] in target_acm_ids]
        upgrade_targets = [t for t in upgrade_targets if t["acm_id"] in target_acm_ids]
        print(f"  ✓ 필터 후 대상: {len(all_targets)}개")

    # ── 3. Claude 이메일 생성 (항상 A/B급 대상으로 선제 생성) ────────────
    # Slack 리포트에 미리보기를 포함해야 하므로, stage=1이어도 생성
    print("\n🧠 Claude 개인화 이메일 생성 중...")
    email_candidates = (
        all_targets if target_acm_ids
        else [t for t in all_targets if t["grade"] in ("A", "B")][:30]
    )
    email_contents: dict = {}
    for t in email_candidates:
        region = t.get("region", "")
        avg    = region_avgs.get(region, {})
        try:
            content = claude_client.generate_email_body(t, avg)
            email_contents[t["acm_id"]] = content
        except Exception as e:
            print(f"  ⚠ 이메일 생성 실패 ({t['acm_name']}): {e}")
    print(f"  ✓ 이메일 본문 {len(email_contents)}개 생성 완료")

    slack_summary = ""
    if run_slack:
        slack_summary = claude_client.generate_slack_proposals(all_targets, region_avgs)
        print("  ✓ Slack 요약 생성 완료")

    # ── 4. Slack 리포트 발송 (이메일 미리보기 + 버튼 포함) ──────────────
    if run_slack:
        if not slack_channel or not slack_token:
            print("\n⚠️ UPSELL_SLACK_CHANNEL_ID 또는 AGENT_BOT_TOKEN 없음 — Slack 발송 스킵")
        else:
            print(f"\n📩 {'[DRY_RUN] ' if dry_run else ''}Slack 리포트 발송 중...")
            if not dry_run:
                blocks = stage1_slack.build_message(
                    no_ad_targets, upgrade_targets, region_avgs,
                    slack_summary, email_contents,
                )
                if args.schedule_slack:
                    # 이메일 미리보기 즉시 발송 → 메인 리포트 11시 예약
                    stage1_slack.post_preview_notice(
                        targets=email_candidates,
                        email_contents=email_contents,
                        channel_id=slack_channel,
                        bot_token=slack_token,
                    )
                    sid = stage1_slack.post_scheduled(blocks, slack_channel, slack_token)
                    if sid:
                        print("  ✓ 이메일 미리보기 즉시 발송 + 리포트 11시 예약 완료")
                    else:
                        print("  ✗ 예약 실패")
                else:
                    # 즉시 발송 (수동 테스트용)
                    ts = stage1_slack.post(blocks, slack_channel, slack_token)
                    if ts:
                        stage1_slack.post_email_threads(
                            targets=email_candidates,
                            email_contents=email_contents,
                            channel_id=slack_channel,
                            bot_token=slack_token,
                            thread_ts=ts,
                        )
                        print("  ✓ 리포트 + 이메일 미리보기 스레드 발송 완료")
                    else:
                        print("  ✗ 발송 실패")
            else:
                print(f"  [DRY_RUN] {len(all_targets)}개 타겟 Slack 발송 시뮬레이션")
                if email_contents:
                    sample = next(iter(email_contents.values()))
                    print(f"  이메일 미리보기 샘플:")
                    print(f"    제목: {sample.get('subject', '')}")
                    print(f"    본문: {sample.get('body', '')[:200]}...")

    # ── 5. 이메일 발송 (버튼 클릭 승인 후) ─────────────────────────────
    if run_email:
        print(f"\n{'[DRY_RUN] ' if dry_run else ''}이메일 발송 중...")
        send_list = [t for t in all_targets if t["acm_id"] in email_contents]
        stats = stage2_email.send_batch(
            targets=send_list,
            region_avgs=region_avgs,
            email_contents=email_contents,
            dry_run=dry_run,
            test_to=args.test_to,
        )
        print(f"  ✓ 완료: 발송 {stats['success']}건 | 스킵 {stats['skip']}건 | 실패 {stats['fail']}건")

    print("\n✅ 완료")


if __name__ == "__main__":
    main()
