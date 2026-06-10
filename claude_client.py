"""Claude API - 호스트별 개인화 업셀 제안 생성."""
from __future__ import annotations

import os
import anthropic

_client: anthropic.Anthropic | None = None


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


def generate_email_body(target: dict, region_avg: dict) -> dict:
    """호스트 이메일용 개인화 제안 (제목 + 본문 반환)."""
    avg_res = round(float(region_avg.get("avg_res", 0)), 1)
    extra_rev = target.get("extra_rev_90d", 0)
    current_pkg = target.get("advert_name", "없음")
    current_rate = target.get("advert_commission")
    current_rate_pct = int(float(current_rate) * 100) if current_rate else 0

    prompt = f"""당신은 미스터멘션 사업운영팀입니다.
아래 호스트에게 보낼 광고 업그레이드 제안 이메일을 작성하세요.

[호스트 정보]
- 숙소명: {target['acm_name']}
- 호스트명: {target['host_name']}
- 현재 패키지: {current_pkg} ({current_rate_pct}%)
- 최근 90일 예약: {target['res_90d']}건 / GMV {target['gmv_90d']:,}원
- 같은 지역 광고 숙소 평균: {avg_res}건
- 추천 패키지: {target['rec_package']} ({int(target['rec_rate']*100)}%)
- 추천 패키지 전환 시 예상 추가 수익(90일): 약 {extra_rev:,}원

작성 지침:
- 이메일 제목과 본문을 JSON으로 반환: {{"subject": "...", "body": "..."}}
- 호스트를 존중하는 정중한 어투 (존댓말)
- 현재 실적을 구체적 수치로 언급해 신뢰감 부여
- 지역 평균과 비교해 성장 가능성 제시
- 추천 패키지의 혜택(노출 우선순위, 추가 지원)을 2~3줄로 설명
- 마지막에 CTA: "지금 업그레이드 문의하기 → help@mrmention.co.kr"
- 발신자 서명은 반드시 '미스터멘션 사업운영팀'으로 작성 (영문 MrMention 사용 금지)
- 본문 500자 이내, HTML 태그 없이 순수 텍스트
- 반드시 JSON만 반환 (다른 텍스트 없이)"""

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = resp.content[0].text.strip()
    # JSON 블록 추출
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
