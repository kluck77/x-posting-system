"""
어드바이저리 레이블 (Advisory Labels)
=======================================
소스/초안 우선순위를 단순 레이블로 표현합니다.
Layer 2 전용 — 어떤 흐름도 차단하지 않습니다.

레이블 기준 (0~100 점수 기반):
  🔴 우선 (High)   : score >= 60
  🟡 보통 (Medium) : 40 <= score < 60
  ⚪ 보류 (Hold)   : score < 40

중요 — 역할 분리 (이번 세션에서 정합성 수정):
  * 여기서 내는 '우선순위' 는 '시의성/운영 중요도' 다.
    품질 점수와는 완전히 독립이다.
  * 품질 점수 → quality_scorer.score_5criteria() 만이 단일 소스.
  * 최종 추천 → telegram_service._recommended_action() 이 품질+위험을 조합해 계산.
  * 과거에는 draft_advisory 가 quality_scorer.score_draft() 결과를 '우선순위' 로
    잘못 라벨링해서 카드에 '품질 20/100 + 우선순위 🔴 + 추천 승인 가능' 같은
    모순이 발생했다. 이 모듈은 이제 품질 scorer 를 호출하지 않는다.

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


# 시의성/운영 중요도 기반 우선순위 점수 (0~100)
# 원칙:
#   - 운영자가 직접 넣은 입력(manual) 은 시의성이 있다고 가정 → 🔴
#   - 커뮤니티 실시간 반응도 시의성 높음 → 🔴
#   - 일반 뉴스 링크는 중간 → 🟡
#   - 자동수집 배치/RSS 는 배경 수준 → 🟡~⚪
#   - 아침 다이제스트는 누적 브리핑 → ⚪
# 이 점수는 '품질' 이 아니다. 품질은 score_5criteria 가 별도로 낸다.
_SOURCE_TYPE_URGENCY: dict[str, int] = {
    "manual": 70,
    "community_input": 70,
    "breaking": 85,
    "breaking_news": 85,
    "news_link": 55,
    "raw_text": 55,
    "x_link": 55,
    "web_ingest": 50,
    "naver_auto": 40,
    "rss_feed": 40,
    "morning_digest": 30,
}

# 본문/훅에서 실시간성을 올려 잡는 키워드 (언어 무관)
_BREAKING_KEYWORDS: tuple[str, ...] = (
    "breaking",
    "속보",
    "긴급",
    "just in",
    "urgent",
    "발표 직후",
)


def draft_advisory(hook: str, body: str, source_type: str = "news_link") -> str:
    """
    초안 우선순위 레이블 — '시의성/운영 중요도' 기준.

    이 값은 '품질' 과 독립이다. 품질 점수는 quality_scorer.score_5criteria 가
    계산하며, 최종 추천은 telegram_service._recommended_action 이 품질+위험을
    조합해 낸다. 과거의 score_draft 기반 품질 점수-as-우선순위 혼동을 제거한다.

    판정 신호:
      1) source_type → 기본 urgency 점수
      2) hook/body 에 breaking 키워드가 있으면 +20 부스트
      3) priority_label() 공통 임계값 적용

    Args:
        hook: 초안 훅 텍스트 (breaking 키워드 감지에만 사용)
        body: 초안 본문 텍스트 (breaking 키워드 감지에만 사용)
        source_type: 소스 유형 (기본값: 'news_link')

    Returns:
        '🔴 우선' | '🟡 보통' | '⚪ 보류' | ''
    """
    try:
        base = _SOURCE_TYPE_URGENCY.get(source_type, 50)
        text_lower = f"{hook or ''}\n{body or ''}".lower()
        if any(kw in text_lower for kw in _BREAKING_KEYWORDS):
            base = min(base + 20, 100)
        return priority_label(base)
    except Exception as e:
        logger.debug(f"[Advisory] draft_advisory 실패 (무시): {e}")
        return ""
