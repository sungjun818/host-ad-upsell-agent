"""월간 성과 분류."""
from __future__ import annotations


def classify(res_this: int, res_last: int) -> str:
    """
    growth : 전월 대비 +20% 이상
    stable : ±20% 이내
    poor   : 전월 대비 -20% 이상 감소
    zero   : 전월 예약 0건
    new    : 전전월 데이터 없음 (광고 첫 달)
    """
    if res_this == 0:
        return "zero"
    if res_last == 0:
        return "new"
    change = (res_this - res_last) / res_last
    if change >= 0.2:
        return "growth"
    if change <= -0.2:
        return "poor"
    return "stable"


def change_pct(res_this: int, res_last: int) -> float:
    if res_last == 0:
        return 0.0
    return (res_this - res_last) / res_last * 100


def performance_emoji(perf: str) -> str:
    return {"growth": "🟢", "stable": "🟡", "poor": "🔴", "zero": "🔴", "new": "🔵"}.get(perf, "⚪")


def is_price_high(host_price_per_res: float, region_avg_price: float) -> bool:
    """호스트 예약당 GMV가 지역 평균보다 30% 이상 높으면 True."""
    if region_avg_price <= 0 or host_price_per_res <= 0:
        return False
    return host_price_per_res > region_avg_price * 1.3


def score_hosts(hosts: list[dict], region_avgs: dict) -> list[dict]:
    """각 호스트에 성과 분류 및 가격 분석 필드 추가."""
    result = []
    for h in hosts:
        res_this = int(h.get("res_this_month", 0))
        res_last = int(h.get("res_last_month", 0))
        gmv_this = int(h.get("gmv_this_month", 0))
        region   = h.get("region", "")
        avg      = region_avgs.get(region, {})

        host_price_per_res = (gmv_this / res_this) if res_this > 0 else 0
        region_price       = float(avg.get("avg_price_per_res", 0))
        perf               = classify(res_this, res_last)

        result.append({
            **h,
            "perf":               perf,
            "change_pct":         round(change_pct(res_this, res_last), 1),
            "host_price_per_res": int(host_price_per_res),
            "region_avg_price":   int(region_price),
            "price_high":         is_price_high(host_price_per_res, region_price),
            "region_avg_res":     round(float(avg.get("avg_res", 0)), 1),
        })

    return result
