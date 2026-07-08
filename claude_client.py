"""Claude API - 호스트별 개인화 업셀 제안 생성."""
from __future__ import annotations

import os
import anthropic

_client: anthropic.Anthropic | None = None

_KOREAN_FIXES = {
    "쿠pon": "쿠폰", "쿠Pon": "쿠폰", "쿠PON": "쿠폰",
    "이vent": "이벤트", "이Vent": "이벤트", "이ven트": "이벤트",
    "쿠pon이": "쿠폰이", "쿠pon을": "쿠폰을", "쿠pon은": "쿠폰은",
    "coupon": "쿠폰", "Coupon": "쿠폰", "COUPON": "쿠폰",
    "push": "푸시", "PUSH": "푸시",
    "marketing": "마케팅", "Marketing": "마케팅",
    "package": "패키지", "Package": "패키지",
}


def _fix_korean(text: str) -> str:
    """한국어 단어 중 영문 혼용 오류 교정."""
    for wrong, right in _KOREAN_FIXES.items():
        text = text.replace(wrong, right)
    return text


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def generate_slack_proposals(targets: list[dict], region_avgs: dict) -> str:
    """Slack용 영업팀 업셀 타겟 리포트 생성."""
    lines = []
    for t in targets[:20]:
        region = t.get("region", "")
        avg = region_avgs.get(region, {})
        avg_res = round(float(avg.get("avg_res", 0)), 1)
        lines.append(
            f"- [{t['grade']}급] {t['acm_name']} | "
            f"90일 예약 {t['res_90d']}건 (지역 광고 숙소 평균 {avg_res}건) | "
            f"추천: {t['rec_package']}({int(t['rec_rate']*100)}%) | "
            f"GMV {t['gmv_90d']:,}원 | "
            f"호스트: {t['host_name']} / {t['host_email']} / {t['host_phone']}"
        )

    prompt = f"""당신은 MrMention(미르멘션) 숙박 플랫폼의 영업 전략가입니다.
아래 업셀 타겟 숙소 목록을 바탕으로 영업팀을 위한 Slack 메시지를 작성하세요.

[업셀 타겟 목록]
{chr(10).join(lines)}

작성 지침:
- 전체 요약을 1~2문장으로 시작 (총 타겟 수, 예상 추가 수익 강조)
- A급 숙소는 "이번 주 즉시 연락" 표시
- 각 숙소별 30~40자 이내의 핵심 영업 포인트 1줄 추가
- 마지막에 이번 주 영업 액션 아이템 3가지 제시
- Slack 마크다운(*볼드*, 이모지) 사용
- 전체 700자 이내"""

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


_PACKAGE_BENEFITS = {
    "스타터 패키지": "숙소 균등 노출(알고리즘 기반), 월간 이벤트 쿠폰 적용, SNS 마케팅(미스터멘션 공식 SNS 노출)",
    "파트너 패키지": "숙소 균등 노출, 월간 이벤트 쿠폰 적용, SNS 마케팅, 별도 할인 쿠폰 제공, 이벤트 테마 노출, 앱 내 광고 활용(앱 PUSH 발송)",
    "미멘 패키지": "숙소 균등 노출, 월간 이벤트 쿠폰 적용, SNS 마케팅, 별도 할인 쿠폰 제공, 이벤트 테마 노출, 앱 PUSH 발송, 인플루언서 마케팅 활용, 메인 페이지 숙소 노출",
}


def generate_email_body(target: dict, region_avg: dict) -> dict:
    """호스트 이메일용 개인화 제안 (제목 + 본문 반환)."""
    ad_acm_cnt = int(region_avg.get("ad_acm_cnt", 0))
    extra_rev = target.get("extra_rev_90d", 0)
    current_pkg = target.get("advert_name", "없음")
    current_rate = target.get("advert_commission")
    current_rate_pct = int(float(current_rate) * 100) if current_rate else 0
    rec_pkg = target['rec_package']
    rec_benefits = _PACKAGE_BENEFITS.get(rec_pkg, "")

    prompt = f"""당신은 미스터멘션 사업운영팀입니다.
아래 호스트에게 보낼 광고 업그레이드 제안 이메일을 작성하세요.

[호스트 정보]
- 숙소명: {target['acm_name']}
- 호스트명: {target['host_name']}
- 현재 패키지: {current_pkg} ({current_rate_pct}%)
- 최근 90일 예약: {target['res_90d']}건 / GMV {target['gmv_90d']:,}원
- 같은 지역 내 광고 경쟁 숙소 수: {ad_acm_cnt}개
- 추천 패키지: {rec_pkg} ({int(target['rec_rate']*100)}%)
- 추천 패키지 신청 시 예상 추가 수익(90일): 약 {extra_rev:,}원

[{rec_pkg} 혜택]
{rec_benefits}

작성 지침:
- 이메일 제목과 본문을 JSON으로 반환: {{"subject": "...", "body": "..."}}
- 호스트를 존중하는 정중한 어투 (존댓말)
- 현재 실적({target['res_90d']}건)을 구체적 수치로 언급해 신뢰감 부여
- "같은 지역에서 {ad_acm_cnt}개 숙소가 이미 광고 중"이라는 사실로 선점 urgency 자극 (경쟁 강조, 낮은 평균 수치 언급 금지)
- 위의 [{rec_pkg} 혜택] 항목들을 이메일 본문에 자연스럽게 녹여 2~3줄로 설명 (혜택 목록을 그대로 나열하지 말고 문장으로 풀어서 작성)
- CTA 버튼 문구는 본문에 포함하지 말 것 (HTML 템플릿에서 자동 삽입됨)
- 발신자 서명은 반드시 '미스터멘션 사업운영팀'으로 작성 (영문 MrMention 사용 금지)
- 한국어 단어 중간에 영문자 절대 혼용 금지 (예: '쿠pon' → '쿠폰', '이ven트' → '이벤트')
- 본문 500자 이내, HTML 태그 없이 순수 텍스트
- 반드시 JSON만 반환 (다른 텍스트 없이)"""

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    result = json.loads(text)
    result["subject"] = _fix_korean(result.get("subject", ""))
    result["body"]    = _fix_korean(result.get("body", ""))
    return result
