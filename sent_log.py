"""이메일 발송 이력 관리 (중복 발송 방지)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

_LOG_PATH = os.path.join(os.path.dirname(__file__), "sent_log.json")
KST = timezone(timedelta(hours=9))


def _load() -> dict:
    if os.path.exists(_LOG_PATH):
        with open(_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"emails": {}}


def _save(log: dict) -> None:
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def should_send(email: str, cooldown_days: int = 14) -> bool:
    """cooldown_days 이내 발송 이력 없으면 True."""
    if not email:
        return False
    log = _load()
    last_sent_str = log["emails"].get(email)
    if not last_sent_str:
        return True
    last_sent = datetime.fromisoformat(last_sent_str)
    return datetime.now(KST) - last_sent > timedelta(days=cooldown_days)


def mark_sent(email: str) -> None:
    log = _load()
    log["emails"][email] = datetime.now(KST).isoformat()
    _save(log)


def pending_emails(targets: list[dict], cooldown_days: int = 14) -> list[dict]:
    """발송 대상 중 cooldown 미경과 호스트만 필터링."""
    return [t for t in targets if should_send(t.get("host_email", ""), cooldown_days)]
