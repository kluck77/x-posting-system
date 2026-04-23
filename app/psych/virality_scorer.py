"""바이럴 스코어 0-100.

규칙 기반 70점 + Haiku Likert 30점.
70점 미만 시 is_warning=True (텔레그램 카드에서 경고 배지 표시).
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)

NUMBER_PATTERN = re.compile(r"\d+[\d,\.]*[%조억만달러원]?")
EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAD6\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF☀-➿]"
)
TICKER_PATTERN = re.compile(
    r"\$?(?:BTC|ETH|SOL|XRP|BNB|USDT|DOGE|ADA|MATIC|DOT)\b",
    re.IGNORECASE,
)
CONTRAST_WORDS = ["반면", "하지만", "그러나", "오히려", "아니라", "vs", "대비"]
CURIOSITY_WORDS = ["핵심은", "진짜는", "숨겨진", "아무도", "모르는", "놓친"]
HOOK_STARTERS = re.compile(
    r"^(?:\d|📊|📈|📉|🚨|\$[A-Z]|BTC|ETH|[가-힣]+이\s|나는\s|내가\s)",
)


def _rule_score(text: str) -> dict:
    """규칙 기반 70점 산출."""
    scores: dict[str, int] = {}

    # 1. 감정 강도 (15점)
    anxiety_words = ["경고", "위기", "붕괴", "폭락", "위험", "주의", "긴급"]
    awe_words     = ["역사적", "사상최대", "최초", "돌파", "ATH", "신고가"]
    emotion_hits = sum(1 for w in anxiety_words + awe_words if w in text)
    scores["emotion"] = min(emotion_hits * 5, 15)

    # 2. 숫자 밀도 (10점)
    numbers = NUMBER_PATTERN.findall(text)
    scores["numbers"] = min(len(numbers) * 3, 10)

    # 3. 길이 (10점)
    char_count = len(text.replace("\n", "").replace(" ", ""))
    if 180 <= char_count <= 240:
        scores["length"] = 10
    elif 140 <= char_count < 180 or 240 < char_count <= 280:
        scores["length"] = 7
    else:
        scores["length"] = 3

    # 4. 호기심 갭 단어 (15점)
    curiosity_hits = sum(1 for w in CURIOSITY_WORDS if w in text)
    scores["curiosity"] = min(curiosity_hits * 8, 15)

    # 5. 대비 구조 (10점)
    contrast_hits = sum(1 for w in CONTRAST_WORDS if w in text)
    scores["contrast"] = min(contrast_hits * 5, 10)

    # 6. 티커 (5점)
    tickers = TICKER_PATTERN.findall(text)
    scores["tickers"] = min(len(set(tickers)) * 3, 5)

    # 7. 이모지 (5점) — 0~2개 최적
    emoji_count = len(EMOJI_PATTERN.findall(text))
    if 0 <= emoji_count <= 2:
        scores["emoji"] = 5
    elif emoji_count <= 4:
        scores["emoji"] = 2
    else:
        scores["emoji"] = 0

    # 8. 훅 시작 (없으면 -5점)
    scores["hook"] = 0 if HOOK_STARTERS.match(text.strip()) else -5

    total = sum(scores.values())
    return {"breakdown": scores, "rule_total": max(total, 0)}


HAIKU_VIRALITY_SYSTEM = """당신은 한국어 X(트위터) 포스트의 바이럴 가능성을 평가합니다.
아래 3개 항목을 1-10점으로 평가해서 JSON만 반환하세요.

평가 항목:
1. hook_strength: 첫 문장이 스크롤을 멈추게 하는가
2. share_intent: "이걸 공유하고 싶다"는 생각이 드는가
3. reply_trigger: 답글을 달고 싶게 만드는가

JSON:
{
  "hook_strength": 1-10,
  "share_intent": 1-10,
  "reply_trigger": 1-10,
  "total": 합계,
  "feedback_ko": "개선 한 줄"
}"""


async def score(text: str) -> dict:
    """
    반환값: {total_score, rule_score, haiku_score, breakdown, feedback_ko, is_warning}
    """
    if not text:
        return {
            "total_score": 0, "rule_score": 0, "haiku_score": 0,
            "breakdown": {}, "feedback_ko": "", "is_warning": True,
        }

    # 규칙 기반 70점
    rule_result = _rule_score(text)
    rule_score = rule_result["rule_total"]

    # Haiku 30점
    haiku_score = 0
    feedback = ""
    try:
        api_key = settings.anthropic_api_key
        if api_key:
            payload = {
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "system":     wrap_anthropic_cache(HAIKU_VIRALITY_SYSTEM),
                "messages":   [{"role": "user", "content": text[:400]}],
                "temperature": 0.2,
            }
            async with httpx.AsyncClient(timeout=15) as client:
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
                # 30점 환산: (합계/30) × 30 (clip)
                _tot = int(data.get("total", 15) or 15)
                haiku_score = max(0, min(30, round((_tot / 30) * 30)))
                feedback = str(data.get("feedback_ko", "") or "")
        else:
            haiku_score = 15  # 기본값
    except Exception as e:
        logger.warning(f"[ViralityScorer] Haiku 실패: {e}")
        haiku_score = 15

    total = min(rule_score + haiku_score, 100)
    is_warning = total < 70

    logger.info(
        f"[ViralityScorer] total={total}/100 "
        f"rule={rule_score} haiku={haiku_score} warning={is_warning}"
    )

    return {
        "total_score":   total,
        "rule_score":    rule_score,
        "haiku_score":   haiku_score,
        "breakdown":     rule_result["breakdown"],
        "feedback_ko":   feedback,
        "is_warning":    is_warning,
    }
