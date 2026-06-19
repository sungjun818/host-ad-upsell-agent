"""월간 리포트 이메일 발송 (Gmail SMTP)."""
from __future__ import annotations

import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import sent_log

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "monthly_report.html"
_SMTP_USER     = os.environ.get("SMTP_USER",    "partnerhost@mrmention.co.kr")
_FROM_EMAIL    = os.environ.get("FROM_EMAIL",   "marketing@mrmention.co.kr")
_FROM_NAME     = "미스터멘션 사업운영팀"
_MONITOR_EMAIL = os.environ.get("MONITOR_EMAIL", "marketing@mrmention.co.kr")


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _render(template: str, ctx: dict) -> str:
    import re
    html = template
    for key, val in ctx.items():
        html = html.replace(f"{{{{{key}}}}}", str(val))
    if ctx.get("show_pkg"):
        html = html.replace("{{#if_show_pkg}}", "").replace("{{/if_show_pkg}}", "")
    else:
        html = re.sub(r"\{\{#if_show_pkg\}\}.*?\{\{/if_show_pkg\}\}", "", html, flags=re.DOTALL)
    return html


def _build_context(host: dict, email_content: dict, month_label: str) -> dict:
    res_this = int(host.get("res_this_month", 0))
    res_last = int(host.get("res_last_month", 0))
    gmv_this = int(host.get("gmv_this_month", 0))
    change   = host.get("change_pct", 0.0)
    perf     = host.get("perf", "stable")

    if change > 0:
        change_arrow = f"▲ {change:.1f}%"
        change_color = "#2e7d32"
    elif change < 0:
        change_arrow = f"▼ {abs(change):.1f}%"
        change_color = "#c62828"
    else:
        change_arrow = "—"
        change_color = "#888"

    perf_label = {
        "growth": "성장 🟢", "stable": "유지 🟡", "poor": "저조 🔴",
        "zero": "예약 없음 🔴", "new": "첫 달 🔵",
    }.get(perf, "—")

    return {
        "month_label":    month_label,
        "host_name":      host.get("host_name", "호스트"),
        "acm_name":       host.get("acm_name", ""),
        "acm_id":         host.get("acm_id", ""),
        "pkg_name":       host.get("advert_name", ""),
        "show_pkg":       perf != "zero",
        "res_this_month": res_this,
        "gmv_this_fmt":   f"{gmv_this:,}",
        "res_last_month": res_last,
        "change_arrow":   change_arrow,
        "change_color":   change_color,
        "region_avg_res": host.get("region_avg_res", 0),
        "perf_label":     perf_label,
        "email_body":     email_content.get("body", ""),
    }


def send_one(
    host: dict,
    email_content: dict,
    month_label: str,
    smtp_conn: smtplib.SMTP,
    dry_run: bool = True,
    test_to: str = "",
) -> bool:
    to_email = test_to if test_to else host.get("host_email", "")
    if not to_email:
        print(f"  ⚠ 이메일 없음: {host.get('acm_name')}")
        return False

    subject = email_content.get("subject", f"미스터멘션 {month_label} 월간 성과 리포트")
    if test_to:
        subject = f"[테스트] {subject}"

    ctx = _build_context(host, email_content, month_label)
    html_body = _render(_load_template(), ctx)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{_FROM_NAME} <{_FROM_EMAIL}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(email_content.get("body", ""), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if dry_run:
        print(f"  [DRY_RUN] → {to_email} | {subject}")
        return True

    try:
        recipients = [to_email, _MONITOR_EMAIL] if _MONITOR_EMAIL != to_email else [to_email]
        smtp_conn.sendmail(_FROM_EMAIL, recipients, msg.as_string())
        if not test_to:
            sent_log.mark_sent(to_email)
        print(f"  ✓ 발송 완료: {to_email} (BCC: {_MONITOR_EMAIL})")
        return True
    except Exception as e:
        print(f"  ✗ 발송 실패 ({to_email}): {e}")
        return False


def send_batch(
    hosts: list[dict],
    email_contents: dict,
    month_label: str,
    dry_run: bool = True,
    delay_sec: float = 2.0,
    test_to: str = "",
) -> dict:
    cooldown = 25 if not dry_run else 0
    pending  = sent_log.pending_hosts(hosts, cooldown_days=cooldown)

    print(f"\n📧 발송 대상: {len(pending)}/{len(hosts)}개 (쿨다운 제외)")
    if not pending:
        return {"success": 0, "skip": len(hosts), "fail": 0}

    stats = {"success": 0, "skip": len(hosts) - len(pending), "fail": 0}

    if dry_run:
        for h in pending:
            content = email_contents.get(h["acm_id"], {"subject": "리포트", "body": ""})
            ok = send_one(h, content, month_label, smtp_conn=None, dry_run=True, test_to=test_to)
            stats["success" if ok else "fail"] += 1
        return stats

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(_SMTP_USER, os.environ["SMTP_PASSWORD"])
        for h in pending:
            content = email_contents.get(h["acm_id"], {"subject": "리포트", "body": ""})
            ok = send_one(h, content, month_label, smtp_conn=server, dry_run=False, test_to=test_to)
            stats["success" if ok else "fail"] += 1
            if ok:
                time.sleep(delay_sec)

    return stats
