"""타래 자동 분해기.

복잡도 점수 C≥2.0 이면 5~7 트윗 타래로 분해.
감정 아크: hook_anxiety → context → data → counter → resolution → cta.

kiwipiepy 미설치 환경에선 개체 수 fallback 으로 동작.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)

CAUSAL_PATTERNS = re.compile(
    r"때문에|따라서|그러므로|결과로|영향으로|여파로|인해|으로써"
)
NUMBER_PATTERN = re.compile(r"\d+[\d,\.]*")

try:
    from kiwipiepy import Kiwi  # type: ignore
    _KIWI = Kiwi(model_type="cong")
    _KIWI_OK = True
except Exception:
    _KIWI = None
    _KIWI_OK = False


@dataclass
class ComplexityScore:
    total:        float
    token_score:  float
    entity_score: float
    causal_score: float
    is_thread:    bool


def compute_complexity(text: str) -> ComplexityScore:
    """복잡도 점수 계산. 총점 ≥ 2.0 → 타래 추천."""
    if not text:
        return ComplexityScore(0.0, 0.0, 0.0, 0.0, False)

    # 1. 토큰 밀도 (100자당 0.4점)
    token_count = len(text.replace(" ", ""))
    token_score = (token_count / 100.0) * 0.4

    # 2. 개체 수 (5개당 0.35점) — kiwipiepy 있으면 NNP/SL, 없으면 숫자 fallback
    if _KIWI_OK:
        try:
            tokens = _KIWI.tokenize(text)
            entities = [t for t in tokens if t.tag in ("NNP", "SL")]
            entity_score = (len(entities) / 5.0) * 0.35
        except Exception:
            entity_score = 0.35
    else:
        entity_score = (len(NUMBER_PATTERN.findall(text)) / 5.0) * 0.35

    # 3. 인과 연결 수 (3개당 0.25점)
    causal_count = len(CAUSAL_PATTERNS.findall(text))
    causal_score = (causal_count / 3.0) * 0.25

    total = token_score + entity_score + causal_score
    return ComplexityScore(
        total=total,
        token_score=token_score,
        entity_score=entity_score,
        causal_score=causal_score,
        is_thread=(total >= 2.0),
    )


THREAD_SYSTEM = """당신은 한국어 X 포스트를 5~7개 트윗 타래로 분해하는 편집자입니다.

감정 아크 구조 (순서 고정):
1. hook_anxiety: 불안·긴장 유발 훅 (숫자+충격 사실)
2. context_a: 배경 맥락 A
3. context_b: 배경 맥락 B (또는 data_a)
4. data: 핵심 데이터+해석
5. counter: 반론 + 내 답변
6. resolution: 결론 + 예측 3종세트
7. cta (선택): 프로필 고정 유도

규칙:
- 각 트윗 ≤270자
- 이모지 ≤1개/트윗
- 외부 링크 금지 (프로필 고정만)
- 1번 트윗은 단독으로도 완결
- 마지막 트윗 = 예측 3종세트 (시간+레벨+반증조건)

JSON만 반환:
{
  "tweets": [
    {"index": 1, "content": "...", "arc_role": "hook_anxiety"},
    {"index": 2, "content": "...", "arc_role": "context_a"}
  ],
  "total_count": 숫자
}"""


async def decompose(post_text: str) -> dict:
    """
    반환값: {is_thread, tweets, complexity_score}
    - complexity < 2.0 → is_thread=False, tweets=[]
    - API 키 없거나 호출 실패 시 is_thread 유지, tweets=[]
    """
    if not post_text:
        return {"is_thread": False, "tweets": [], "complexity_score": 0.0}

    complexity = compute_complexity(post_text)
    if not complexity.is_thread:
        return {
            "is_thread":        False,
            "tweets":           [],
            "complexity_score": complexity.total,
        }

    api_key = settings.anthropic_api_key
    if not api_key:
        return {
            "is_thread":        True,
            "tweets":           [],
            "complexity_score": complexity.total,
        }

    try:
        payload = {
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 2000,
            "system":     wrap_anthropic_cache(THREAD_SYSTEM),
            "messages": [{
                "role": "user",
                "content": f"아래 포스트를 타래로 분해하세요:\n\n{post_text}",
            }],
            "temperature": 0.4,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":        api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":     "application/json",
                    "anthropic-beta":   "prompt-caching-2024-07-31",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()
            raw = raw.strip("```json").strip("```").strip()
            data = json.loads(raw)
            logger.info(
                f"[ThreadArc] 타래 분해 완료 tweets={data.get('total_count')} "
                f"complexity={complexity.total:.2f}"
            )
            return {
                "is_thread":        True,
                "tweets":           data.get("tweets", []) or [],
                "complexity_score": complexity.total,
            }
    except Exception as e:
        logger.warning(f"[ThreadArc] 실패: {e}")
        return {
            "is_thread":        True,
            "tweets":           [],
            "complexity_score": complexity.total,
        }
