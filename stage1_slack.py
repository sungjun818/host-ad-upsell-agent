"""1단계: Slack 영업팀 채널에 업셀 타겟 리포트 발송.

메시지 구조:
  [메인 메시지]  숙소 카드 (등급/예약수/이메일 제목/발송 버튼)
  [스레드]       숙소별 이메일 본문 전체 → 담당자가 내용 확인 후 버튼 클릭
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

KST = timezone(timedelta(hours=9))


def _grade_emoji(grade: str) -> str:
    return {"A": "🔴", "B": "🟠", "C": "🟡", "D": "⚪"}.get(grade, "")


def _fmt_phone(phone: str | None) -> str:
    if not phone:
        return "번호없음"
    p = str(phone).strip()
    if len(p) == 10:
        return f"{p[:3]}-{p[3:6]}-{p[6:]}"
    if len(p) == 11:
        return f"{p[:3]}-{p[3:7]}-{p[7:]}"
    return p


def _test_button(acm_id: int) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "🔍 테스트 발송"},
        "action_id": "test_upsell_email",
        "value": str(acm_id),
    }


def _send_button(acm_id: int) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "📧 발송"},
        "action_id": "send_upsell_email",
        "value": str(acm_id),
        "style": "primary",
        "confirm": {
            "title":   {"type": "plain_text", "text": "이메일 발송 확인"},
            "text":    {"type": "plain_text", "text": "스레드에서 이메일 내용을 확인하셨나요?\n이 호스트에게 이메일을 발송합니다."},
            "confirm": {"type": "plain_text", "text": "발송"},
            "deny":    {"type": "plain_text", "text": "취소"},
        },
    }


def _send_all_button(acm_ids: list[int]) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": f"✅ A/B급 전체 발송 ({len(acm_ids)}개)"},
        "action_id": "send_all_upsell",
        "value": ",".join(str(i) for i in acm_ids),
        "style": "primary",
        "confirm": {
            "title":   {"type": "plain_text", "text": "전체 발송 확인"},
            "text":    {"type": "plain_text", "text": f"스레드에서 이메일 내용을 모두 확인하셨나요?\n{len(acm_ids)}개 숙소 호스트에게 이메일을 발송합니다."},
            "confirm": {"type": "plain_text", "text": "전체 발송"},
            "deny":    {"type": "plain_text", "text": "취소"},
        },
    }


def build_message(
    no_ad_targets: list[dict],
    upgrade_targets: list[dict],
    region_avgs: dict,
    slack_summary: str,
    email_contents: dict,       # {acm_id: {subject, body}}
) -> list[dict]:
    """Slack Block Kit 메시지 블록 구성."""
    today       = datetime.now(KST).strftime("%Y-%m-%d")
    all_targets = no_ad_targets + upgrade_targets
    ab_ids      = [t["acm_id"] for t in all_targets if t.get("grade") in ("A", "B")]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📣 호스트 광고 업셀 리포트 — {today}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": slack_summary},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "💡 각 숙소의 *스레드*에서 이메일 전문을 확인한 후 발송 버튼을 눌러주세요."}],
        },
    ]

    # 전체 발송 버튼
    if ab_ids:
        blocks.append({
            "type": "actions",
            "elements": [_send_all_button(ab_ids)],
        })

    blocks.append({"type": "divider"})

    # ── 광고 미가입 타겟 ──────────────────────────────────────────────────
    if no_ad_targets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🆕 광고 미가입 타겟 (총 {len(no_ad_targets)}개)*"},
        })
        for t in no_ad_targets[:15]:
            region    = t.get("region", "")
            avg_res   = round(float(region_avgs.get(region, {}).get("avg_res", 0)), 1)
            emoji     = _grade_emoji(t["grade"])
            content   = email_contents.get(t["acm_id"], {})
            has_email = t["acm_id"] in email_contents
            subject   = content.get("subject", "—")
            body_prev = content.get("body", "")[:130].replace("\n", " ").strip() if has_email else ""

            text = (
                f"{emoji} *[{t['grade']}급]* {t['acm_name']}\n"
                f"90일 예약 *{t['res_90d']}건* (지역 광고 평균 {avg_res}건) | "
                f"GMV {t['gmv_90d']:,}원\n"
                f"추천: *{t['rec_package']}* ({int(t['rec_rate']*100)}%) | "
                f"추가 예상수익 *{t['extra_rev_90d']:,}원*\n"
                f"📧 {t['host_email']} | 📱 {_fmt_phone(t['host_phone'])}"
            )
            if has_email:
                text += f"\n✉️ *제목:* {subject}"
                if body_prev:
                    text += f"\n📝 _{body_prev}..._"

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
            if has_email:
                blocks.append({
                    "type": "actions",
                    "elements": [_test_button(t["acm_id"]), _send_button(t["acm_id"])],
                })

        blocks.append({"type": "divider"})

    # ── 수수료 업그레이드 타겟 ───────────────────────────────────────────
    if upgrade_targets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*⬆️ 수수료 업그레이드 타겟 (총 {len(upgrade_targets)}개)*"},
        })
        for t in upgrade_targets[:10]:
            emoji        = _grade_emoji(t["grade"])
            cur_rate_pct = int(float(t["advert_commission"]) * 100)
            content      = email_contents.get(t["acm_id"], {})
            has_email    = t["acm_id"] in email_contents
            subject      = content.get("subject", "—")
            body_prev    = content.get("body", "")[:130].replace("\n", " ").strip() if has_email else ""

            text = (
                f"{emoji} *[{t['grade']}급]* {t['acm_name']}\n"
                f"현재: {t['advert_name']} ({cur_rate_pct}%) | "
                f"90일 예약 *{t['res_90d']}건* | GMV {t['gmv_90d']:,}원\n"
                f"→ 추천: *{t['rec_package']}* ({int(t['rec_rate']*100)}%) | "
                f"추가 예상수익 *{t['extra_rev_90d']:,}원*\n"
                f"📧 {t['host_email']} | 📱 {_fmt_phone(t['host_phone'])}"
            )
            if has_email:
                text += f"\n✉️ *제목:* {subject}"
                if body_prev:
                    text += f"\n📝 _{body_prev}..._"

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
            if has_email:
                blocks.append({
                    "type": "actions",
                    "elements": [_test_button(t["acm_id"]), _send_button(t["acm_id"])],
                })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"총 {len(all_targets)}개 타겟 | 스레드에서 이메일 전문 확인 후 발송 버튼 클릭"}],
    })

    return blocks


def _next_monday_11am_kst() -> int:
    """다음(또는 오늘) 월요일 오전 11시 KST의 Unix timestamp 반환."""
    now = datetime.now(KST)
    days_to_monday = (7 - now.weekday()) % 7
    if days_to_monday == 0 and now.hour >= 11:
        days_to_monday = 7
    target = (now + timedelta(days=days_to_monday)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    return int(target.timestamp())


def post(blocks: list[dict], channel_id: str, bot_token: str) -> str | None:
    """메인 메시지 즉시 발송. 성공 시 thread_ts 반환, 실패 시 None."""
    client = WebClient(token=bot_token)
    try:
        resp = client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text="호스트 광고 업셀 리포트",
        )
        return resp["ts"]
    except SlackApiError as e:
        print(f"Slack 발송 실패: {e.response['error']}")
        return None


def post_scheduled(blocks: list[dict], channel_id: str, bot_token: str) -> str | None:
    """메인 리포트를 월요일 오전 11시 KST에 예약 발송. 성공 시 scheduled_message_id 반환."""
    client = WebClient(token=bot_token)
    post_at = _next_monday_11am_kst()
    try:
        resp = client.chat_scheduleMessage(
            channel=channel_id,
            blocks=blocks,
            text="호스트 광고 업셀 리포트",
            post_at=post_at,
        )
        import datetime as _dt
        scheduled_time = _dt.datetime.fromtimestamp(post_at, KST).strftime("%Y-%m-%d %H:%M KST")
        print(f"  → 예약 시각: {scheduled_time}")
        return resp["scheduled_message_id"]
    except SlackApiError as e:
        print(f"Slack 예약 발송 실패: {e.response['error']}")
        return None


def post_preview_notice(
    targets: list[dict],
    email_contents: dict,
    channel_id: str,
    bot_token: str,
    delay: float = 0.5,
) -> None:
    """이메일 전문을 즉시 발송 (11시 메인 리포트 검토용 미리보기)."""
    client = WebClient(token=bot_token)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        resp = client.chat_postMessage(
            channel=channel_id,
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"📋 *[{today}] 업셀 이메일 미리보기*\n"
                        "오전 11시에 발송될 리포트의 이메일 전문입니다.\n"
                        "스레드에서 내용 확인 후 *11시 메시지*에서 발송 버튼을 눌러주세요."
                    ),
                },
            }],
            text="업셀 이메일 미리보기",
        )
        thread_ts = resp["ts"]
    except SlackApiError as e:
        print(f"  ⚠ 미리보기 메시지 발송 실패: {e.response['error']}")
        return
    post_email_threads(targets, email_contents, channel_id, bot_token, thread_ts, delay)


def post_email_threads(
    targets: list[dict],
    email_contents: dict,
    channel_id: str,
    bot_token: str,
    thread_ts: str,
    delay: float = 0.5,
) -> None:
    """각 숙소의 이메일 전문을 메인 메시지 스레드로 첨부."""
    client = WebClient(token=bot_token)
    for t in targets:
        acm_id  = t["acm_id"]
        content = email_contents.get(acm_id)
        if not content:
            continue

        subject = content.get("subject", "")
        body    = content.get("body", "")

        thread_text = (
            f"*[{t['acm_name']}] 이메일 미리보기*\n\n"
            f"*수신:* {t.get('host_email', '')}\n"
            f"*제목:* {subject}\n\n"
            f"```{body}```"
        )

        try:
            client.chat_postMessage(
                channel=channel_id,
                text=thread_text,
                thread_ts=thread_ts,
                mrkdwn=True,
            )
            time.sleep(delay)
        except SlackApiError as e:
            print(f"  ⚠ 스레드 발송 실패 ({t['acm_name']}): {e.response['error']}")
