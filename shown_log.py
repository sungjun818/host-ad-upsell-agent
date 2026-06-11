"""Slack 리포트 노출 이력 관리 (같은 숙소 반복 노출 방지)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

_LOG_PATH = os.path.join(os.path.dirname(__file__), "shown_log.json")
KST = timezone(timedelta(hours=9))


def _load() -> dict:
    if os.path.exists(_LOG_PATH):
        with open(_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"acms": {}}


def _save(log: dict) -> None:
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def recently_shown(acm_id: int, cooldown_days: int = 7) -> bool:
    """cooldown_days 이내 Slack 노출 이력 있으면 True."""
    log = _load()
    last_str = log["acms"].get(str(acm_id))
    if not last_str:
        return False
    last = datetime.fromisoformat(last_str)
    return datetime.now(KST) - last < timedelta(days=cooldown_days)


def mark_shown(acm_ids: list[int]) -> None:
    """해당 숙소들을 '오늘 노출됨'으로 기록."""
    log = _load()
    now_str = datetime.now(KST).isoformat()
    for acm_id in acm_ids:
        log["acms"][str(acm_id)] = now_str
    _save(log)


def filter_new_targets(targets: list[dict], cooldown_days: int = 7) -> list[dict]:
    """최근 cooldown_days일 이내 Slack에 노출된 숙소 제외."""
    return [t for t in targets if not recently_shown(t["acm_id"], cooldown_days)]
