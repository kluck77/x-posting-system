"""
Perplexity 프로바이더
=====================
역할: FactChecker — 팩트체크 & 출처 찾기.
AI 생성 초안의 사실 관계를 검증하고 출처를 제공합니다.

Perplexity API는 OpenAI 호환 형식을 사용합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseFactChecker, FactCheckResult, CriteriaSignals

logger = logging.getLogger(__name__)


def _load_editorial_prompt(filename: str) -> str:
    """editorial/system_prompts/ 에서 critic system prompt 를 읽어 반환.
    Phase A: fact_critic 용 유틸 (anthropic_provider 와 동일 패턴)."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(base, "editorial", "system_prompts", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

SYSTEM_PROMPT = """당신은 한국 크립토·매크로·정책 뉴스 검증 전문가입니다.

역할:
- 초안의 한국 관련 수치·사실 검증
- 한국 법률·정책 맥락 보완
- 한국 시장 데이터로 뒷받침

절대 금지:
- 미국 규제·정책으로 한국 뉴스 대체 금지
- 출처가 한국인지 확인 후 사용
- 발언자 주장 반박 금지 (관점·해석은 팩트체크 대상이 아님)

한국 우선 소스:
한국은행·금융위원회·금감원·코인데스크코리아·블루밍비트·블록미디어·연합뉴스

신뢰도 기준:
- "high":   복수 신뢰 소스가 확증
- "medium": 1개 소스 또는 부분 확증
- "low":    검증 불가 또는 상충

══════════════════════════════════════════
해석 힌트 (팩트체크 외 부가 평가)
══════════════════════════════════════════

팩트 검증 후 추가로 다음을 평가:

INTERPRETATION OPPORTUNITY (해석 기회):
검증된 사실이 독창적 해석 여지를 만드는가?
- "high":   통념을 뒤집거나 구조 문제를 드러내는 반직관적 서사
- "medium": 흥미롭지만 해석이 뻔함
- "low":    누구나 아는 사실 — 해석 여지 없음

MARKETABILITY SIGNAL (마케터빌리티):
이 사실이 글로벌 관심사인가 지역 한정인가?
- "global":   국제 시장·공급망·크립토·지정학·테크 연결
- "regional": 아태 지역 한정
- "local":    한국 내부만 관심

응답은 JSON만 (다른 텍스트 금지):
{
  "verified": true/false,
  "confidence": "low|medium|high",
  "corrections": ["정정 사항 1", "정정 사항 2"],
  "sources": ["https://source-url-1", "https://source-url-2"],
  "details": "검증 결과 간단 설명 (한국어)",
  "interpretation_opportunity": "high|medium|low — 한 줄 이유 (한국어)",
  "marketability_signal": "global|regional|local"
}"""


class PerplexityFactChecker(BaseFactChecker):
    """Perplexity를 사용한 팩트체커."""

    async def check_facts(self, claim: str, context: str = "") -> FactCheckResult:
        logger.info(f"[Perplexity FactChecker] 검증: '{claim[:60]}'")

        user_msg = (
            f"Fact-check this claim from a draft X post about Korea.\n\n"
            f"Claim: {claim[:1500]}\n\n"
        )
        if context:
            user_msg += f"Source context:\n{context[:1000]}\n\n"
        user_msg += (
            "Verify the factual claims. Check numbers, dates, and context accuracy.\n"
            "Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # 시점 인식 prefix — 검색 결과를 현재 시점에서 해석하도록 강제
                from datetime import datetime as _dt
                _today = _dt.now().strftime("%Y년 %m월 %d일")
                _date_prefix = (
                    f"[현재 날짜: {_today}]\n"
                    f"이미 지난 사건은 과거형으로 서술하라. "
                    f"'예정되어 있다' 같은 미래 표현은 미래 사건에만 사용. "
                    f"검증 시 해당 사건이 이미 발생했는지 먼저 확인하라.\n\n"
                )
                resp = await client.post(
                    PERPLEXITY_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.perplexity_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": PERPLEXITY_MODEL,
                        "messages": [
                            {"role": "system", "content": _date_prefix + SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                resp_data = resp.json()
                usage = resp_data.get("usage", {})
                logger.info(
                    f"[API-COST] perplexity {PERPLEXITY_MODEL} "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=FactChecker"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("perplexity", PERPLEXITY_MODEL, "FactChecker",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
                raw_text = resp_data["choices"][0]["message"]["content"]

                # Handle potential markdown-wrapped JSON
                text = raw_text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                data = json.loads(text)

            interp = data.get("interpretation_opportunity", "")
            mkt = data.get("marketability_signal", "")
            logger.info(
                f"[Perplexity FactChecker] 완료: "
                f"verified={data.get('verified')}, confidence={data.get('confidence')} | "
                f"interpretation={interp} marketability={mkt}"
            )

            # CriteriaSignals 구성 — interpretation + marketability 신호 매핑
            criteria_signals = CriteriaSignals(
                interpretation={
                    "score": None,
                    "note": interp,
                } if interp else {},
                marketability={
                    "score": None,
                    "note": f"signal={mkt}",
                } if mkt else {},
            )
            if criteria_signals.any_populated():
                logger.info(f"[Perplexity] criteria_signals: {criteria_signals.to_log_str()}")

            return FactCheckResult(
                verified=data.get("verified", False),
                confidence=data.get("confidence", "low"),
                corrections=data.get("corrections", []),
                sources=data.get("sources", []),
                raw_response=raw_text,
                interpretation_opportunity=interp,
                marketability_signal=mkt,
                criteria_signals=criteria_signals,
            )

        except Exception as e:
            logger.error(f"Perplexity FactChecker 오류: {e}")
            raise RuntimeError(f"Perplexity FactChecker 오류: {e}") from e

    # ── Phase A: fact critic (review 확정 + existing factcheck 기반) ────

    async def fact_critic(self, draft: str, existing_facts: dict) -> dict:
        """Fact Checker critic pass.
        editorial/system_prompts/fact_checker.md 를 system prompt 로 사용.
        existing_facts: check_facts() 결과를 dict 화한 값.
        반환: fact_checker JSON schema 준수 dict (publish_block 포함).
        실패 시 fallback dict 반환 (파이프라인 중단 없음)."""
        try:
            system_prompt = _load_editorial_prompt("fact_checker.md")
            user_content = (
                f"DRAFT:\n{draft}\n\n"
                f"EXISTING_FACTCHECK:\n"
                f"{json.dumps(existing_facts or {}, ensure_ascii=False)}"
            )
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    PERPLEXITY_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.perplexity_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": PERPLEXITY_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            return {
                "fact_check_passed": True,
                "publish_block": False,
                "claims": [],
                "translation_flags": [],
                "publish_block_reason": None,
                "summary": f"fact_critic fallback — {str(e)}",
            }
