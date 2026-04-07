"""
어드바이저리 레이블 (Advisory Labels)
=======================================
소스/초안 우선순위를 단순 레이블로 표현합니다.
Layer 2 전용 — 어떤 흐름도 차단하지 않습니다.

레이블 기준 (0~100 점수 기반):
  🔴 우선 (High)   : score >= 60
  🟡 보통 (Medium) : 40 <= score < 60
  ⚪ 보류 (Hold)   : score < 40

순수 함수 모듈 — AI 호출 없음, DB 없음, 예외 발생 없음.
"""

import logging

logger = logging.getLogger(__name__)


def priority_label(score: int) -> str:
    """
    0~100 점수 → 우선/보통/보류 레이블.

    Args:
        score: 0~100 정수

    Returns:
        '🔴 우선' | '🟡 보통' | '⚪ 보류'
    """
    if score >= 60:
        return "🔴 우선"
    elif score >= 40:
        return "🟡 보통"
    else:
        return "⚪ 보류"


_IMPORTANCE_MAX = 43  # morning_digest._importance_score() 이론적 최대값


def source_advisory(article: dict) -> str:
    """
    뉴스 기사 dict → 우선순위 레이블.

    morning_digest._importance_score()를 재사용.
    점수를 0~100으로 정규화한 뒤 priority_label()에 전달.
    실패 시 빈 문자열.

    Args:
        article: {'title': str, 'summary': str, 'region': str, 'category': str}

    Returns:
        '🔴 우선' | '🟡 보통' | '⚪ 보류' | ''
    """
    try:
        from app.services.morning_digest import _importance_score
        raw = _importance_score(article)
        normalized = min(int(raw * 100 / _IMPORTANCE_MAX), 100) if raw > 0 else 0
        return priority_label(normalized)
    except Exception as e:
        logger.debug(f"[Advisory] source_advisory 실패 (무시): {e}")
        return ""


def draft_advisory(hook: str, body: str, source_type: str = "news_link") -> str:
    """
    초안 텍스트 → 우선순위 레이블.

    quality_scorer.score_draft()를 재사용.
    실패 시 빈 문자열.

    Args:
        hook: 초안 훅 텍스트
        body: 초안 본문 텍스트
        source_type: 소스 유형 (기본값: 'news_link')

    Returns:
        '🔴 우선' | '🟡 보통' | '⚪ 보류' | ''
    """
    try:
        import types
        from app.services.quality_scorer import score_draft
        mock = types.SimpleNamespace(hook=hook, body=body)
        score, _ = score_draft(mock, source_type)
        return priority_label(score)
    except Exception as e:
        logger.debug(f"[Advisory] draft_advisory 실패 (무시): {e}")
        return ""
