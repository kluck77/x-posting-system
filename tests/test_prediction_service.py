"""
prediction_service 단위 테스트
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.content import ContentCategory, RiskLevel
from app.services.prediction_service import predict_publish_time

UTC = timezone.utc
KST = ZoneInfo("Asia/Seoul")


def _make_utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# 테스트용 고정 기준 시각: 2026-04-01 수요일 10:00 UTC
BASE_NOW = _make_utc(2026, 4, 1, 10, 0)


class TestPredictPublishTimeBasic:

    def test_returns_utc_aware_datetime(self):
        result_time, reasoning = predict_publish_time(
            ContentCategory.ECONOMY, RiskLevel.MEDIUM, BASE_NOW
        )
        assert result_time.tzinfo is not None

    def test_returns_reasoning_string(self):
        _, reasoning = predict_publish_time(
            ContentCategory.ECONOMY, RiskLevel.MEDIUM, BASE_NOW
        )
        assert isinstance(reasoning, str)
        assert len(reasoning) > 0

    def test_predicted_time_is_in_future(self):
        result_time, _ = predict_publish_time(
            ContentCategory.POLITICS, RiskLevel.LOW, BASE_NOW
        )
        assert result_time > BASE_NOW

    def test_requires_tz_aware_input(self):
        naive = datetime(2026, 4, 1, 10, 0)
        with pytest.raises(AssertionError):
            predict_publish_time(ContentCategory.ECONOMY, RiskLevel.LOW, naive)


class TestCategoryTargetHours:

    @pytest.mark.parametrize("category,expected_utc_hour", [
        (ContentCategory.POLITICS,     12),
        (ContentCategory.POLICY,       12),
        (ContentCategory.ECONOMY,      12),
        (ContentCategory.SOCIETY,      13),
        (ContentCategory.KPOP_CULTURE,  0),
        (ContentCategory.EVERGREEN,    10),
    ])
    def test_target_hour_low_risk(self, category, expected_utc_hour):
        # 기준: 목표 시각보다 훨씬 이른 시각 (02:00 UTC)
        now = _make_utc(2026, 4, 7, 2, 0)  # 화요일
        result_time, _ = predict_publish_time(category, RiskLevel.LOW, now)
        assert result_time.hour == expected_utc_hour


class TestHighRiskDelay:

    def test_high_risk_adds_one_hour(self):
        # ECONOMY LOW = UTC 12:00, HIGH = UTC 13:00
        now = _make_utc(2026, 4, 1, 6, 0)  # 수요일 06:00 UTC

        low_time, _ = predict_publish_time(ContentCategory.ECONOMY, RiskLevel.LOW, now)
        high_time, _ = predict_publish_time(ContentCategory.ECONOMY, RiskLevel.HIGH, now)

        assert high_time.hour == (low_time.hour + 1) % 24

    def test_high_risk_reasoning_mentions_delay(self):
        now = _make_utc(2026, 4, 1, 6, 0)
        _, reasoning = predict_publish_time(ContentCategory.POLITICS, RiskLevel.HIGH, now)
        assert "HIGH" in reasoning or "+1시간" in reasoning


class TestPreferredDays:

    def test_politics_avoids_weekend(self):
        # 2026-04-04 토요일 06:00 UTC — 다음 선호 요일(화)로 이동해야 함
        saturday = _make_utc(2026, 4, 4, 6, 0)
        result_time, _ = predict_publish_time(ContentCategory.POLITICS, RiskLevel.LOW, saturday)
        # 결과는 화·수·목 중 하나여야 함
        assert result_time.weekday() in [1, 2, 3]

    def test_kpop_allows_saturday(self):
        # KPOP은 토요일도 선호 요일
        saturday = _make_utc(2026, 4, 4, 1, 0)  # 토요일 01:00 UTC (00:00 이미 지남)
        result_time, _ = predict_publish_time(ContentCategory.KPOP_CULTURE, RiskLevel.LOW, saturday)
        # 다음 날(일요일)은 선호 아님 → 화요일
        # 단, 토요일 목표시각(00:00)이 이미 지났으므로 다음 선호 요일 탐색
        assert result_time.weekday() in [1, 2, 3, 4, 5]

    def test_result_within_7_days(self):
        # 어떤 입력이든 7일 이내 결과
        now = _make_utc(2026, 4, 1, 10, 0)
        for category in ContentCategory:
            result_time, _ = predict_publish_time(category, RiskLevel.LOW, now)
            assert result_time <= now + timedelta(days=7)


class TestEdgeCases:

    def test_target_hour_already_passed_today(self):
        # ECONOMY 목표 = UTC 12:00, 현재 13:00 → 다음 선호 요일로 넘어가야 함
        now = _make_utc(2026, 4, 1, 13, 0)  # 수요일 13:00 UTC
        result_time, _ = predict_publish_time(ContentCategory.ECONOMY, RiskLevel.LOW, now)
        assert result_time > now

    def test_target_hour_exact_match_goes_to_next(self):
        # 정각 = "이미 지남" 처리
        now = _make_utc(2026, 4, 1, 12, 0)  # 수요일 12:00 UTC
        result_time, _ = predict_publish_time(ContentCategory.ECONOMY, RiskLevel.LOW, now)
        assert result_time > now

    def test_kst_conversion_in_reasoning(self):
        # reasoning에 KST 시간 포함 여부
        now = _make_utc(2026, 4, 7, 2, 0)  # 화요일
        _, reasoning = predict_publish_time(ContentCategory.ECONOMY, RiskLevel.LOW, now)
        assert "KST" in reasoning
