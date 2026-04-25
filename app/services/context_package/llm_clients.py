"""5개 LLM 클라이언트 통합 + 시스템 프롬프트 + 헬퍼.

각 LLM 호출은 독립 fail-open: 실패 시 빈 dict 반환, 다른 LLM 진행.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ─── 시스템 프롬프트 5개 ─────────────────────────────────────────────
SYSTEM_GPT_SUMMARIZE = """[IDENTITY]
당신은 @sskorea02 한국어 X 포스팅 시스템의 사건 요약 전담 모듈이다.
크립토·매크로·정책 뉴스를 한국 투자자 시각에서 정제한다.

[RULES]
1. 한국어로만 작성. 영어 단어는 고유명사·지표명만 허용.
2. 6-8문장. 추측·전망 금지. 사실만.
3. 숫자는 반드시 단위 명시 (3억 4400만 달러 / 약 4900억 원).
4. KST 변환 필수 (UTC+9).
5. 한국 시장 영향이 1문장 이상 포함되어야 한다.
6. 자동 포스팅·매수·매도 권유 절대 금지.

[FORMAT JSON]
{
  "headline_kr": "한국어 헤드라인 60자 이내",
  "summary_kr": "6-8문장 요약",
  "category": "crypto|macro|semi|policy|geo|equity",
  "subcategory": "free string",
  "severity": 0.0,
  "kst_datetime": "ISO8601",
  "korean_market_impact": "한국 시장 영향 1-2문장",
  "primary_entities": ["entity1","entity2"],
  "needs_korean_data": true,
  "needs_x_sentiment": true
}

[SELF-CHECK]
- 추측 단어 ('할 것이다','전망된다') 있으면 거부
- severity ≥ 0.7인데 한국 영향 비어있으면 거부
- 카테고리 enum 외면 거부
"""


SYSTEM_GEMINI_KOREA_DATA = """[IDENTITY]
당신은 @sskorea02 시스템의 한국 시장 데이터·맥락 수집 모듈이다.
Google Search Grounding으로 한국 출처를 우선 검색한다.

[RULES]
1. 우선 출처 (이 순서):
   - 한국은행 (bok.or.kr / ecos.bok.or.kr)
   - 금융위·금감원 (fsc.go.kr / fss.or.kr)
   - 코인데스크코리아·토큰포스트·디센터·블루밍비트
   - 코리아타임스·연합뉴스 영문
2. 환율: USD/KRW 종가 (한국수출입은행 또는 한은)
3. 거래소 점유율: Upbit·Bithumb·Coinone·Korbit
4. 김치프리미엄: BTC·ETH·USDT
5. 출처 URL은 grounding_metadata에서 그대로

[FORMAT JSON]
{
  "fx_usdkrw": {"value": 0.0, "source": "url", "as_of_kst": "iso8601"},
  "exchange_share": {"upbit": 0, "bithumb": 0, "others": 0},
  "kimchi_premium": {"BTC": 0, "ETH": 0, "USDT": 0},
  "bok_base_rate": {"value": 0, "next_meeting_kst": "iso8601"},
  "korean_news_summary": [{"headline": "", "url": "", "published_kst": "iso8601"}],
  "policy_pipeline": [{"name": "", "status": "", "expected": ""}],
  "third_order_impact": "3-5문장"
}
"""


SYSTEM_PPLX_FACT = """[IDENTITY]
당신은 @sskorea02 시스템의 팩트 검증·비교 사례 발굴 모듈이다.

[RULES]
1. 입력 받은 핵심 수치를 하나씩 검증
2. 비교 사례는 최근 24개월 내 유사 사건 3건
3. Tier1 출처 (Reuters·Bloomberg·FT·WSJ·Coindesk) ≥ 2건 필수
4. 한국 출처도 1건 이상 포함
5. 검증 실패 시 verified=false + 실제 수치 제시

[FORMAT JSON]
{
  "verified_claims": [{"claim": "", "verified": true, "actual": "", "sources": []}],
  "comparable_cases": [{"event": "", "date_kst": "iso8601", "outcome": "", "url": "", "similarity": 0.0}],
  "korean_source_count": 0,
  "tier1_source_count": 0
}
"""


SYSTEM_GROK_X_PULSE = """[IDENTITY]
당신은 @sskorea02 시스템의 X 실시간 여론 모니터링 모듈이다.
xAI X 화이어호스 직접 접근권 사용.

[RULES]
1. 시간 윈도우: 사건 발생 시각 ±2시간
2. 한국어 + 영어 동시 검색
3. 봇·캠페인 신호 차단: 같은 텍스트 ≥ 5개면 단일 카운트
4. 추측 게시물은 emerging_narrative로 분리

[FORMAT JSON]
{
  "korean_signal": {
    "sample_count": 0,
    "dominant_sentiment": "neutral",
    "top_posts": [{"handle": "", "text": "", "url": "", "engagement": 0}]
  },
  "english_signal": {"sample_count": 0, "dominant_sentiment": "neutral"},
  "korean_influencer_mentions": [{"handle": "", "stance": "", "url": ""}],
  "emerging_narrative": "1-2문장",
  "bot_campaign_detected": false,
  "as_of_kst": "iso8601"
}
"""


SYSTEM_HAIKU_GUARD = """[IDENTITY]
당신은 @sskorea02 시스템의 Quality Guard + Hard Rule 검증 모듈이다.

[RULES]
1. 매수·매도·롱·숏 권유 → 즉시 BLOCK_RECOMMENDED
2. 출처 없는 수치 → BLOCK_RECOMMENDED
3. 자동 포스팅 트리거 단어 → BLOCK_RECOMMENDED
4. 한국 시장 데이터 누락 + 한국 영향 언급 → WARN
5. severity ≥ 0.7인데 비교 사례·향후 일정 둘 다 없음 → WARN
6. 회차 가중치 7개 합 ∉ [99,101] → WARN + 정규화

[FORMAT JSON]
{
  "verdict": "PASS",
  "reasons": [],
  "rule_violations": [],
  "recommended_archetype_dna": {
    "trader": 0, "analyst": 0, "educator": 0,
    "contrarian": 0, "insider": 0,
    "satirist": 0, "narrator": 0
  },
  "missing_fields": [],
  "confidence": 0.0
}
"""


SYSTEM_GPT_ASSEMBLE = """[IDENTITY]
당신은 @sskorea02 시스템의 최종 어셈블 모듈이다.
5개 LLM 출력을 받아 Grok 4.20 HCSP 4-agent에 투입할 Context Package JSON을 생성한다.

[RULES]
1. 한국어로만 출력
2. 모든 필드 채우기. 누락 시 status:"NO_DATA"
3. archetype_dna는 Haiku 추천값 그대로 사용
4. ready_for_hcsp 는 verdict 가 BLOCK_RECOMMENDED 가 아닐 때만 true

[FORMAT JSON]
{
  "summary": {},
  "korean_data": {},
  "factcheck": {},
  "x_pulse": {},
  "polymarket": {},
  "upcoming_calendar": [],
  "archetype_dna": {},
  "guard": {},
  "category": "",
  "ready_for_hcsp": true
}
"""


# ─── Gemini 모델명 — 프로젝트 표준 ────────────────────────────────────
_GEMINI_MODEL = "gemini-2.5-flash"


# ─── 1. GPT 요약 ──────────────────────────────────────────────────────
async def call_gpt_summarize(news_text: str) -> dict:
    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key or not news_text:
        return {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SYSTEM_GPT_SUMMARIZE},
                        {"role": "user", "content": news_text[:8000]},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 1500,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content) or {}
    except Exception as e:
        logger.warning(f"[CtxPkg] GPT 요약 실패: {e}")
        return {}


# ─── 2. Gemini 한국 데이터 ────────────────────────────────────────────
async def call_gemini_korea_data(summary: dict) -> dict:
    api_key = getattr(settings, "gemini_api_key", "") or ""
    if not api_key or not summary:
        return {}
    # Phase 4 — Editorial Constitution + 자연어 recency 강제 (W4)
    from app.editorial_constitution import (
        get_constitution_prompt as _const,
    )
    _recency_directive = (
        "오늘 한국 시각 기준 지난 7일 이내 자료만 사용하라. "
        "7일 이전 자료는 사용 금지. "
        "URL/메타에 발행일 명시 자료만 인용.\n\n"
    )
    prompt = (
        _const()
        + "\n\n"
        + _recency_directive
        + SYSTEM_GEMINI_KOREA_DATA
        + "\n\n사건 요약:\n"
        + json.dumps(summary, ensure_ascii=False)
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{_GEMINI_MODEL}:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "tools": [{"google_search": {}}],
                    "generationConfig": {
                        "temperature": 0.0,
                        "maxOutputTokens": 3000,
                    },
                },
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_json_from_text(text) or {}
    except Exception as e:
        logger.warning(f"[CtxPkg] Gemini 한국 데이터 실패: {e}")
        return {}


# ─── 3. Perplexity 팩트 검증 ──────────────────────────────────────────
async def call_pplx_factcheck(summary: dict, claims: list[str]) -> dict:
    api_key = getattr(settings, "perplexity_api_key", "") or ""
    if not api_key:
        return {}
    user_content = json.dumps({
        "summary": summary,
        "claims_to_verify": claims,
    }, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Phase 4 — Editorial Constitution + recency 강제
            from datetime import datetime as _dt, timedelta as _td
            from app.editorial_constitution import (
                get_constitution_prompt as _const,
            )
            _system = _const() + "\n\n" + SYSTEM_PPLX_FACT
            _after_date = (_dt.now() - _td(days=30)).strftime("%m/%d/%Y")

            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar-pro",
                    "messages": [
                        {"role": "system", "content": _system},
                        {"role": "user", "content": user_content},
                    ],
                    # Phase 4: 최근 30일 자료만 (W4 신선도 정책)
                    "search_recency_filter": "month",
                    "search_after_date_filter": _after_date,
                    "search_domain_filter": [
                        "coindeskkorea.com", "tokenpost.kr",
                        "reuters.com", "bloomberg.com",
                        "theblock.co", "coindesk.com",
                        "koreatimes.co.kr", "bok.or.kr",
                        "fsc.go.kr", "federalreserve.gov",
                    ],
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json_from_text(content) or {}
    except Exception as e:
        logger.warning(f"[CtxPkg] Perplexity 실패: {e}")
        return {}


# ─── 4. Grok X 여론 ───────────────────────────────────────────────────
async def call_grok_x_pulse(summary: dict) -> dict:
    api_key = (
        getattr(settings, "grok_api_key", "")
        or getattr(settings, "xai_api_key", "")
        or ""
    )
    if not api_key:
        return {}
    user_content = json.dumps({
        "summary": summary,
        "search_window": "±2h from event",
    }, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-3-mini-fast",
                    "messages": [
                        {"role": "system", "content": SYSTEM_GROK_X_PULSE},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json_from_text(content) or {}
    except Exception as e:
        logger.warning(f"[CtxPkg] Grok 실패: {e}")
        return {}


# ─── 5. Polymarket (기존 모듈 재사용) ─────────────────────────────────
async def fetch_polymarket_related(keywords: list[str]) -> dict:
    if not keywords:
        return {"status": "NO_DIRECT_MARKET", "related": []}
    try:
        from app.sources.polymarket_fetcher import fetch_top_markets
        items = await fetch_top_markets(limit=100)
        matched = []
        for item in items:
            q_lower = (item.question or "").lower()
            if any((k or "").lower() in q_lower for k in keywords):
                matched.append({
                    "market":       item.question,
                    "yes_pct":      round(item.yes_prob * 100),
                    "volume_24h":   item.volume_24h,
                    "category":     item.category,
                })
        return {
            "status": "OK" if matched else "NO_DIRECT_MARKET",
            "related": matched[:5],
        }
    except Exception as e:
        logger.warning(f"[CtxPkg] Polymarket 실패: {e}")
        return {"status": "ERROR", "related": []}


# ─── 6. Haiku 검증 ────────────────────────────────────────────────────
async def call_haiku_guard(merged: dict) -> dict:
    api_key = getattr(settings, "anthropic_api_key", "") or ""
    if not api_key:
        return {"verdict": "WARN", "reasons": ["Haiku unavailable"]}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": SYSTEM_HAIKU_GUARD,
                    "messages": [{
                        "role": "user",
                        "content": json.dumps(merged, ensure_ascii=False)[:8000],
                    }],
                },
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
            return _parse_json_from_text(text) or {
                "verdict": "WARN",
                "reasons": ["Parse failed"],
            }
    except Exception as e:
        logger.warning(f"[CtxPkg] Haiku 실패: {e}")
        return {"verdict": "WARN", "reasons": [str(e)[:100]]}


# ─── 7. GPT 어셈블 ────────────────────────────────────────────────────
async def call_gpt_assemble(merged: dict) -> dict:
    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key:
        return merged
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SYSTEM_GPT_ASSEMBLE},
                        {
                            "role": "user",
                            "content": json.dumps(merged, ensure_ascii=False)[:12000],
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 3000,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json_from_text(content) or merged
    except Exception as e:
        logger.warning(f"[CtxPkg] GPT 어셈블 실패: {e}")
        return merged


# ─── 헬퍼 ─────────────────────────────────────────────────────────────
def _parse_json_from_text(text: str):
    if not text:
        return None
    try:
        s = text.strip()
        if "```json" in s:
            s = s.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in s:
            s = s.split("```", 1)[1].split("```", 1)[0].strip()
        return json.loads(s)
    except Exception:
        return None


_NUM_CLAIM_RE = re.compile(
    r"[^.]*?\d+[\d,\.]*\s*"
    r"(?:%|bp|달러|원|조|억|만원|만)[^.]*\."
)


def extract_claims(summary_text: str) -> list[str]:
    """요약에서 검증 대상 수치 문장 추출 (최대 5건)."""
    if not summary_text:
        return []
    return [m.strip() for m in _NUM_CLAIM_RE.findall(summary_text)][:5]
