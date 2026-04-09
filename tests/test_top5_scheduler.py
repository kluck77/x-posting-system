"""
tests/test_top5_scheduler.py
==============================
Top5 05:00 KST 스케줄러 루프 단위 테스트.

app.main 은 uvicorn 의존으로 직접 import 불가한 환경이 있으므로,
스케줄러 핵심 로직(시각 계산)을 독립 테스트한다.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

# KST 상수 (app.main 과 동일)
_KST = timezone(timedelta(hours=9))
_TOP5_HOUR = 5
_TOP5_MINUTE = 0


def _next_target(now_kst: datetime) -> datetime:
    """app.main._top5_scheduler_loop 내 대기 시각 계산 로직 추출."""
    target = now_kst.replace(hour=_TOP5_HOUR, minute=_TOP5_MINUTE, second=0, microsecond=0)
    if target <= now_kst:
        target += timedelta(days=1)
    return target


# ---------------------------------------------------------------------------
# 시각 계산 테스트
# ---------------------------------------------------------------------------
class TestNextTarget:
    def test_before_target_same_day(self):
        """03:30 KST → 당일 05:00."""
        now = datetime(2026, 4, 10, 3, 30, tzinfo=_KST)
        t = _next_target(now)
        assert t == datetime(2026, 4, 10, 5, 0, tzinfo=_KST)

    def test_after_target_next_day(self):
        """06:00 KST → 익일 05:00."""
        now = datetime(2026, 4, 10, 6, 0, tzinfo=_KST)
        t = _next_target(now)
        assert t == datetime(2026, 4, 11, 5, 0, tzinfo=_KST)

    def test_exact_target_next_day(self):
        """정확히 05:00 → 익일 05:00."""
        now = datetime(2026, 4, 10, 5, 0, 0, tzinfo=_KST)
        t = _next_target(now)
        assert t == datetime(2026, 4, 11, 5, 0, tzinfo=_KST)

    def test_midnight(self):
        """00:00 KST → 당일 05:00."""
        now = datetime(2026, 4, 10, 0, 0, tzinfo=_KST)
        t = _next_target(now)
        assert t == datetime(2026, 4, 10, 5, 0, tzinfo=_KST)

    def test_just_before_target(self):
        """04:59:59 → 당일 05:00."""
        now = datetime(2026, 4, 10, 4, 59, 59, tzinfo=_KST)
        t = _next_target(now)
        assert t == datetime(2026, 4, 10, 5, 0, tzinfo=_KST)

    def test_wait_seconds_positive(self):
        """대기 시간이 항상 양수."""
        now = datetime(2026, 4, 10, 12, 0, tzinfo=_KST)
        t = _next_target(now)
        wait = (t - now).total_seconds()
        assert wait > 0
        assert wait <= 86400  # 최대 24시간

    def test_wait_seconds_small_before(self):
        """05:00 직전이면 대기 시간 매우 짧음."""
        now = datetime(2026, 4, 10, 4, 59, 0, tzinfo=_KST)
        t = _next_target(now)
        wait = (t - now).total_seconds()
        assert wait == 60


# ---------------------------------------------------------------------------
# 스케줄러 루프 통합 테스트 (asyncio.run 사용)
# ---------------------------------------------------------------------------
class TestSchedulerLoop:
    def test_loop_calls_run_top5(self):
        """스케줄러 루프가 run_top5_briefing 을 호출하는지 확인."""

        async def _run():
            # 인라인 정의로 uvicorn import 회피
            call_count = 0
            mock_run = AsyncMock(return_value=True)

            async def fake_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError

            with patch("asyncio.sleep", side_effect=fake_sleep), \
                 patch.dict("sys.modules", {"uvicorn": type("M", (), {"run": lambda *a, **k: None})}):
                import importlib
                import app.main as main_mod
                importlib.reload(main_mod)

                with patch("app.services.top5_briefing_service.run_top5_briefing", mock_run):
                    with pytest.raises(asyncio.CancelledError):
                        await main_mod._top5_scheduler_loop()

            mock_run.assert_called_once()

        asyncio.run(_run())

    def test_loop_fail_open(self):
        """run_top5_briefing 실패해도 루프 계속."""

        async def _run():
            call_count = 0
            mock_run = AsyncMock(side_effect=RuntimeError("test error"))

            async def fake_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count > 2:
                    raise asyncio.CancelledError

            with patch("asyncio.sleep", side_effect=fake_sleep), \
                 patch.dict("sys.modules", {"uvicorn": type("M", (), {"run": lambda *a, **k: None})}):
                import importlib
                import app.main as main_mod
                importlib.reload(main_mod)

                with patch("app.services.top5_briefing_service.run_top5_briefing", mock_run):
                    with pytest.raises(asyncio.CancelledError):
                        await main_mod._top5_scheduler_loop()

            assert mock_run.call_count == 2

        asyncio.run(_run())
