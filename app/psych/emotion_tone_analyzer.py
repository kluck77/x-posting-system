"""감정 톤 분석기.

KoELECTRA 로컬 추론 (20-60ms) → confidence < 0.55 시 Haiku fallback.
KoELECTRA 미설치 환경에서는 즉시 Haiku 전용 모드.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)

# KoELECTRA 로컬 추론 시도
_KOELECTRA_AVAILABLE = False
_emotion_pipe = None
try:
    from transformers import pipeline as hf_pipeline  # type: ignore
    _emotion_pipe = hf_pipeline(
        "text-classification",
        model="Jinuuuu/KoELECTRA_fine_tunning_emotion",
        top_k=None,
    )
    _KOELECTRA_AVAILABLE = True
    logger.info("[EmotionAnalyzer] KoELECTRA 로드 성공")
except Exception as _e:
    logger.warning(f"[EmotionAnalyzer] KoELECTRA 로드 실패 (Haiku 전용): {_e}")

# 경외(awe) 감지 키워드
AWE_KEYWORDS = re.compile(
    r"역사적|사상\s*최대|최초|돌파|ATH|신고가|사상\s*최고",
    re.IGNORECASE,
)

KOELECTRA_TO_5CLASS = {
    "공포": "anxiety",
    "놀람": "excitement",
    "분노": "anger",
    "슬픔": "anxiety",
    "행복": "excitement",
    "중립": "neutral",
    "혐오": "anger",
}

HAIKU_SYSTEM = """한국어 텍스트의 감정 톤을 분석해서 JSON만 반환하세요.
5가지 톤 중 하나: anxiety / excitement / anger / neutral / awe

JSON:
{
  "tone": "톤 이름",
  "confidence": 0.0-1.0,
  "reason_ko": "이유 한 줄"
}
JSON만. 다른 텍스트 금지."""


async def analyze(text: str) -> dict:
    """
    반환값: {tone, confidence, source}
    tone: anxiety | excitement | anger | neutral | awe
    """
    if not text:
        return {"tone": "neutral", "confidence": 0.5, "source": "empty"}

    # 1. 경외 키워드 우선 체크
    if AWE_KEYWORDS.search(text):
        return {"tone": "awe", "confidence": 0.90, "source": "keyword"}

    # 2. KoELECTRA 로컬 추론
    if _KOELECTRA_AVAILABLE and _emotion_pipe is not None:
        try:
            results = _emotion_pipe(text[:256])[0]
            top = max(results, key=lambda x: x["score"])
            tone = KOELECTRA_TO_5CLASS.get(top["label"], "neutral")
            confidence = float(top["score"])

            # awe 보정
            if tone == "excitement" and confidence > 0.55 and AWE_KEYWORDS.search(text):
                tone = "awe"

            if confidence >= 0.55:
                return {"tone": tone, "confidence": confidence, "source": "koelectra"}

            logger.debug(
                f"[EmotionAnalyzer] KoELECTRA confidence 낮음 ({confidence:.2f}), "
                "Haiku fallback"
            )
        except Exception as e:
            logger.warning(f"[EmotionAnalyzer] KoELECTRA 추론 실패: {e}")

    # 3. Haiku fallback
    return await _haiku_analyze(text)


async def _haiku_analyze(text: str) -> dict:
    api_key = settings.anthropic_api_key
    if not api_key:
        return {"tone": "neutral", "confidence": 0.5, "source": "default"}

    try:
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 150,
            "system": wrap_anthropic_cache(HAIKU_SYSTEM),
            "messages": [{"role": "user", "content": text[:400]}],
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    "anthropic-beta": "prompt-caching-2024-07-31",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()
            raw = raw.strip("```json").strip("```").strip()
            data = json.loads(raw)
            data["source"] = "haiku"
            data.setdefault("tone", "neutral")
            try:
                data["confidence"] = float(data.get("confidence", 0.5))
            except Exception:
                data["confidence"] = 0.5
            return data
    except Exception as e:
        logger.warning(f"[EmotionAnalyzer] Haiku fallback 실패: {e}")
        return {"tone": "neutral", "confidence": 0.5, "source": "error"}
