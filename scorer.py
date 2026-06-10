"""업셀 타겟 우선순위 스코어링."""
from __future__ import annotations


_GRADE_THRESHOLDS = [
    ("A", 20),
    ("B", 10),
    ("C", 3),
    ("D", 1),
]

_NEXT_PACKAGE = {
    None:  ("베이직 패키지", 0.10),
    0.10:  ("스타터 패키지", 0.15),
    0.15:  ("파트너 패키지", 0.20),
    0.20:  ("미멘 패키지",   0.30),
}


def grade(res_90d: int) -> str:
    for g, threshold in _GRADE_THRESHOLDS:
        if res_90d >= threshold:
            return g
    return "D"


def recommended_package(current_commission: float | None) -> tuple[str, float]:
    """현재 수수료율 기준으로 다음 업그레이드 패키지 반환."""
    key = None if current_commission is None else round(float(current_commission), 2)
    return _NEXT_PACKAGE.get(key, ("스타터 패키지", 0.15))


def expected_extra_revenue(gmv_90d: int, from_rate: float, to_rate: float) -> int:
    """수수료 업그레이드 시 추가 예상 수익 (90일 기준)."""
    return int(gmv_90d * (to_rate - from_rate))


def score_targets(targets: list[dict], target_type: str = "no_ad") -> list[dict]:
    """타겟 리스트에 등급·추천 패키지·예상 추가 수익 필드 추가."""
    result = []
    for t in targets:
        res_90d = int(t.get("res_90d", 0))
        gmv_90d = int(t.get("gmv_90d", 0))
        current_rate = t.get("advert_commission")  # None이면 미가입

        pkg_name, pkg_rate = recommended_package(current_rate)
        from_rate = float(current_rate) if current_rate else 0.0
        extra_rev = expected_extra_revenue(gmv_90d, from_rate, pkg_rate)

        result.append({
            **t,
            "grade":        grade(res_90d),
            "target_type":  target_type,
            "rec_package":  pkg_name,
            "rec_rate":     pkg_rate,
            "extra_rev_90d": extra_rev,
        })

    result.sort(key=lambda x: (x["grade"], -x["res_90d"]))
    return result
