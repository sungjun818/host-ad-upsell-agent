"""Slack 영업팀 채널에 월간 리포트 발송."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

KST = timezone(timedelta(hours=9))


def _perf_emoji(perf: str) -> str:
    return {"growth": "🟢", "stable": "🟡", "poor": "🔴", "zero": "🔴", "new": "🔵"}.get(perf, "⚪")


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
        "action_id": "test_monthly_report",
        "value": str(acm_id),
    }


def _send_button(acm_id: int) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "📧 발송"},
        "action_id": "send_monthly_report",
        "value": str(acm_id),
        "style": "primary",
        "confirm": {
            "title":   {"type": "plain_text", "text": "리포트 발송 확인"},
            "text":    {"type": "plain_text", "text": "이메일 내용을 확인하셨나요?\n이 호스트에게 월간 리포트를 발송합니다."},
            "confirm": {"type": "plain_text", "text": "발송"},
            "deny":    {"type": "plain_text", "text": "취소"},
        },
    }


def _send_all_button(acm_ids: list[int]) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": f"✅ 전체 발송 ({len(acm_ids)}개)"},
        "action_id": "send_all_monthly_report",
        "value": ",".join(str(i) for i in acm_ids),
        "style": "primary",
        "confirm": {
            "title":   {"type": "plain_text", "text": "전체 발송 확인"},
            "text":    {"type": "plain_text", "text": f"모든 이메일 내용을 확인하셨나요?\n{len(acm_ids)}개 숙소에 월간 리포트를 발송합니다."},
            "confirm": {"type": "plain_text", "text": "전체 발송"},
            "deny":    {"type": "plain_text", "text": "취소"},
        },
    }


def build_message(
    hosts: list[dict],
    slack_summary: str,
    email_contents: dict,
    month_label: str,
) -> list[dict]:
    """메인 Slack 메시지: 요약 + 전체발송 버튼 + 숙소 목록 (블록 한도 고려해 카드 최대 20개)."""
    today   = datetime.now(KST).strftime("%Y-%m-%d")
    all_ids = [h["acm_id"] for h in hosts if h["acm_id"] in email_contents]

    perf_counts: dict[str, int] = {}
    for h in hosts:
        p = h.get("perf", "stable")
        perf_counts[p] = perf_counts.get(p, 0) + 1

    summary_text = (
        f"{slack_summary}\n\n"
        f"🟢 성장 {perf_counts.get('growth', 0)}개 | "
        f"🟡 유지 {perf_counts.get('stable', 0) + perf_counts.get('new', 0)}개 | "
        f"🔴 저조/0건 {perf_counts.get('poor', 0) + perf_counts.get('zero', 0)}개 | "
        f"총 *{len(hosts)}개*"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 {month_label} 호스트 월간 성과 리포트 — {today}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": "💡 스레드에서 각 호스트 이메일 전문을 확인한 후 발송 버튼을 눌러주세요."}]},
    ]

    if all_ids:
        blocks.append({"type": "actions", "elements": [_send_all_button(all_ids)]})

    blocks.append({"type": "divider"})

    # 숙소 카드: Slack 블록 한도(50) 고려해 최대 20개 표시
    # 나머지는 스레드에서 확인 가능
    for h in hosts[:20]:
        acm_id         = h["acm_id"]
        perf           = h.get("perf", "stable")
        emoji          = _perf_emoji(perf)
        change         = h.get("change_pct", 0.0)
        change_str     = f"+{change:.1f}%" if change > 0 else f"{change:.1f}%"
        has_email      = acm_id in email_contents
        subject        = email_contents.get(acm_id, {}).get("subject", "—") if has_email else "—"
        commission_pct = int(float(h.get("advert_commission", 0)) * 100)

        text = (
            f"{emoji} *{h['acm_name']}*\n"
            f"{h.get('advert_name', '')} ({commission_pct}%) | "
            f"전월 *{h.get('res_this_month', 0)}건* ({change_str}) | "
            f"GMV {int(h.get('gmv_this_month', 0)):,}원\n"
            f"📧 {h.get('host_email', '')} | 📱 {_fmt_phone(h.get('host_phone'))}"
        )
        if h.get("price_high"):
            text += f"\n⚠️ 예약당 {int(h.get('host_price_per_res', 0)):,}원 (지역 평균 {int(h.get('region_avg_price', 0)):,}원) — 가격 점검"
        if has_email:
            text += f"\n✉️ *제목:* {subject}"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        if has_email:
            blocks.append({"type": "actions", "elements": [_test_button(acm_id), _send_button(acm_id)]})

    if len(hosts) > 20:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"📌 이하 {len(hosts) - 20}개 숙소는 스레드에서 확인하세요."}]})

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": f"총 {len(hosts)}개 숙소 | {month_label} 전월 성과 기준"}]})
    return blocks


def _next_10am_kst() -> int:
    now    = datetime.now(KST)
    target = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int(target.timestamp())


def post(blocks: list[dict], channel_id: str, bot_token: str) -> str | None:
    client = WebClient(token=bot_token)
    try:
        resp = client.chat_postMessage(channel=channel_id, blocks=blocks, text="호스트 월간 성과 리포트")
        return resp["ts"]
    except SlackApiError as e:
        print(f"Slack 발송 실패: {e.response['error']}")
        return None


def post_scheduled(blocks: list[dict], channel_id: str, bot_token: str) -> str | None:
    client  = WebClient(token=bot_token)
    post_at = _next_10am_kst()
    try:
        resp = client.chat_scheduleMessage(
            channel=channel_id, blocks=blocks,
            text="호스트 월간 성과 리포트", post_at=post_at,
        )
        import datetime as _dt
        t = _dt.datetime.fromtimestamp(post_at, KST).strftime("%Y-%m-%d %H:%M KST")
        print(f"  → 예약 시각: {t}")
        return resp["scheduled_message_id"]
    except SlackApiError as e:
        print(f"Slack 예약 발송 실패: {e.response['error']}")
        return None


def post_email_threads(
    hosts: list[dict],
    email_contents: dict,
    channel_id: str,
    bot_token: str,
    thread_ts: str,
    delay: float = 0.5,
) -> None:
    client = WebClient(token=bot_token)
    for h in hosts:
        acm_id  = h["acm_id"]
        content = email_contents.get(acm_id)
        if not content:
            continue
        thread_text = (
            f"*[{h['acm_name']}] 월간 리포트 미리보기*\n\n"
            f"*수신:* {h.get('host_email', '')}\n"
            f"*제목:* {content.get('subject', '')}\n\n"
            f"```{content.get('body', '')}```"
        )
        try:
            client.chat_postMessage(channel=channel_id, text=thread_text, thread_ts=thread_ts, mrkdwn=True)
            time.sleep(delay)
        except SlackApiError as e:
            print(f"  ⚠ 스레드 발송 실패 ({h['acm_name']}): {e.response['error']}")


def post_preview_notice(
    hosts: list[dict],
    email_contents: dict,
    channel_id: str,
    bot_token: str,
) -> None:
    client = WebClient(token=bot_token)
    today  = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        resp = client.chat_postMessage(
            channel=channel_id,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": (
                f"📋 *[{today}] 월간 리포트 이메일 미리보기*\n"
                "오전 10시에 발송될 리포트의 이메일 전문입니다.\n"
                "스레드에서 내용 확인 후 *10시 메시지*의 발송 버튼을 눌러주세요."
            )}}],
            text="월간 리포트 이메일 미리보기",
        )
        post_email_threads(hosts, email_contents, channel_id, bot_token, resp["ts"])
    except SlackApiError as e:
        print(f"  ⚠ 미리보기 발송 실패: {e.response['error']}")
