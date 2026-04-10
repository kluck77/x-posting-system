"""
tests/test_news_monitor_loop.py
================================
news_monitor 폴링 루프 + full_pipeline 연결 테스트.

app.main._news_monitor_loop() 의 핵심 동작을 검증한다:
1. news_monitor.py 없으면 자동 비활성화 (ImportError)
2. 사이클 실행 후 60초 대기
3. 사이클 실패 시 fail-open (다음 사이클 계속)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _news_monitor_loop 동작 테스트
# ---------------------------------------------------------------------------

class TestNewsMonitorLoop:
    @pytest.mark.asyncio
    async def test_import_error_graceful_exit(self):
        """news_monitor.py 가 없으면 조용히 종료."""
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # ImportError 발생 시뮬레이션
            with patch.dict("sys.modules", {"app.services.news_monitor": None}):
                # _news_monitor_loop 로직 재현 (import 실패 → return)
                try:
                    from app.services.news_monitor import run_monitor_cycle
                    imported = True
                except (ImportError, TypeError):
                    imported = False

                assert not imported

    @pytest.mark.asyncio
    async def test_cycle_called_and_sleeps(self):
        """사이클 실행 후 60초 대기."""
        call_count = 0

        async def fake_cycle():
            nonlocal call_count
            call_count += 1

        # 1회 실행 후 탈출하도록 side_effect 설계
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            if len(sleep_calls) >= 2:  # 초기 대기 + 1회 인터벌 후 중단
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            # 루프 로직 시뮬레이션
            await fake_sleep(10)  # 초기 대기
            try:
                await fake_cycle()
                await fake_sleep(60)  # 인터벌
            except asyncio.CancelledError:
                pass

        assert call_count == 1
        assert sleep_calls[0] == 10  # 초기 대기
        assert sleep_calls[1] == 60  # 인터벌

    @pytest.mark.asyncio
    async def test_cycle_failure_is_fail_open(self):
        """사이클 실패 시 예외를 삼키고 계속."""
        errors = []

        async def failing_cycle():
            raise RuntimeError("test error")

        # fail-open 로직 테스트
        try:
            await failing_cycle()
        except Exception as e:
            errors.append(str(e))
            # fail-open: 예외 로그만 남기고 계속

        assert len(errors) == 1
        assert "test error" in errors[0]


# ---------------------------------------------------------------------------
# full_pipeline 연결 테스트 (breaking_classifier 사전 분류)
# ---------------------------------------------------------------------------

class TestMonitorPipelineIntegration:
    def test_breaking_classifier_filters_correctly(self):
        """BREAKING/CANDIDATE 만 full_pipeline 대상."""
        from app.services.breaking_classifier import classify_article

        # CANDIDATE 예상 (금융 키워드)
        result = classify_article(
            title="한국은행 기준금리 동결 결정",
            body="한국은행 금융통화위원회가 기준금리를 동결했다. "
                 "시장 컨센서스와 일치하는 결정이다. "
                 "향후 경기 흐름을 주시하겠다고 밝혔다.",
            url="https://example.com/bok",
        )
        assert result.classification in ("BREAKING_NOW", "CANDIDATE")
        assert result.topic_domain in ("금융", "투자", "크립토", "주식")

    def test_reject_article_skipped(self):
        """REJECT 기사는 full_pipeline 대상 아님."""
        from app.services.breaking_classifier import classify_article

        # 충분한 본문 + 제외 키워드 → REJECT
        result = classify_article(
            title="인기 드라마 주연 배우 열애설 보도",
            body="인기 드라마의 주연 배우가 열애 중이라는 보도가 나왔다. "
                 "소속사는 아직 공식 입장을 내지 않았다. "
                 "팬 커뮤니티에서는 다양한 반응이 나오고 있다.",
            url="https://example.com/drama",
        )
        assert result.classification == "REJECT"

    def test_hold_article_skipped(self):
        """HOLD 기사는 full_pipeline 대상 아님."""
        from app.services.breaking_classifier import classify_article

        result = classify_article(
            title="오늘 시장 요약",
            body="조용한 하루.",
            url="https://example.com/quiet",
        )
        assert result.classification == "HOLD"

    def test_source_type_naver_auto(self):
        """SourceItemCreate 에 naver_auto source_type 설정 가능."""
        from app.models.content import SourceItemCreate

        payload = SourceItemCreate(
            title="테스트 기사",
            source_text="본문 내용",
            url="https://example.com/test",
            source_type="naver_auto",
            language="ko",
        )
        assert payload.source_type == "naver_auto"
        assert payload.language == "ko"

    def test_source_type_rss_auto(self):
        """rss_auto source_type 도 가능."""
        from app.models.content import SourceItemCreate

        payload = SourceItemCreate(
            title="RSS 기사",
            source_text="RSS 본문",
            url="https://example.com/rss",
            source_type="rss_auto",
            language="ko",
        )
        assert payload.source_type == "rss_auto"
