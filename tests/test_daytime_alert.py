"""
주간 고점수 CANDIDATE 즉시 알림 테스트
======================================
"""

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# requests_oauthlib 가 없는 sandbox 에서도 import 가능하게
if "requests_oauthlib" not in sys.modules:
    _mock_oauth = ModuleType("requests_oauthlib")
    _mock_oauth.OAuth1 = MagicMock()  # type: ignore[attr-defined]
    sys.modules["requests_oauthlib"] = _mock_oauth

from app.services.daytime_alert_service import (
    DAYTIME_FRESHNESS_HOURS,
    DAYTIME_MIN_KEYWORDS,
    DAYTIME_SCORE_THRESHOLD,
    _is_daytime_kst,
    _is_fresh,
    build_daytime_alert_text,
    should_send_daytime_alert,
)

_KST = timezone(timedelta(hours=9))
_UTC = timezone.utc


# ---------------------------------------------------------------------------
# _is_daytime_kst
# ---------------------------------------------------------------------------
class TestIsDaytimeKst:
    def test_morning_is_daytime(self):
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is True

    def test_afternoon_is_daytime(self):
        now = datetime(2026, 4, 10, 15, 30, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is True

    def test_5am_is_daytime(self):
        now = datetime(2026, 4, 10, 5, 0, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is True

    def test_2159_is_daytime(self):
        now = datetime(2026, 4, 10, 21, 59, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is True

    def test_2200_is_nighttime(self):
        now = datetime(2026, 4, 10, 22, 0, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is False

    def test_midnight_is_nighttime(self):
        now = datetime(2026, 4, 10, 0, 0, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is False

    def test_3am_is_nighttime(self):
        now = datetime(2026, 4, 10, 3, 0, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is False

    def test_459_is_nighttime(self):
        now = datetime(2026, 4, 10, 4, 59, tzinfo=_KST)
        assert _is_daytime_kst(now=now) is False

    def test_utc_converted_to_kst(self):
        # 14:00 UTC = 23:00 KST → nighttime
        now = datetime(2026, 4, 10, 14, 0, tzinfo=_UTC)
        assert _is_daytime_kst(now=now) is False

    def test_utc_daytime(self):
        # 06:00 UTC = 15:00 KST → daytime
        now = datetime(2026, 4, 10, 6, 0, tzinfo=_UTC)
        assert _is_daytime_kst(now=now) is True


# ---------------------------------------------------------------------------
# _is_fresh
# ---------------------------------------------------------------------------
class TestIsFresh:
    def test_recent_is_fresh(self):
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_UTC)
        collected = datetime(2026, 4, 10, 9, 0, tzinfo=_UTC)
        assert _is_fresh(collected, now=now) is True

    def test_old_is_not_fresh(self):
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_UTC)
        collected = datetime(2026, 4, 10, 7, 0, tzinfo=_UTC)
        assert _is_fresh(collected, now=now) is False

    def test_none_collected_is_fresh(self):
        assert _is_fresh(None) is True

    def test_exactly_2h_is_fresh(self):
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_UTC)
        collected = datetime(2026, 4, 10, 8, 0, tzinfo=_UTC)
        assert _is_fresh(collected, now=now) is True


# ---------------------------------------------------------------------------
# should_send_daytime_alert
# ---------------------------------------------------------------------------
class TestShouldSendDaytimeAlert:
    def _daytime_now(self):
        return datetime(2026, 4, 10, 10, 0, tzinfo=_KST)

    def _nighttime_now(self):
        return datetime(2026, 4, 10, 23, 0, tzinfo=_KST)

    def _fresh_collected(self, now):
        return now - timedelta(hours=1)

    def test_all_conditions_met(self):
        now = self._daytime_now()
        assert should_send_daytime_alert(
            matched_keywords=["a", "b", "c", "d"],
            score=60,
            collected_at=self._fresh_collected(now),
            now=now,
        ) is True

    def test_nighttime_blocked(self):
        now = self._nighttime_now()
        assert should_send_daytime_alert(
            matched_keywords=["a", "b", "c", "d"],
            score=60,
            collected_at=self._fresh_collected(now),
            now=now,
        ) is False

    def test_too_few_keywords_blocked(self):
        now = self._daytime_now()
        assert should_send_daytime_alert(
            matched_keywords=["a", "b", "c"],
            score=60,
            collected_at=self._fresh_collected(now),
            now=now,
        ) is False

    def test_low_score_blocked(self):
        now = self._daytime_now()
        assert should_send_daytime_alert(
            matched_keywords=["a", "b", "c", "d"],
            score=50,
            collected_at=self._fresh_collected(now),
            now=now,
        ) is False

    def test_stale_article_blocked(self):
        now = self._daytime_now()
        old = now - timedelta(hours=5)
        assert should_send_daytime_alert(
            matched_keywords=["a", "b", "c", "d"],
            score=60,
            collected_at=old,
            now=now,
        ) is False

    def test_threshold_values(self):
        """임계값 자체가 올바르게 설정되어 있는지 확인."""
        assert DAYTIME_SCORE_THRESHOLD == 55
        assert DAYTIME_MIN_KEYWORDS == 4
        assert DAYTIME_FRESHNESS_HOURS == 2


# ---------------------------------------------------------------------------
# build_daytime_alert_text
# ---------------------------------------------------------------------------
class TestBuildDaytimeAlertText:
    def test_basic_card(self):
        text = build_daytime_alert_text(
            title="비트코인 현물 ETF 자금 유입 7억달러 기록",
            body="비트코인 현물 ETF에 7억달러가 유입됐다. 이는 사상 최대 규모다.",
            url="https://example.com/article",
            topic_domain="크립토",
            matched_keywords=["비트코인", "ETF", "자금 유입", "현물 ETF"],
            score=62,
        )
        assert "[주간 주목]" in text
        assert "크립토" in text
        assert "62/100" in text
        assert "example.com" in text

    def test_prefix_is_correct(self):
        text = build_daytime_alert_text(
            title="테스트 제목",
            body="테스트 본문입니다.",
            url=None,
            topic_domain="금융",
            matched_keywords=["금리"],
            score=55,
        )
        assert text.startswith("[주간 주목]")
        # URL 없으면 원문 라인 없음
        assert "원문" not in text

    def test_long_title_clipped(self):
        long_title = "가" * 100
        text = build_daytime_alert_text(
            title=long_title,
            body="본문",
            url=None,
            topic_domain="금융",
            matched_keywords=[],
            score=55,
        )
        # 60자 클립
        first_line = text.split("\n")[0]
        assert len(first_line) <= len("[주간 주목] ") + 60


# ---------------------------------------------------------------------------
# try_daytime_alert (통합 테스트)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestTryDaytimeAlert:
    async def test_daytime_high_score_sends(self):
        """주간 + 고점수 + 교차검증 → 알림 전송."""
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_KST)
        collected = now - timedelta(minutes=30)
        from app.services.daytime_alert_service import try_daytime_alert

        # 점수 충족에 필요: 본문 800자+, 수치 다수, 인용 다수
        body = (
            "미국 연준이 4월 FOMC에서 기준금리를 5.25%에서 5.00%로 인하 의결했다. "
            "파월 의장은 기자회견에서 인플레이션이 2%대로 수렴하고 있다고 밝혔다. "
            "이번 결정으로 달러 인덱스는 발표 직후 1.2% 하락했으며 104.3에서 103.1로 하락했다. "
            "금값은 온스당 2,350달러로 1.5% 상승했다. "
            "한국은행 관계자에 따르면 5월 금통위에서 금리 인하를 검토할 전망이다. "
            "코스피 선물은 야간 거래에서 0.8% 상승하며 영향을 반영했다. "
            "미국 10년물 국채 수익률은 4.2%에서 4.05%로 15bp 하락했다. "
            "연준의 점도표에 따르면 올해 추가 2회 인하가 전망된다. "
            "시장 분석가들은 이번 결정이 자금흐름과 심리에 미치는 영향이 크다고 분석했다. "
            "GDP 성장률 둔화와 고용 시장 약화가 이번 결정의 핵심 배경으로 지목된다. "
            "파월 의장은 '경기침체 리스크를 선제적으로 관리하겠다'고 발표했다. "
            "유럽 ECB도 6월 회의에서 금리 인하를 논의할 것으로 전망된다. "
            "원/달러 환율은 장중 1,380원까지 하락하며 수출주에 부정적 영향이 예상된다."
        )
        result = await try_daytime_alert(
            title="미 연준 FOMC 금리 인하 의결 발표, 환율 달러 국채 금값 영향",
            body=body,
            url="https://example.com/fomc",
            topic_domain="금융",
            matched_keywords=["기준금리", "FOMC", "연준", "환율", "금값"],
            collected_at=collected,
            now=now,
        )
        # mock 텔레그램이므로 True 반환 (조건 충족 시)
        assert result is True

    async def test_nighttime_does_not_send(self):
        """야간에는 조건 충족해도 알림 안 보냄."""
        now = datetime(2026, 4, 10, 23, 0, tzinfo=_KST)
        collected = now - timedelta(minutes=30)
        from app.services.daytime_alert_service import try_daytime_alert

        result = await try_daytime_alert(
            title="미 연준 FOMC 금리 동결 의결 발표, 환율 달러 국채 금값 영향",
            body="미국 연준이 금리를 동결했다. 파월은 인플레이션 경계를 유지한다.",
            url="https://example.com/fomc",
            topic_domain="금융",
            matched_keywords=["기준금리", "FOMC", "연준", "환율", "금값"],
            collected_at=collected,
            now=now,
        )
        assert result is False

    async def test_few_keywords_does_not_send(self):
        """교차검증 부족 → 알림 안 보냄."""
        now = datetime(2026, 4, 10, 10, 0, tzinfo=_KST)
        collected = now - timedelta(minutes=30)
        from app.services.daytime_alert_service import try_daytime_alert

        result = await try_daytime_alert(
            title="비트코인 가격 변동",
            body="비트코인이 소폭 상승했다.",
            url="https://example.com",
            topic_domain="크립토",
            matched_keywords=["비트코인"],  # 1개만
            collected_at=collected,
            now=now,
        )
        assert result is False
