"""월간 리포트 발송 이력 (월 1회 제한)."""
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
    return {"hosts": {}}


def _save(log: dict) -> None:
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def should_send(email: str, cooldown_days: int = 25) -> bool:
    """cooldown_days 이내 발송 이력 없으면 True (월 1회 제한)."""
    if not email:
        return False
    log = _load()
    last_str = log["hosts"].get(email)
    if not last_str:
        return True
    last = datetime.fromisoformat(last_str)
    return datetime.now(KST) - last > timedelta(days=cooldown_days)


def mark_sent(email: str) -> None:
    log = _load()
    log["hosts"][email] = datetime.now(KST).isoformat()
    _save(log)


def pending_hosts(hosts: list[dict], cooldown_days: int = 25) -> list[dict]:
    return [h for h in hosts if should_send(h.get("host_email", ""), cooldown_days)]
