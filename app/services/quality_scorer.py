"""
초안 퀄리티 스코어러
====================
AI가 생성한 초안을 자동으로 채점하고, 기준 미달 시 재생성을 요청합니다.

채점 기준 (총 100점):
  +20  훅에 숫자/퍼센트/배수가 있음
  +20  첫 줄이 "South Korea" / "Korea's" 로 시작하지 않음
  +15  CTA 포함 (Follow / Bookmark / Thread 등)
  +15  본문 270자 이하
  +10  "you" 직접 호칭 포함
  +10  구체적 국가/기관/인물명 포함 (맥락 구체성)
  +10  커뮤니티 입력 시 감정/반응 표현 포함
  -15  금지어 포함 (however, furthermore, it is worth noting 등)
  -10  본문 270자 초과할 때마다

임계값: 60점 미만 → 자동 재생성 (최대 2회)
"""

import re
import logging
from app.providers.base import DraftResult

logger = logging.getLogger(__name__)

# 금지어 (패턴)
_BANNED = [
    r"\bhowever\b",
    r"\bfurthermore\b",
    r"\bmoreover\b",
    r"\bit is worth noting\b",
    r"\bit should be noted\b",
    r"\bin conclusion\b",
    r"\bto summarize\b",
    r"\bnotably\b",
]

# CTA 패턴
_CTA_PATTERNS = [
    r"\bfollow\b",
    r"\bbookmark\b",
    r"\bthread\b",
    r"\bkeep.{0,10}(watch|track|eye)",
]

# 숫자/지표 패턴
_NUMBER_PATTERN = re.compile(
    r"(\d+[.,]?\d*\s*(%|억|조|만|원|달러|won|usd|btc|x|\+|-|bp|bps|'s))|"
    r"(\$[\d,]+)|"
    r"(\d+\.\d+)|"
    r"(#\d+)",
    re.IGNORECASE,
)

# 감정/반응 표현 (커뮤니티 입력용)
_SENTIMENT_PATTERN = re.compile(
    r"\b(panic|fear|angry|concern|worry|bullish|bearish|react|surge|crash|dump|pump|"
    r"panicck|skeptic|optimis|pessimis)\w*\b",
    re.IGNORECASE,
)

REGEN_THRESHOLD = 60  # 이 점수 미만이면 재생성 요청


def score_draft(draft: DraftResult, source_type: str = "manual") -> tuple[int, list[str]]:
    """
    초안을 채점하고 (점수, 이유 목록)을 반환합니다.

    Args:
        draft: 채점할 초안
        source_type: "manual" 또는 "community_input"

    Returns:
        (score: int, reasons: list[str])
    """
    score = 0
    reasons: list[str] = []
    full = f"{draft.hook}\n{draft.body}"
    hook_lower = draft.hook.lower()
    body_lower = draft.body.lower()
    full_lower  = full.lower()

    # +20 훅에 숫자 포함
    if _NUMBER_PATTERN.search(draft.hook):
        score += 20
        reasons.append("+20 훅에 숫자/지표 있음")
    else:
        reasons.append(" 0 훅에 숫자 없음 (필수)")

    # +20 금지 시작어 없음
    bad_starts = ("south korea", "korea's", "in south korea", "south korea's")
    if not any(hook_lower.startswith(s) for s in bad_starts):
        score += 20
        reasons.append("+20 훅 시작어 OK")
    else:
        reasons.append("-0 훅이 'South Korea'/'Korea's'로 시작 (감점 없으나 약점)")

    # +15 CTA 포함
    if any(re.search(p, full_lower) for p in _CTA_PATTERNS):
        score += 15
        reasons.append("+15 CTA 포함")
    else:
        reasons.append(" 0 CTA 없음")

    # +15 본문 270자 이하
    body_len = len(draft.body)
    if body_len <= 270:
        score += 15
        reasons.append(f"+15 본문 {body_len}자 (270 이하)")
    else:
        penalty = min(30, ((body_len - 270) // 30) * 10)
        score -= penalty
        reasons.append(f"-{penalty} 본문 {body_len}자 초과")

    # +10 "you" 직접 호칭
    if re.search(r"\byou\b|\byour\b", full_lower):
        score += 10
        reasons.append("+10 'you' 직접 호칭")
    else:
        reasons.append(" 0 'you' 없음")

    # +10 구체적 맥락 (기관명/지명/통화/수치)
    context_pattern = re.compile(
        r"\b(korea|korean|seoul|won|krw|bok|samsung|hyundai|sk|lg|kospi|"
        r"bitcoin|ethereum|btc|eth|binance|upbit|bithumb)\b",
        re.IGNORECASE,
    )
    if context_pattern.search(full):
        score += 10
        reasons.append("+10 구체적 맥락(기관/통화) 포함")
    else:
        reasons.append(" 0 구체적 맥락 없음")

    # +10 커뮤니티 입력 시 감정 표현
    if source_type == "community_input":
        if _SENTIMENT_PATTERN.search(full):
            score += 10
            reasons.append("+10 커뮤 감정/반응 표현 포함")
        else:
            reasons.append(" 0 커뮤 감정 표현 없음")
    else:
        score += 10  # 일반 입력은 이 항목 면제
        reasons.append("+10 일반 입력 (감정 표현 항목 면제)")

    # -15 금지어
    for pattern in _BANNED:
        if re.search(pattern, full_lower):
            score -= 15
            reasons.append(f"-15 금지어: '{pattern}'")

    score = max(0, min(100, score))
    return score, reasons


def should_regenerate(score: int) -> bool:
    """점수가 임계값 미만이면 재생성 필요."""
    return score < REGEN_THRESHOLD


def format_score_report(score: int, reasons: list[str]) -> str:
    """점수 리포트 텍스트 반환 (로그/Telegram용)."""
    grade = "✅ 통과" if score >= REGEN_THRESHOLD else "⚠️ 재생성 필요"
    lines = [f"📊 품질 점수: {score}/100 {grade}"] + reasons
    return "\n".join(lines)
