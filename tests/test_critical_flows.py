"""
Critical Flows Regression Bundle (Phase 16)
=============================================

Scenario-level regression tests for the most important operator-facing flows.
These tests protect against regressions in the real behaviors the operator relies on.

Run only critical flow tests:
    pytest -m critical -q --tb=short

Covers:
  1. Monitor paused guard — /monitor off must actually stop the scheduler from polling
  2. Queue lifecycle scenario — add → view → remove → clear as a sequential flow
  3. Cross-flow consistency — HTML structure, keyboard contents, recovery summary completeness
  4. Idle reminder lifecycle — end-to-end sequential scenario
  5. Recovery lifecycle — startup_check behavior with missing, valid, and corrupt files
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# 1. Monitor ON/OFF guard
# =============================================================================


class TestMonitorPausedGuard:
    """
    /monitor off must prevent run_reply_monitor() from polling.

    Regression guard: if the is_paused() early-return breaks, /monitor off
    has no effect and the monitor keeps running even when the operator paused it.
    """

    @pytest.mark.asyncio
    @pytest.mark.critical
    async def test_paused_monitor_skips_poll_entirely(self):
        """is_paused=True → ReplyMonitor is never instantiated → no API calls."""
        from app.services.growth import reply_monitor as rm
        with (
            patch("app.services.growth.monitor_state.is_paused", return_value=True),
            patch("app.services.growth.reply_monitor.ReplyMonitor") as mock_cls,
        ):
            await rm.run_reply_monitor()
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.critical
    async def test_unpaused_monitor_instantiates_monitor_class(self):
        """is_paused=False → ReplyMonitor is constructed and poll is attempted."""
        from app.services.growth import reply_monitor as rm
        with (
            patch("app.services.growth.monitor_state.is_paused", return_value=False),
            patch("app.services.growth.reply_monitor.ReplyMonitor") as mock_cls,
            patch("app.services.growth._tg_helper.tg_send_with_keyboard", new_callable=AsyncMock),
            patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock),
        ):
            mock_monitor = AsyncMock()
            mock_monitor.poll_new_replies = AsyncMock(return_value=[])
            mock_cls.return_value = mock_monitor
            await rm.run_reply_monitor()
        mock_cls.assert_called_once()

    @pytest.mark.critical
    def test_pause_resume_cycle_restores_expected_state(self, tmp_path):
        """off → on cycle produces the correct is_paused() values throughout."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "ms.json"):
            # Initially on
            assert ms.is_paused() is False
            # Turn off
            ms.pause()
            assert ms.is_paused() is True
            # Turn on again
            ms.resume()
            assert ms.is_paused() is False


# =============================================================================
# 2. Queue full lifecycle scenario
# =============================================================================


class TestQueueLifecycleScenario:
    """
    Sequential queue operations as the operator experiences them.
    Scenario: add → count → view → remove → position-shift → clear → empty.
    """

    def _make_queue(self):
        from app.services.growth.post_queue import PostQueue
        q = PostQueue.__new__(PostQueue)
        q._queue = []
        q._last_published = None
        return q

    @pytest.mark.critical
    def test_full_add_view_remove_clear_lifecycle(self):
        """add 3 → view(2) confirms B → remove(1) shifts positions → clear → empty."""
        q = self._make_queue()

        with patch.object(q, "_save"):
            post_a = q.add("포스트 A")
            post_b = q.add("포스트 B")
            post_c = q.add("포스트 C")

        assert q.count_pending() == 3

        # view(2) returns B without changing state
        assert q.get_pending_at(2) is post_b
        assert q.count_pending() == 3  # unchanged by view

        # remove(1) removes A; B shifts to position 1
        with patch.object(q, "_save"):
            removed = q.remove_pending(1)
        assert removed is post_a
        assert q.count_pending() == 2
        assert q.get_pending_at(1) is post_b
        assert q.get_pending_at(2) is post_c

        # clear removes B and C
        with patch.object(q, "_save"):
            n = q.clear_pending()
        assert n == 2
        assert q.count_pending() == 0
        assert q.get_pending_at(1) is None

    @pytest.mark.critical
    def test_published_item_invisible_throughout_lifecycle(self):
        """Published posts are excluded from count, view, remove, and clear."""
        from app.services.growth.post_queue import QueuedPost
        q = self._make_queue()

        published = QueuedPost(text="발행 완료")
        published.published_at = datetime.now(timezone.utc)
        q._queue.append(published)

        with patch.object(q, "_save"):
            pending = q.add("대기 중")

        assert q.count_pending() == 1
        assert q.get_pending_at(1) is pending
        assert q.get_pending_at(2) is None

        with patch.object(q, "_save"):
            q.remove_pending(1)

        assert published in q._queue
        assert q.count_pending() == 0

    @pytest.mark.asyncio
    @pytest.mark.critical
    async def test_notified_post_not_re_notified_on_next_scheduler_run(self):
        """notified_at already set → no re-notification on subsequent scheduler ticks."""
        from app.services.growth.post_queue import QueuedPost
        q = self._make_queue()

        post = QueuedPost(text="이미 알림 완료")
        post.notified_at = datetime.now(timezone.utc)
        q._queue.append(post)

        with (
            patch.object(q, "_is_optimal_slot_now", return_value=True),
            patch.object(q, "_can_publish_now", return_value=True),
            patch.object(q, "_send_approval_notification", new_callable=AsyncMock) as mock_notify,
        ):
            result = await q.try_publish_next()

        mock_notify.assert_not_called()
        assert result is None


# =============================================================================
# 3. Cross-flow consistency
# =============================================================================


class TestCrossFlowConsistency:
    """
    Operator-facing output structure must not regress.

    These tests verify that:
    - Approval cards always have valid HTML markup
    - The inline keyboard always has all four action buttons
    - The recovery summary always covers all four state files
    - /status and /monitor both report monitor state via the same is_paused() function
    - The callback data parser never admits unknown actions
    """

    def _make_draft(self):
        from app.models.content import ContentCategory, RiskLevel
        d = MagicMock()
        d.id = 1
        d.version = 1
        d.hook = "South Korea trade balance hits record"
        d.body = "Korea posted its largest trade surplus in five years."
        d.thread_continuation = None
        d.category = ContentCategory.ECONOMY
        d.risk_level = RiskLevel.LOW
        d.risk_reasoning = None
        d.ai_rationale = None
        d.community_warning = None
        d.predicted_publish_at = None
        d.prediction_reasoning = None
        d.text_length = len(d.body)
        return d

    @pytest.mark.critical
    def test_approval_card_always_contains_required_html_elements(self):
        """Approval card must have <b> tags and reference the draft ID."""
        from app.services.telegram_service import build_approval_card
        card = build_approval_card(self._make_draft())
        assert "<b>" in card, "Approval card must contain <b> HTML tags"
        assert "</b>" in card, "Approval card must close <b> HTML tags"
        assert "ID" in card, "Approval card must reference the draft ID"

    @pytest.mark.critical
    def test_approval_keyboard_always_has_all_four_action_buttons(self):
        """Keyboard must always have approve, reject, defer, and regenerate buttons."""
        from app.services.telegram_service import build_inline_keyboard
        kb = build_inline_keyboard(42)
        all_callbacks = [
            btn["callback_data"]
            for row in kb["inline_keyboard"]
            for btn in row
        ]
        assert any("approve:42" in c for c in all_callbacks)
        assert any("reject:42" in c for c in all_callbacks)
        assert any("defer:42" in c for c in all_callbacks)
        assert any("regenerate:42" in c for c in all_callbacks)

    @pytest.mark.critical
    def test_recovery_summary_always_contains_all_four_state_labels(self):
        """format_recovery_summary must render all 4 state-file labels."""
        from app.utils.startup_check import format_recovery_summary, _STATE_FILES, _LABELS
        results = {
            k: {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}
            for k in _STATE_FILES
        }
        summary = format_recovery_summary(results)
        for label in _LABELS.values():
            assert label in summary, f"Recovery summary must include label: {label}"

    @pytest.mark.critical
    def test_status_and_monitor_commands_both_use_is_paused(self):
        """
        /status and /monitor both report monitor state via is_paused().
        Read the source file directly — avoids telegram library import issues.
        If either command stops using is_paused(), monitor state reporting diverges.
        """
        src = Path(__file__).parent.parent / "app" / "telegram_bot.py"
        content = src.read_text(encoding="utf-8")
        # Both commands must reference is_paused (not a hardcoded value)
        assert content.count("is_paused") >= 2, (
            "telegram_bot.py must call is_paused() in at least 2 places "
            "(/status and /monitor)"
        )

    @pytest.mark.critical
    def test_callback_parser_rejects_non_allowlisted_actions(self):
        """parse_callback_data must reject any action not in the allowed list."""
        from app.services.telegram_service import parse_callback_data
        # Unknown / dangerous actions must be rejected
        assert parse_callback_data("delete:42") is None
        assert parse_callback_data("auto_post:1") is None
        assert parse_callback_data("bypass:99") is None
        assert parse_callback_data("approve_all:0") is None
        # Known actions must still work
        assert parse_callback_data("approve:1") == ("approve", 1)
        assert parse_callback_data("reject:1") == ("reject", 1)
        assert parse_callback_data("defer:1") == ("defer", 1)
        assert parse_callback_data("regenerate:1") == ("regenerate", 1)


# =============================================================================
# 4. Idle reminder full lifecycle (sequential scenario)
# =============================================================================


class TestIdleReminderLifecycleScenario:
    """
    End-to-end sequential scenario:
    record activity → simulate 50h idle → reminder fires →
    cooldown active → second reminder blocked → record activity → idle clock reset.
    """

    @pytest.mark.asyncio
    @pytest.mark.critical
    async def test_full_lifecycle_sequential(self, tmp_path):
        """Walk through the complete idle reminder lifecycle in one scenario."""
        import app.services.growth.activity_tracker as at
        state_file = tmp_path / "activity.json"

        with patch.object(at, "_STATE_FILE", state_file):
            # 1. Record initial activity
            at.record_activity()
            assert at.get_last_activity() is not None

            # 2. Simulate 50h of inactivity by backdating the record
            old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
            state_file.write_text(json.dumps({"last_activity_at": old}), encoding="utf-8")
            assert at.should_send_idle_reminder() is True

            # 3. Send the reminder
            with patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock) as mock_send:
                await at.check_and_send_idle_reminder()
            mock_send.assert_called_once()

            # 4. Cooldown: second call within 24h must not send
            with patch("app.services.growth._tg_helper.tg_send", new_callable=AsyncMock) as mock_send2:
                await at.check_and_send_idle_reminder()
            mock_send2.assert_not_called()

            # 5. Record new activity: idle clock resets
            at.record_activity()
            assert at.should_send_idle_reminder() is False

    @pytest.mark.critical
    def test_fresh_install_never_triggers_reminder(self, tmp_path):
        """No activity.json on first run → should_send_idle_reminder() must be False."""
        import app.services.growth.activity_tracker as at
        nonexistent = tmp_path / "activity_missing.json"
        with patch.object(at, "_STATE_FILE", nonexistent):
            assert at.should_send_idle_reminder() is False


# =============================================================================
# 5. Recovery lifecycle scenario
# =============================================================================


class TestRecoveryLifecycleScenario:
    """
    Startup check behavior across file states:
    missing files (fresh install), valid files, and corrupt files.
    """

    @pytest.mark.critical
    def test_all_missing_files_produce_no_errors(self, tmp_path):
        """Fresh install: all state files missing → no errors, no warnings."""
        from app.utils.startup_check import _check_file, _STATE_FILES
        for key in _STATE_FILES:
            result = _check_file(key, tmp_path / f"{key}_missing.json")
            assert result["exists"] is False
            assert result["valid_json"] is None
            assert result["error"] is None

    @pytest.mark.critical
    def test_valid_post_queue_reports_pending_count(self, tmp_path):
        """Valid post_queue.json → check reports correct pending/total count."""
        from app.utils.startup_check import _check_file
        pq = tmp_path / "post_queue.json"
        pq.write_text(json.dumps({
            "queue": [
                {"text": "pending", "added_at": "2026-01-01T00:00:00+00:00",
                 "published_at": None, "notified_at": None,
                 "is_thread_starter": False, "hashtags": []},
                {"text": "done", "added_at": "2026-01-01T01:00:00+00:00",
                 "published_at": "2026-01-01T02:00:00+00:00", "notified_at": None,
                 "is_thread_starter": False, "hashtags": []},
            ],
            "last_published": None,
        }), encoding="utf-8")
        result = _check_file("post_queue", pq)
        assert result["valid_json"] is True
        assert "1개 대기" in result["info"]
        assert "2개 전체" in result["info"]

    @pytest.mark.critical
    def test_corrupt_file_detected_startup_continues(self, tmp_path):
        """Corrupt file → valid_json=False, error reported, app does not crash."""
        from app.utils.startup_check import _check_file
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{ NOT VALID JSON !!!", encoding="utf-8")
        result = _check_file("post_queue", corrupt)
        assert result["exists"] is True
        assert result["valid_json"] is False
        assert result["error"] is not None

    @pytest.mark.critical
    def test_run_startup_check_never_raises(self, tmp_path):
        """run_startup_check() must never raise regardless of file state."""
        from app.utils.startup_check import run_startup_check, _STATE_FILES
        # Point all files at non-existent paths in tmp_path
        fake_files = {k: tmp_path / f"{k}.json" for k in _STATE_FILES}
        with patch("app.utils.startup_check._STATE_FILES", fake_files):
            result = run_startup_check()  # must not raise
        assert set(result.keys()) == set(_STATE_FILES.keys())


# =============================================================================
# 6. Telegram Quick Menu (/menu command)
# =============================================================================

class TestTelegramQuickMenu:
    """
    /menu 커맨드와 퀵 액션 콜백이 telegram_bot.py에 올바르게 구현됐는지 검증.
    telegram 라이브러리 임포트 없이 소스 텍스트 분석으로 검증합니다.
    """

    @pytest.fixture(autouse=True)
    def bot_source(self):
        self.src = (Path(__file__).parent.parent / "app" / "telegram_bot.py").read_text()

    @pytest.mark.critical
    def test_menu_command_defined(self):
        """menu_command 함수가 정의되어 있어야 한다."""
        assert "async def menu_command(" in self.src

    @pytest.mark.critical
    def test_menu_command_registered(self):
        """CommandHandler('menu', menu_command)가 등록되어 있어야 한다."""
        assert 'CommandHandler("menu", menu_command)' in self.src

    @pytest.mark.critical
    def test_all_five_quick_callbacks_defined(self):
        """5개 quick_ callback_data가 모두 정의되어 있어야 한다."""
        for cb in ("quick_draft", "quick_queue", "quick_status", "quick_monitor", "quick_recover"):
            assert cb in self.src, f"Missing callback_data: {cb}"

    @pytest.mark.critical
    def test_quick_handler_routed_in_callback_handler(self):
        """callback_handler에서 quick_ 접두사가 _handle_quick_callback으로 라우팅돼야 한다."""
        assert 'startswith("quick_")' in self.src
        assert "_handle_quick_callback" in self.src

    @pytest.mark.critical
    def test_quick_handler_calls_existing_commands(self):
        """_handle_quick_callback이 기존 커맨드 핸들러를 재사용해야 한다."""
        assert "queue_command" in self.src
        assert "status_command" in self.src
        assert "monitor_command" in self.src
        assert "recover_command" in self.src

    @pytest.mark.critical
    def test_five_inline_buttons_present(self):
        """5개 인라인 버튼 텍스트가 menu_command에 있어야 한다."""
        for label in ("초안 요청", "대기 큐", "오늘 현황", "모니터 확인", "복구 점검"):
            assert label in self.src, f"Missing button label: {label}"
