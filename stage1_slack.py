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
            region  = t.get("region", "")
            avg_res = round(float(region_avgs.get(region, {}).get("avg_res", 0)), 1)
            emoji   = _grade_emoji(t["grade"])
            subject = email_contents.get(t["acm_id"], {}).get("subject", "—")
            has_email = t["acm_id"] in email_contents

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

            block: dict = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
            if has_email:
                block["accessory"] = _send_button(t["acm_id"])
            blocks.append(block)

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
            subject      = email_contents.get(t["acm_id"], {}).get("subject", "—")
            has_email    = t["acm_id"] in email_contents

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

            block: dict = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
            if has_email:
                block["accessory"] = _send_button(t["acm_id"])
            blocks.append(block)

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"총 {len(all_targets)}개 타겟 | 스레드에서 이메일 전문 확인 후 발송 버튼 클릭"}],
    })

    return blocks


def post(blocks: list[dict], channel_id: str, bot_token: str) -> str | None:
    """메인 메시지 발송. 성공 시 thread_ts 반환, 실패 시 None."""
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
