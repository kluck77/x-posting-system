"""
activity_tracker.py 테스트.
유휴 알림 조건 및 스팸 방지 로직 검증.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from pathlib import Path


class TestRecordAndGetActivity:
    def test_get_last_activity_returns_none_when_no_record(self, tmp_path):
        """활동 기록이 없으면 None 반환."""
        import app.services.growth.activity_tracker as at
        with patch.object(at, "_STATE_FILE", tmp_path / "activity.json"):
            assert at.get_last_activity() is None

    def test_record_then_get_returns_timestamp(self, tmp_path):
        """record_activity() 후 get_last_activity()가 datetime 반환."""
        import app.services.growth.activity_tracker as at
        with patch.object(at, "_STATE_FILE", tmp_path / "activity.json"):
            at.record_activity()
            result = at.get_last_activity()
        assert result is not None
        assert isinstance(result, datetime)

    def test_record_overwrites_previous(self, tmp_path):
        """record_activity()를 두 번 호출하면 최신 시각으로 덮어쓴다."""
        import app.services.growth.activity_tracker as at
        with patch.object(at, "_STATE_FILE", tmp_path / "activity.json"):
            at.record_activity()
            first = at.get_last_activity()
            at.record_activity()
            second = at.get_last_activity()
        assert second >= first


class TestShouldSendIdleReminder:
    def test_no_activity_record_returns_false(self, tmp_path):
        """활동 기록이 없으면 False (최초 설치 과잉 알림 방지)."""
        import app.services.growth.activity_tracker as at
        with patch.object(at, "_STATE_FILE", tmp_path / "activity.json"):
            assert at.should_send_idle_reminder() is False

    def test_recent_activity_returns_false(self, tmp_path):
        """최근 활동(1시간 전)이 있으면 False."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{recent}"}}', encoding="utf-8")
        with patch.object(at, "_STATE_FILE", state_file):
            assert at.should_send_idle_reminder() is False

    def test_idle_48h_no_previous_reminder_returns_true(self, tmp_path):
        """48시간 이상 활동 없고 알림 이력 없으면 True."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{old}"}}', encoding="utf-8")
        with patch.object(at, "_STATE_FILE", state_file):
            assert at.should_send_idle_reminder() is True

    def test_idle_48h_recent_reminder_returns_false(self, tmp_path):
        """48시간 이상 활동 없지만 최근 알림(12시간 전)이 있으면 False (스팸 방지)."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        old_activity = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        recent_reminder = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        state_file.write_text(
            f'{{"last_activity_at": "{old_activity}", "last_reminder_at": "{recent_reminder}"}}',
            encoding="utf-8",
        )
        with patch.object(at, "_STATE_FILE", state_file):
            assert at.should_send_idle_reminder() is False

    def test_idle_48h_old_reminder_returns_true(self, tmp_path):
        """48시간 이상 활동 없고 마지막 알림이 25시간 전이면 True."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        old_activity = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        old_reminder = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        state_file.write_text(
            f'{{"last_activity_at": "{old_activity}", "last_reminder_at": "{old_reminder}"}}',
            encoding="utf-8",
        )
        with patch.object(at, "_STATE_FILE", state_file):
            assert at.should_send_idle_reminder() is True

    def test_exactly_48h_triggers(self, tmp_path):
        """정확히 48시간은 알림 조건 충족 (< 아닌 ==, 스팸 이력 없음)."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        exactly_48h = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{exactly_48h}"}}', encoding="utf-8")
        with patch.object(at, "_STATE_FILE", state_file):
            # total_seconds() == 48*3600 → not less-than → 조건 미충족 → 알림 발송
            assert at.should_send_idle_reminder() is True


class TestCheckAndSendIdleReminder:
    @pytest.mark.asyncio
    async def test_sends_message_when_idle(self, tmp_path):
        """유휴 조건 충족 시 tg_send가 호출된다."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{old}"}}', encoding="utf-8")

        with (
            patch.object(at, "_STATE_FILE", state_file),
            patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock) as mock_tg,
        ):
            await at.check_and_send_idle_reminder()

        mock_tg.assert_called_once()
        call_arg = mock_tg.call_args[0][0]
        assert "유휴" in call_arg

    @pytest.mark.asyncio
    async def test_does_not_send_when_recent_activity(self, tmp_path):
        """최근 활동 있으면 tg_send가 호출되지 않는다."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{recent}"}}', encoding="utf-8")

        with (
            patch.object(at, "_STATE_FILE", state_file),
            patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock) as mock_tg,
        ):
            await at.check_and_send_idle_reminder()

        mock_tg.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_reminder_sent_after_send(self, tmp_path):
        """알림 발송 후 last_reminder_at이 기록된다."""
        import app.services.growth.activity_tracker as at
        import json
        state_file = tmp_path / "activity.json"
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{old}"}}', encoding="utf-8")

        with (
            patch.object(at, "_STATE_FILE", state_file),
            patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock),
        ):
            await at.check_and_send_idle_reminder()

        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert "last_reminder_at" in state

    @pytest.mark.asyncio
    async def test_does_not_crash_when_tg_fails(self, tmp_path):
        """tg_send가 예외를 던져도 check_and_send_idle_reminder는 조용히 종료된다."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        state_file.write_text(f'{{"last_activity_at": "{old}"}}', encoding="utf-8")

        with (
            patch.object(at, "_STATE_FILE", state_file),
            patch(
                "app.services.growth._tg_helper.tg_send",
                new_callable=AsyncMock,
                side_effect=RuntimeError("tg fail"),
            ),
        ):
            # 예외가 바깥으로 전파되지 않아야 함
            await at.check_and_send_idle_reminder()
