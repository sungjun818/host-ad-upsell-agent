"""2단계: 호스트에게 직접 이메일 발송 (Gmail SMTP)."""
from __future__ import annotations

import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import sent_log

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "upsell_email.html"
_SMTP_USER     = os.environ.get("SMTP_USER",    "partnerhost@mrmention.co.kr")
_FROM_EMAIL    = os.environ.get("FROM_EMAIL",   "marketing@mrmention.co.kr")
_FROM_NAME     = "미스터멘션 사업운영팀"
_MONITOR_EMAIL = os.environ.get("MONITOR_EMAIL", "marketing@mrmention.co.kr")


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _render(template: str, ctx: dict) -> str:
    html = template
    for key, val in ctx.items():
        html = html.replace(f"{{{{{key}}}}}", str(val))
    # 비교 블록 처리
    if int(ctx.get("ad_acm_cnt", 0)) > 0:
        html = html.replace("{{#if_compare}}", "").replace("{{/if_compare}}", "")
    else:
        import re
        html = re.sub(r"\{\{#if_compare\}\}.*?\{\{/if_compare\}\}", "", html, flags=re.DOTALL)
    return html


def _build_context(target: dict, region_avg: dict, email_content: dict) -> dict:
    avg_res = round(float(region_avg.get("avg_res", 0)), 1)
    current_pkg = target.get("advert_name") or "미가입"
    extra_rev = target.get("extra_rev_90d", 0)
    subject = email_content.get("subject", "미스터멘션 파트너 성장 제안")

    ad_acm_cnt = int(region_avg.get("ad_acm_cnt", 0))
    return {
        "host_name":    target.get("host_name", "호스트"),
        "acm_name":     target.get("acm_name", ""),
        "acm_id":       target.get("acm_id", ""),
        "res_90d":      target.get("res_90d", 0),
        "gmv_90d_fmt":  f"{int(target.get('gmv_90d', 0)):,}",
        "current_pkg":  current_pkg,
        "avg_res":      avg_res,
        "ad_acm_cnt":   ad_acm_cnt,
        "extra_rev_fmt": f"{extra_rev:,}",
        "rec_package":  target.get("rec_package", ""),
        "rec_rate_pct": int(float(target.get("rec_rate", 0)) * 100),
        "email_body":   email_content.get("body", ""),
    }


def send_one(
    target: dict,
    region_avg: dict,
    email_content: dict,
    smtp_conn: smtplib.SMTP,
    dry_run: bool = True,
    test_to: str = "",
) -> bool:
    """단일 호스트에게 이메일 발송. test_to 지정 시 해당 주소로 테스트 발송."""
    to_email = test_to if test_to else target.get("host_email", "")
    if not to_email:
        print(f"  ⚠ 이메일 없음: {target.get('acm_name')}")
        return False

    subject = email_content.get("subject", "미스터멘션 파트너 성장 제안")
    if test_to:
        subject = f"[테스트] {subject}"
    ctx = _build_context(target, region_avg, email_content)
    html_body = _render(_load_template(), ctx)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_FROM_NAME} <{_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(email_content.get("body", ""), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if dry_run:
        print(f"  [DRY_RUN] → {to_email} | {subject}")
        return True

    try:
        recipients = [to_email, _MONITOR_EMAIL] if _MONITOR_EMAIL != to_email else [to_email]
        smtp_conn.sendmail(_FROM_EMAIL, recipients, msg.as_string())
        sent_log.mark_sent(to_email)
        print(f"  ✓ 발송 완료: {to_email} (모니터링 BCC: {_MONITOR_EMAIL})")
        return True
    except Exception as e:
        print(f"  ✗ 발송 실패 ({to_email}): {e}")
        return False


def send_batch(
    targets: list[dict],
    region_avgs: dict,
    email_contents: dict,
    dry_run: bool = True,
    delay_sec: float = 2.0,
    test_to: str = "",
) -> dict:
    """배치 이메일 발송. email_contents: {acm_id: {subject, body}}"""
    cooldown = 14 if not dry_run else 0
    pending  = sent_log.pending_emails(targets, cooldown_days=cooldown)
    blocked  = sent_log.blocked_emails(targets, cooldown_days=cooldown) if not dry_run else []

    print(f"\n📧 이메일 발송 대상: {len(pending)}/{len(targets)}개 (쿨다운 제외)")
    if blocked:
        for b in blocked:
            print(f"  ⏳ 쿨다운 차단: {b['acm_name']} — 다음 발송 가능일 {b['next_available']}")

    if not pending:
        return {"success": 0, "skip": len(targets), "fail": 0, "blocked": blocked}

    stats = {"success": 0, "skip": len(targets) - len(pending), "fail": 0, "blocked": blocked}

    if dry_run:
        for t in pending:
            region = t.get("region", "")
            avg = region_avgs.get(region, {})
            content = email_contents.get(t["acm_id"], {"subject": "제안", "body": ""})
            ok = send_one(t, avg, content, smtp_conn=None, dry_run=True, test_to=test_to)
            stats["success" if ok else "fail"] += 1
        return stats

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = _SMTP_USER
    smtp_pass = os.environ["SMTP_PASSWORD"]

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)

        for t in pending:
            region = t.get("region", "")
            avg = region_avgs.get(region, {})
            content = email_contents.get(t["acm_id"], {"subject": "제안", "body": ""})
            ok = send_one(t, avg, content, smtp_conn=server, dry_run=False, test_to=test_to)
            stats["success" if ok else "fail"] += 1
            if ok:
                time.sleep(delay_sec)

    return stats
