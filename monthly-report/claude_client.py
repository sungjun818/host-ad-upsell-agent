"""Claude API — 호스트별 개인화 월간 리포트 생성."""
from __future__ import annotations

import os
import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_PERF_GUIDE = {
    "growth": "축하와 긍정적 에너지로 시작. 성장세를 유지하려면 더 높은 패키지 혜택이 도움될 수 있음을 자연스럽게 언급.",
    "stable": "안정적 운영을 격려. 성수기/특수 시즌 대비 전략 팁 1가지 제안.",
    "poor":   "공감하는 어조로 시작. 비수기·경쟁 심화 등 외부 요인을 먼저 언급하고, 가격 전략과 사진/설명 개선을 조언. 강요하지 않고 제안하는 톤.",
    "zero":   "부드럽지만 솔직하게. 전월 예약이 0건임을 사실로 짚고, 광고 효과를 높이기 위해 숙소 가격 경쟁력·사진·설명·응답률 점검을 구체적으로 조언. 미스터멘션도 함께 고민하고 있다는 연대감 표현.",
    "new":    "첫 달 광고 시작을 축하. 데이터 축적 중임을 안내하고, 좋은 첫인상을 위한 팁 제안.",
}

_UPGRADE_PACKAGES = {
    0.15: ("파트너 패키지", "별도 할인 쿠폰 제공, 이벤트 테마 노출, 앱 PUSH 발송"),
    0.20: ("미멘 패키지",   "인플루언서 마케팅 활용, 메인 페이지 숙소 노출"),
}


def generate_report_email(host: dict, month_label: str) -> dict:
    """호스트 개인화 월간 리포트 이메일 생성."""
    perf         = host.get("perf", "stable")
    res_this     = int(host.get("res_this_month", 0))
    res_last     = int(host.get("res_last_month", 0))
    gmv_this     = int(host.get("gmv_this_month", 0))
    change       = host.get("change_pct", 0.0)
    region_avg   = host.get("region_avg_res", 0.0)
    price_high   = host.get("price_high", False)
    host_price   = host.get("host_price_per_res", 0)
    region_price = host.get("region_avg_price", 0)
    commission   = round(float(host.get("advert_commission", 0.15)), 2)
    pkg_name     = host.get("advert_name", "")

    # 업그레이드 제안 여부
    upgrade_info = _UPGRADE_PACKAGES.get(commission)
    upgrade_text = ""
    if upgrade_info and perf == "growth":
        up_pkg, up_benefits = upgrade_info
        upgrade_text = f"\n[업그레이드 옵션]\n추천 패키지: {up_pkg}\n추가 혜택: {up_benefits}"

    # 가격 조언 여부
    price_advice = ""
    if price_high and perf in ("poor", "zero") and region_price > 0:
        price_advice = (
            f"\n[가격 참고 데이터]\n"
            f"귀 숙소 예약당 평균 금액: 약 {host_price:,}원\n"
            f"같은 지역 광고 숙소 평균: 약 {region_price:,}원\n"
            f"→ 지역 평균 대비 높은 편입니다. 가격 경쟁력 점검을 권장합니다."
        )

    guide = _PERF_GUIDE.get(perf, _PERF_GUIDE["stable"])

    prompt = f"""당신은 미스터멘션 사업운영팀입니다.
아래 호스트에게 보낼 {month_label} 월간 성과 리포트 이메일을 작성하세요.

[호스트 정보]
- 숙소명: {host['acm_name']}
- 호스트명: {host['host_name']}
- 현재 패키지: {pkg_name} ({int(commission * 100)}%)
- {month_label} 예약: {res_this}건 / GMV {gmv_this:,}원
- 전월 대비: {'+' if change >= 0 else ''}{change:.1f}%
- 같은 지역 광고 숙소 평균: {region_avg}건
- 성과 분류: {perf}
{price_advice}
{upgrade_text}

[작성 가이드]
{guide}

작성 지침:
- 이메일 제목과 본문을 JSON으로 반환: {{"subject": "...", "body": "..."}}
- 호스트를 존중하는 정중한 어투 (존댓말)
- 구체적 수치({month_label} 예약 {res_this}건, GMV {gmv_this:,}원 등)를 자연스럽게 언급
- 조언은 강요가 아닌 제안 형태로
- 마지막에 CTA: "로그인하고 성과 확인하기 → [버튼]" 과 "1:1 문의하기 → [버튼]" 안내
- 발신자 서명: '미스터멘션 사업운영팀' (영문 MrMention 사용 금지)
- 본문 600자 이내, HTML 태그 없이 순수 텍스트
- 반드시 JSON만 반환"""

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def generate_slack_summary(hosts: list[dict], month_label: str) -> str:
    """Slack용 월간 리포트 요약 생성."""
    counts = {}
    for h in hosts:
        p = h.get("perf", "stable")
        counts[p] = counts.get(p, 0) + 1

    lines = [
        f"- 🟢 성장: {counts.get('growth', 0)}개",
        f"- 🟡 유지: {counts.get('stable', 0) + counts.get('new', 0)}개",
        f"- 🔴 저조/0건: {counts.get('poor', 0) + counts.get('zero', 0)}개",
    ]

    prompt = f"""당신은 미스터멘션 사업운영팀 매니저입니다.
{month_label} 월간 광고 성과 리포트 결과를 Slack 채널에 공유하는 메시지를 작성하세요.

[성과 분포]
{chr(10).join(lines)}
총 {len(hosts)}개 숙소

작성 지침:
- 2~3문장으로 전체 요약 (주목할 숙소 유형, 이번 달 특이사항)
- 저조/0건 숙소는 "가격·퀄리티 점검 필요" 관점에서 언급
- Slack 마크다운(*볼드*, 이모지) 사용
- 200자 이내"""

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
