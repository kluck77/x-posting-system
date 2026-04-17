"""
xAI Grok 프로바이더
====================
역할: TrendHunter — 실시간 트렌드 탐지.
X/Twitter에서 한국 관련 트렌딩 토픽을 탐지하고 분석합니다.

Grok API는 OpenAI 호환 형식을 사용합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseTrendHunter, TrendResult, CriteriaSignals

logger = logging.getLogger(__name__)

GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODEL = "grok-3-mini-fast"

SYSTEM_PROMPT = """당신은 X 계정 @cheesesvav의 트렌드 헌터입니다. 한국 커뮤니티 시각을 글로벌 독자에게 전달하는 계정입니다.

임무: 한국 온라인 커뮤니티와 X/Twitter에서 지금 화제인 토픽을 찾아라. 해외 독자가 관심 가질 만한 한국 트렌드를 발굴하라.

탐색 영역:
- 한국 경제 뉴스 중 화제가 된 것
- 한국 온라인 커뮤니티 핫 토픽 (디시인사이드, 에펨코리아, 코인 게시판)
- 한국 정부 정책에 대한 반응
- K-pop, 문화 현상 중 글로벌 함의가 있는 것
- 한국 코인/시장 심리 변화
- 사회 트렌드 (고용, 주거, 인구)

══════════════════════════════════════════
5기준 품질 필터 — 트렌드 포함 전 반드시 적용
══════════════════════════════════════════

시장성 체크 (기준 2): 글로벌 시장, 공급망, 코인, 지정학과 연결되는가?
- 통과 (7-10점): 원달러, 반도체, 코인, 글로벌 무역, 국제 지정학과 연결
- 미약 (4-6점): 지역적 관련성은 있지만 글로벌 신호 약함
- 탈락 (1-3점): 순수 국내 이슈, 국제적 함의 없음 → 제외

팔로워 품질 체크 (기준 4): 정보력 있는 글로벌 마인드 팔로워를 끌어오는가?
- 통과 (7-10점): 투자자, 애널리스트, 연구원, 정책 관찰자, 트레이더 유입
- 미약 (4-6점): 혼합 독자층
- 탈락 (1-3점): 연예/가십 → 제외

규칙: marketability_score >= 6 AND follower_fit_score >= 6 모두 통과한 트렌드만 포함.
어느 하나라도 미달이면 출력에서 제외.

각 트렌드 평가 항목:
- 얼마나 많은 반응을 얻고 있는지
- 해외 독자에게 관련성이 있는지
- 감성 (긍정/부정/혼합)
- 시급성 (속보/화제/지속)

엄격 규칙:
- 글로벌 관련성 또는 의외성이 있는 토픽에 집중
- 국제적 함의 없는 순수 국내 가십은 건너뛸 것
- 한국 시각이 서방 보도와 다른 토픽을 우선
- 가능하면 구체적 숫자 (반응 수, 퍼센트) 포함

**모든 출력은 반드시 한국어로 작성하라.**

JSON만 응답:
{
  "trending_topics": [
    {
      "topic": "짧은 토픽 제목 (한국어)",
      "description": "1-2문장 설명 (한국어)",
      "sentiment": "positive|negative|mixed|neutral",
      "urgency": "breaking|trending|ongoing",
      "relevance_score": 1-10,
      "marketability_score": 1-10,
      "follower_fit_score": 1-10,
      "criteria_note": "이 트렌드가 품질 필터를 통과한 이유 (한국어)"
    }
  ],
  "relevance_notes": "전체 평가 — 몇 개 트렌드가 필터를 통과했고 그 이유 (한국어)"
}"""


class GrokTrendHunter(BaseTrendHunter):
    """xAI Grok을 사용한 트렌드 탐지기."""

    async def find_trends(self, topic_area: str = "korea") -> TrendResult:
        logger.info(f"[Grok TrendHunter] 트렌드 탐색: '{topic_area}'")

        user_msg = (
            f"한국 온라인 커뮤니티와 X/Twitter에서 현재 화제인 트렌드를 찾아라.\n"
            f"주제 영역: {topic_area}\n\n"
            f"해외 독자가 놀라거나 관심 가질 만한 토픽에 집중.\n"
            f"모든 출력은 한국어로. JSON만 응답."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    GROK_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROK_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.5,
                    },
                )
                resp.raise_for_status()
                resp_data = resp.json()
                usage = resp_data.get("usage", {})
                logger.info(
                    f"[API-COST] grok {GROK_MODEL} "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=TrendHunter"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("grok", GROK_MODEL, "TrendHunter",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
                raw_text = resp_data["choices"][0]["message"]["content"]

                # Grok may return markdown-wrapped JSON, strip it
                text = raw_text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                data = json.loads(text)

            topics_raw = data.get("trending_topics", [])
            # Normalize: could be list of strings or list of dicts
            topics: list[str] = []
            mkt_scores: list[float] = []
            fit_scores: list[float] = []
            filter_summary: list[str] = []

            for t in topics_raw:
                if isinstance(t, str):
                    topics.append(t)
                elif isinstance(t, dict):
                    topic_name = t.get("topic", str(t))
                    topics.append(topic_name)

                    mkt = t.get("marketability_score")
                    fit = t.get("follower_fit_score")
                    note = t.get("criteria_note", "")

                    if isinstance(mkt, (int, float)):
                        mkt_scores.append(float(mkt))
                    if isinstance(fit, (int, float)):
                        fit_scores.append(float(fit))

                    filter_summary.append(
                        f"{topic_name} [mkt={mkt or '?'} fit={fit or '?'}]"
                    )
                    if note:
                        logger.debug(f"  └ {note}")

            if filter_summary:
                logger.info(f"[Grok] 5-criteria 통과 트렌드: {'; '.join(filter_summary)}")
            logger.info(f"[Grok TrendHunter] {len(topics)}개 트렌드 발견")

            # CriteriaSignals 구성 — 통과한 트렌드 점수 집계
            avg_mkt = round(sum(mkt_scores) / len(mkt_scores), 1) if mkt_scores else None
            avg_fit = round(sum(fit_scores) / len(fit_scores), 1) if fit_scores else None
            criteria_signals = CriteriaSignals(
                marketability={
                    "score": avg_mkt,
                    "note": f"{len(topics)}개 트렌드 평균 (≥6 필터 통과분)",
                } if avg_mkt is not None else {},
                follower_quality={
                    "score": avg_fit,
                    "note": f"{len(topics)}개 트렌드 평균 follower_fit",
                } if avg_fit is not None else {},
            )
            if criteria_signals.any_populated():
                logger.info(f"[Grok] criteria_signals: {criteria_signals.to_log_str()}")

            return TrendResult(
                trending_topics=topics,
                relevance_notes=data.get("relevance_notes", ""),
                raw_response=raw_text,
                criteria_signals=criteria_signals,
            )

        except Exception as e:
            logger.error(f"Grok TrendHunter 오류: {e}")
            raise RuntimeError(f"Grok TrendHunter 오류: {e}") from e

    async def quick_review(self, hook: str, body: str, category: str = "") -> dict:
        """전송 직전 X/트렌드 감각 보정. 본문 전체 rewrite 금지."""
        prompt = f"""아래 X(트위터) 초안을 X/트렌드 관점에서 빠르게 점검하라.

초안:
hook: {hook}
body: {body}
카테고리: {category}

JSON으로만 응답:
{{
  "hook_alt": "더 강한 첫 줄 제안 (원본이 충분하면 null)",
  "x_angle": "X/트위터에서 먹힐 각도 1줄 (이미 좋으면 null)",
  "resonance_note": "공명도 보정 제안 1줄 (불필요하면 null)",
  "verdict": "use_default 또는 use_grok_hook"
}}

규칙:
- 본문 전체 rewrite 금지
- hook_alt는 60자 이내
- verdict가 use_default면 원본 유지
- 모든 출력 한국어"""

        try:
            from app.services.api_cost_tracker import record_usage
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    GROK_API_URL,
                    headers={"Authorization": f"Bearer {settings.grok_api_key}",
                             "Content-Type": "application/json"},
                    json={"model": GROK_MODEL, "messages": [
                        {"role": "user", "content": prompt}
                    ], "temperature": 0.4, "max_tokens": 300},
                )
                if resp.status_code != 200:
                    logger.warning(f"[Grok quick_review] API {resp.status_code}")
                    return {"grok_used": False, "reason": f"API {resp.status_code}"}

                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                record_usage("grok", GROK_MODEL, "QuickReview",
                             input_tokens=usage.get("prompt_tokens", 0),
                             output_tokens=usage.get("completion_tokens", 0))

                clean = raw.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

                import json as _json
                result = _json.loads(clean)
                result["grok_used"] = True
                logger.info(f"[Grok quick_review] verdict={result.get('verdict')} hook_alt={result.get('hook_alt','')[:30]}")
                return result

        except Exception as e:
            logger.warning(f"[Grok quick_review] 실패 (fallback): {e}")
            return {"grok_used": False, "reason": str(e)}
