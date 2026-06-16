"""
호스트 월간 성과 리포트 에이전트

Usage:
  python run.py                          # 드라이런 (시뮬레이션)
  python run.py --execute                # 실제 발송
  python run.py --acm-ids 123,456 --execute  # 버튼 클릭 시 특정 숙소 발송
  python run.py --test-to me@email.com   # 테스트 발송
  python run.py --schedule-slack         # Slack 10시 예약 발송 모드
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
    parser = argparse.ArgumentParser(description="호스트 월간 성과 리포트 에이전트")
    parser.add_argument("--execute",       action="store_true", help="실제 발송 (기본: 드라이런)")
    parser.add_argument("--acm-ids",       dest="acm_ids", default="", help="발송 대상 숙소 ID comma-separated")
    parser.add_argument("--test-to",       dest="test_to", default="", help="테스트 발송 이메일")
    parser.add_argument("--schedule-slack", dest="schedule_slack", action="store_true", help="Slack 10시 예약 발송")
    parser.add_argument("--limit",         type=int, default=200, help="조회 숙소 수 (기본 200)")
    args = parser.parse_args()

    dry_run = not args.execute

    target_acm_ids: set[int] = set()
    if args.acm_ids:
        target_acm_ids = {int(x.strip()) for x in args.acm_ids.split(",") if x.strip()}
        print(f"=== 월간 리포트 이메일 발송 (버튼 승인) ===")
        print(f"DRY_RUN={dry_run} | 대상 숙소 {len(target_acm_ids)}개\n")
    else:
        print(f"=== 호스트 월간 성과 리포트 에이전트 ===")
        print(f"DRY_RUN={dry_run} | LIMIT={args.limit}\n")

    slack_channel = os.environ.get("UPSELL_SLACK_CHANNEL_ID", "")
    slack_token   = os.environ.get("AGENT_BOT_TOKEN", "")

    # ── 1. DB 조회 ──────────────────────────────────────────────────────────
    print("📊 DB 조회 중...")
    conn       = db.connect()
    month_label = db.get_report_month_label()
    hosts_raw  = db.get_ad_hosts(conn, limit=args.limit)
    print(f"  ✓ 광고 호스트: {len(hosts_raw)}개 ({month_label} 기준)")

    all_regions  = list({h.get("region", "") for h in hosts_raw if h.get("region")})
    region_avgs  = {r: db.get_region_monthly_avg(conn, r) for r in all_regions}
    conn.close()

    # ── 2. 성과 분류 ────────────────────────────────────────────────────────
    print("\n🏆 성과 분류 중...")
    hosts = scorer.score_hosts(hosts_raw, region_avgs)

    perf_counts: dict[str, int] = {}
    for h in hosts:
        p = h["perf"]
        perf_counts[p] = perf_counts.get(p, 0) + 1
    print(f"  ✓ 성과 분포: {perf_counts}")

    if target_acm_ids:
        hosts = [h for h in hosts if h["acm_id"] in target_acm_ids]
        print(f"  ✓ 필터 후: {len(hosts)}개")

    # ── 3. Claude 이메일 생성 ───────────────────────────────────────────────
    print(f"\n🧠 Claude 개인화 리포트 생성 중... ({len(hosts)}개)")
    email_contents: dict = {}
    for h in hosts:
        try:
            content = claude_client.generate_report_email(h, month_label)
            email_contents[h["acm_id"]] = content
        except Exception as e:
            print(f"  ⚠ 생성 실패 ({h['acm_name']}): {e}")
    print(f"  ✓ 이메일 {len(email_contents)}개 생성 완료")

    # ── 4. Slack 리포트 (acm_ids 없을 때만 = 버튼 클릭 모드 제외) ───────────
    if not target_acm_ids:
        slack_summary = claude_client.generate_slack_summary(hosts, month_label)
        print("  ✓ Slack 요약 생성 완료")

        if not slack_channel or not slack_token:
            print("\n⚠️ UPSELL_SLACK_CHANNEL_ID 또는 AGENT_BOT_TOKEN 없음 — Slack 발송 스킵")
        elif dry_run:
            print(f"\n  [DRY_RUN] {len(hosts)}개 Slack 발송 시뮬레이션")
            if email_contents:
                sample = next(iter(email_contents.values()))
                print(f"  샘플 제목: {sample.get('subject', '')}")
                print(f"  샘플 본문: {sample.get('body', '')[:200]}...")
        else:
            blocks = stage1_slack.build_message(hosts, slack_summary, email_contents, month_label)
            print(f"\n📩 Slack 리포트 발송 중...")

            if args.schedule_slack:
                stage1_slack.post_preview_notice(hosts, email_contents, slack_channel, slack_token)
                sid = stage1_slack.post_scheduled(blocks, slack_channel, slack_token)
                if sid:
                    print("  ✓ 이메일 미리보기 즉시 발송 + 리포트 10시 예약 완료")
                else:
                    print("  ✗ 예약 실패")
            else:
                ts = stage1_slack.post(blocks, slack_channel, slack_token)
                if ts:
                    stage1_slack.post_email_threads(hosts, email_contents, slack_channel, slack_token, ts)
                    print("  ✓ 리포트 + 이메일 미리보기 스레드 발송 완료")
                else:
                    print("  ✗ 발송 실패")

    # ── 5. 이메일 발송 (버튼 클릭으로 acm_ids 지정된 경우만) ─────────────────
    if target_acm_ids:
        send_list = [h for h in hosts if h["acm_id"] in email_contents]
        print(f"\n{'[DRY_RUN] ' if dry_run else ''}이메일 발송 중...")
        stats = stage2_email.send_batch(
            hosts=send_list,
            email_contents=email_contents,
            month_label=month_label,
            dry_run=dry_run,
            test_to=args.test_to,
        )
        print(f"  ✓ 완료: 발송 {stats['success']}건 | 스킵 {stats['skip']}건 | 실패 {stats['fail']}건")

    print("\n✅ 완료")


if __name__ == "__main__":
    main()
