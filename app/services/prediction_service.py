"""
예측 게시 시간 서비스
====================
콘텐츠 카테고리·위험 수준·현재 UTC 시각을 기반으로
영어권 독자에게 최적인 X 포스팅 시간을 예측합니다.

타겟 오디언스: 미국·영국 영어권 독자
기준: UTC (KST 아침 기준 아님)
DST 참고: KST는 연중 UTC+9 고정, DST 없음
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.content import ContentCategory, RiskLevel

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

# 카테고리별 UTC 목표 시각 (hour)
# 근거: Buffer 870만 트윗 분석 + SocialPilot 70만 트윗 분석
# - 뉴스/정책/경제: UTC 12:00 = 미국 동부 07:00 + 영국 12:00 교차점
# - KPOP:          UTC 00:00 = KST 09:00 (한국 아침 피크) + 미국 서부 전날 17:00
# - EVERGREEN:     UTC 10:00 = 영국 오전 피크
_CATEGORY_TARGET_HOUR_UTC: dict[ContentCategory, int] = {
    ContentCategory.POLITICS:     12,
    ContentCategory.POLICY:       12,
    ContentCategory.ECONOMY:      12,
    ContentCategory.SOCIETY:      13,
    ContentCategory.KPOP_CULTURE:  0,
    ContentCategory.EVERGREEN:    10,
}

# 카테고리별 선호 요일 (0=월요일 ~ 6=일요일)
# 뉴스성 콘텐츠는 주말 참여율이 현저히 낮음
_CATEGORY_PREFERRED_DAYS: dict[ContentCategory, list[int]] = {
    ContentCategory.POLITICS:     [1, 2, 3],        # 화·수·목
    ContentCategory.POLICY:       [1, 2, 3],
    ContentCategory.ECONOMY:      [1, 2, 3],
    ContentCategory.SOCIETY:      [1, 2, 3],
    ContentCategory.KPOP_CULTURE: [1, 2, 3, 4, 5],  # 화~토 (팬덤은 주말도 활발)
    ContentCategory.EVERGREEN:    [1, 3],            # 화·목
}

_CATEGORY_REASONING: dict[ContentCategory, str] = {
    ContentCategory.POLITICS:
        "정치 뉴스 – 미국 동부 오전 + 영국 정오 교차점 (UTC 12:00)",
    ContentCategory.POLICY:
        "정책 뉴스 – 미국 동부 오전 + 영국 정오 교차점 (UTC 12:00)",
    ContentCategory.ECONOMY:
        "경제 뉴스 – 미국 동부 오전 + 영국 정오 교차점 (UTC 12:00)",
    ContentCategory.SOCIETY:
        "사회 이슈 – 미국 동부 오전 피크 (UTC 13:00)",
    ContentCategory.KPOP_CULTURE:
        "K-pop/문화 – KST 09:00 아침 피크 + 미국 서부 전날 저녁 교차 (UTC 00:00)",
    ContentCategory.EVERGREEN:
        "에버그린 – 영국 오전 피크 (UTC 10:00)",
}


def predict_publish_time(
    category: ContentCategory,
    risk_level: RiskLevel,
    now: datetime,
) -> tuple[datetime, str]:
    """
    최적 게시 시간 예측.

    Args:
        category: 콘텐츠 카테고리
        risk_level: 위험 수준
        now: 현재 시각 (UTC aware datetime)

    Returns:
        (predicted_utc, reasoning_korean) 튜플
        - predicted_utc: UTC aware datetime
        - reasoning_korean: 한국어 예측 근거 문자열
    """
    assert now.tzinfo is not None, "now must be tz-aware (UTC)"

    target_hour = _CATEGORY_TARGET_HOUR_UTC[category]
    preferred_days = _CATEGORY_PREFERRED_DAYS[category]
    base_reasoning = _CATEGORY_REASONING[category]

    # HIGH 리스크: +1시간 지연 (추가 검토 여유)
    delay_hours = 1 if risk_level == RiskLevel.HIGH else 0
    effective_hour = (target_hour + delay_hours) % 24

    # 오늘 UTC 기준 목표 시각 구성
    candidate = now.replace(
        hour=effective_hour, minute=0, second=0, microsecond=0, tzinfo=UTC
    )

    # 목표 시각이 이미 지났으면 다음 날부터 선호 요일 탐색
    if now >= candidate:
        candidate += timedelta(days=1)

    # 선호 요일이 아닌 경우 최대 7일 내 가장 가까운 선호 요일로 이동
    for _ in range(7):
        if candidate.weekday() in preferred_days:
            break
        candidate += timedelta(days=1)

    # KST 표현 (확인용)
    kst_time = candidate.astimezone(KST)

    # reasoning 조립
    risk_note = " (HIGH 리스크로 +1시간 지연 적용)" if risk_level == RiskLevel.HIGH else ""
    reasoning = (
        f"{base_reasoning}{risk_note} → "
        f"KST {kst_time.strftime('%m/%d(%a) %H:%M')}"
    )

    return candidate, reasoning
