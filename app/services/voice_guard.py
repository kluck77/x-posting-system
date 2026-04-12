"""
보이스 일관성 가드 (Voice Guard)
==================================
AI 어투 패턴을 감지하여 style_warnings로 반환합니다.

설계 원칙:
- 외부 의존성 없음 (순수 regex)
- 예외 발생 없음 — Layer 2 보호
- 각 경고는 operator가 직접 수정할 수 있는 구체적 표현 포함

감지 대상:
- AI가 자주 쓰는 전환어 / 클리셰
- X 포스팅에 어울리지 않는 에세이체
- 금지 단어 목록 (SYSTEM_PROMPT와 동기화)
"""

import re
import logging

logger = logging.getLogger(__name__)

# (regex 패턴, 경고 메시지)
_PATTERNS: list[tuple[str, str]] = [
    # 전환어 클리셰
    (r"\bIn conclusion\b",              "AI 어투: 'In conclusion' — X 포스트에 불필요"),
    (r"\bFurthermore\b",               "AI 어투: 'Furthermore' — 금지 단어"),
    (r"\bMoreover\b",                  "AI 어투: 'Moreover' — 금지 단어"),
    (r"\bNotably\b",                   "AI 어투: 'Notably' — 금지 단어"),
    (r"\bit(?:'s| is) worth noting\b", "AI 어투: 'worth noting' — 금지 표현"),
    (r"\bit(?:'s| is) important to\b", "AI 어투: 'it's important to' — 직접 표현으로 변경"),
    (r"\bit(?:'s| is) imperative\b",   "AI 어투: 'it's imperative' — 너무 격식체"),
    # 여정·탐구 클리셰
    (r"\bdelve into\b",                "AI 어투: 'delve into' — 흔한 AI 클리셰"),
    (r"\bnavigate\b",                  "AI 어투: 'navigate' — 문맥 확인 필요"),
    (r"\bin the realm of\b",           "AI 어투: 'in the realm of' — 과잉 수사"),
    (r"\bfoster(?:ing|s|ed)?\b",       "AI 어투: 'foster' — 추상적 표현"),
    # 미래·전망 클리셰
    (r"\bas we look ahead\b",          "AI 어투: 'as we look ahead' — 불필요한 서문"),
    (r"\bin today'?s? \w+",            "AI 어투: 'In today's X' 도입부 — 더 강한 훅으로 시작"),
    (r"\bmoving forward\b",            "AI 어투: 'moving forward' — 공허한 표현"),
    # 강조 과잉
    (r"\bthis underscores\b",          "AI 어투: 'this underscores' — 직접 주장으로 대체"),
    (r"\bundeniably\b",                "AI 어투: 'undeniably' — 불필요한 강조어"),
    (r"\bpivotal\b",                   "AI 어투: 'pivotal' — 남용되는 표현"),
    (r"\bgame.changer\b",              "AI 어투: 'game-changer' — 남용되는 표현"),
    (r"\bunprecedented\b",             "AI 어투: 'unprecedented' — 구체적 수치로 대체"),
    # X 포스팅 금지 시작어
    (r"^(?:South Korea|Korea'?s)\b",   "금지 시작어: 'South Korea' / 'Korea's'로 시작 — 긴장감으로 시작할 것"),
]

# 컴파일 캐시
_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE | re.MULTILINE), msg)
    for pattern, msg in _PATTERNS
]


def check_voice(text: str) -> list[str]:
    """
    텍스트에서 AI 어투 패턴 감지.

    Args:
        text: 검사할 포스트 텍스트

    Returns:
        경고 문자열 목록. 문제 없으면 빈 리스트.
        예외 발생 시 빈 리스트 반환 (Layer 2 보호).
    """
    if not text or len(text) < 10:
        return []

    try:
        warnings: list[str] = []
        for pattern, msg in _COMPILED:
            if pattern.search(text):
                warnings.append(f"⚠️ {msg}")
        return warnings
    except Exception as e:
        logger.warning(f"[VoiceGuard] 패턴 검사 실패 (무시): {e}")
        return []


def check_pack_voices(posts: list[str]) -> list[str]:
    """
    여러 포스트 텍스트를 한꺼번에 검사. 중복 경고는 제거.

    Args:
        posts: 포스트 텍스트 목록

    Returns:
        deduplicated 경고 목록
    """
    seen: set[str] = set()
    result: list[str] = []
    for post in posts:
        for w in check_voice(post):
            if w not in seen:
                seen.add(w)
                result.append(w)
    return result
