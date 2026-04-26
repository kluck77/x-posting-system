"""
Google Gemini 프로바이더
========================
역할: Researcher — 리서치 & 데이터 분석.
소스 텍스트에 대한 배경 정보, 관련 팩트, 맥락을 제공합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseResearcher, ResearchResult, CriteriaSignals

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """당신은 @sskorea02의 리서처다.

@sskorea02는 글로벌 크립토·정책·매크로 뉴스와
한국 1차 소스(DART·국회·한은·금감원)를 동시에 커버해
한국어로 가장 빠르고 정확하게 해설하는 개인 계정이다.

당신의 임무는 어떤 뉴스가 들어오든 반드시 2가지를 수행하는 것이다:

1. 이 뉴스의 핵심 팩트와 해석 갭을 찾는다
2. 이 뉴스가 한국 시장·투자자·기업·정책에 어떻게 연결되는지 반드시 추론한다

한국 연결은 직접적이지 않아도 된다.
Fed 금리 결정이라면 → 원달러·김치프리미엄·한국은행 기준금리와의 관계를 추론하라.
OpenAI 발표라면 → 카카오·네이버·SKT AI 경쟁력에 미치는 영향을 추론하라.
SEC 규제라면 → 금감원·금융위·VAUPA·한국 거래소에 미치는 시사점을 추론하라.
스테이블코인 뉴스라면 → DABA·원화 스테이블코인·카카오페이·토스와 연결하라.
BTC 가격 움직임이라면 → 업비트 KRW 비중·김치프리미엄·한국 개인투자자 포지션을 추론하라.

한국 연결이 전혀 없는 뉴스는 없다. 없다고 판단되면 더 깊이 추론하라.

## 반드시 반환할 항목

summary: 뉴스의 핵심 1~2문장 요약

key_facts: 검증 가능한 팩트 목록 (숫자·날짜·기관명 우선)

interpretation_gaps: 아래 두 가지를 모두 포함하라
  - 블록미디어·코인데스크코리아·연합뉴스가 놓치고 있는 해석 갭
  - 이 뉴스가 한국 시장·기업·투자자·정책에 연결되는 구체적 맥락
    (한국 독자가 "그래서 나한테 왜 중요한가"를 알 수 있도록)

fact_labels: 각 key_fact 에 아래 3가지 중 하나를 라벨링
  - challenges_assumption: 기존 통념을 뒤집는 팩트
  - missing_context: 한국 독자에게 필요한 구조적 배경
  - confirms_common_narrative: 이미 알려진 사실 확인

sources: 출처 URL 또는 기관명 목록

context_for_foreigners: 이 뉴스를 이해하는 데 필요한 한국 시장 구조 설명
  (한국 거래소 구조, 실명계좌 체계, 김치프리미엄 메커니즘, 규제 체계 등)

## 응답 형식

반드시 JSON만 반환한다. 마크다운 펜스 없음. 프로즈 없음.

{
  "summary": "string",
  "key_facts": ["string", ...],
  "sources": ["string", ...],
  "context_for_foreigners": "string",
  "interpretation_gaps": ["string", ...],
  "fact_labels": {
    "fact 내용": "challenges_assumption | missing_context | confirms_common_narrative"
  }
}

## 파급 효과 분석 (필수)

이 뉴스의 파급 효과를 반드시 3단계로 분석해서 interpretation_gaps 에 포함시켜라:

- 1차 파급: 직접적인 시장·가격·거래량 영향 (오늘~이번 주)
- 2차 파급: 관련 산업·기업·경쟁자·정책 변화 (이번 달~이번 분기)
- 3차 파급: 한국 투자자·소비자·규제 환경의 구조적 재편 (6개월~1년)

한국 연결이 없어 보이는 글로벌 뉴스도 반드시 3차까지 추론하라.
"""


class GeminiResearcher(BaseResearcher):
    """Google Gemini를 사용한 리서처."""

    async def research(self, query: str, context: str = "") -> ResearchResult:
        logger.info(f"[Gemini Researcher] 리서치: '{query[:60]}'")

        user_msg = (
            f"Research this Korean topic for an X post.\n\n"
            f"Topic: {query}\n\n"
        )
        if context:
            user_msg += f"Additional context:\n{context[:2000]}\n\n"
        user_msg += "Respond in JSON only."

        try:
            url = GEMINI_API_URL.format(model=GEMINI_MODEL)
            # 시점 인식 prefix — 훈련 데이터 시점(2024 등)으로 답하지 않도록 강제
            from datetime import datetime as _dt
            _today = _dt.now().strftime("%Y년 %m월 %d일")
            _date_prefix = (
                f"[현재 날짜: {_today}]\n"
                f"이 시점에서 이미 지난 사건은 과거형으로 서술하라.\n"
                f"예: '2024년 11월 미국 대선' → 이미 끝난 사건. "
                f"'예정되어 있다' 등 미래 표현 금지.\n\n"
            )
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    headers={"Content-Type": "application/json"},
                    json={
                        "system_instruction": {
                            "parts": [{"text": _date_prefix + SYSTEM_INSTRUCTION}],
                        },
                        "contents": [
                            {
                                "parts": [{"text": user_msg}],
                            },
                        ],
                        "generationConfig": {
                            "temperature": 0.4,
                        },
                    },
                )
                if resp.status_code >= 400:
                    body = resp.text
                    if settings.gemini_api_key:
                        body = body.replace(settings.gemini_api_key, "***")
                    logger.error(f"[Gemini Researcher] API {resp.status_code}: {body[:500]}")
                    raise RuntimeError(f"[Gemini Researcher] API {resp.status_code}")
                resp_data = resp.json()
                usage_meta = resp_data.get("usageMetadata", {})
                logger.info(
                    f"[API-COST] gemini {GEMINI_MODEL} "
                    f"in={usage_meta.get('promptTokenCount', '?')} "
                    f"out={usage_meta.get('candidatesTokenCount', '?')} "
                    f"think={usage_meta.get('thoughtsTokenCount', 0)} "
                    f"caller=Researcher"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("gemini", GEMINI_MODEL, "Researcher",
                                 usage_meta.get("promptTokenCount", 0),
                                 usage_meta.get("candidatesTokenCount", 0))
                except Exception:
                    pass
                raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                # responseMimeType 미사용 시 마크다운 코드블록 제거
                _t = raw_text.strip()
                if _t.startswith("```"):
                    _t = _t.split("\n", 1)[1] if "\n" in _t else _t[3:]
                    if _t.endswith("```"):
                        _t = _t[:-3]
                    _t = _t.strip()
                data = json.loads(_t)

            gaps = data.get("interpretation_gaps", [])
            labels = data.get("fact_labels", {})
            high_value = [f for f, lbl in labels.items() if lbl != "confirms_common_narrative"]

            if gaps:
                logger.info(f"[Gemini Researcher] 해석 갭 {len(gaps)}개 발견: {gaps[0][:80]}")
            if high_value:
                logger.info(f"[Gemini Researcher] 고가치 팩트 {len(high_value)}개 (challenges/missing)")
            logger.info("[Gemini Researcher] 리서치 성공")

            # CriteriaSignals 구성 — expertise(해석 갭) + context_gap(고가치 팩트)
            criteria_signals = CriteriaSignals(
                expertise={
                    "score": None,
                    "note": f"해석 갭 {len(gaps)}개 발견",
                } if gaps else {},
                context_gap={
                    "score": None,
                    "note": (
                        f"고가치 팩트 {len(high_value)}개 "
                        f"(challenges_assumption/missing_context)"
                    ),
                } if high_value else {},
            )
            if criteria_signals.any_populated():
                logger.info(f"[Gemini] criteria_signals: {criteria_signals.to_log_str()}")

            return ResearchResult(
                summary=data.get("summary", ""),
                key_facts=data.get("key_facts", []),
                sources=data.get("sources", []),
                raw_response=raw_text,
                interpretation_gaps=gaps,
                fact_labels=labels,
                criteria_signals=criteria_signals,
            )

        except Exception as e:
            safe_msg = str(e)
            if settings.gemini_api_key:
                safe_msg = safe_msg.replace(settings.gemini_api_key, "***")
            logger.error(f"Gemini Researcher 오류: {safe_msg}")
            raise RuntimeError(f"Gemini Researcher 오류: {safe_msg}") from e
