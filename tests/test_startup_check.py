"""
Tests for app/utils/startup_check.py
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.utils.startup_check import (
    _check_file,
    run_startup_check,
    format_recovery_summary,
    _STATE_FILES,
)


class TestCheckFile:
    """_check_file 단위 테스트."""

    def test_missing_file_returns_not_exists(self, tmp_path):
        result = _check_file("activity", tmp_path / "nonexistent.json")
        assert result["exists"] is False
        assert result["valid_json"] is None
        assert "파일 없음" in result["info"]
        assert result["error"] is None

    def test_valid_post_queue(self, tmp_path):
        p = tmp_path / "post_queue.json"
        p.write_text(json.dumps({
            "queue": [
                {"text": "post1", "added_at": "2026-01-01T00:00:00", "published_at": None,
                 "notified_at": None, "is_thread_starter": False, "hashtags": []},
                {"text": "post2", "added_at": "2026-01-01T01:00:00", "published_at": "2026-01-01T02:00:00",
                 "notified_at": None, "is_thread_starter": False, "hashtags": []},
            ],
            "last_published": None,
        }), encoding="utf-8")
        result = _check_file("post_queue", p)
        assert result["exists"] is True
        assert result["valid_json"] is True
        assert "1개 대기" in result["info"]
        assert "2개 전체" in result["info"]

    def test_valid_processed_replies(self, tmp_path):
        p = tmp_path / "processed_replies.json"
        p.write_text(json.dumps(["id1", "id2", "id3"]), encoding="utf-8")
        result = _check_file("processed_replies", p)
        assert result["valid_json"] is True
        assert "3개" in result["info"]

    def test_valid_activity(self, tmp_path):
        p = tmp_path / "activity.json"
        p.write_text(json.dumps({"last_activity_at": "2026-04-05T10:30:00+00:00"}), encoding="utf-8")
        result = _check_file("activity", p)
        assert result["valid_json"] is True
        assert "2026-04-05T10:30:00" in result["info"]

    def test_activity_no_entry(self, tmp_path):
        p = tmp_path / "activity.json"
        p.write_text(json.dumps({}), encoding="utf-8")
        result = _check_file("activity", p)
        assert result["valid_json"] is True
        assert "없음" in result["info"]

    def test_valid_monitor_state_running(self, tmp_path):
        p = tmp_path / "monitor_state.json"
        p.write_text(json.dumps({"reply_monitor_paused": False}), encoding="utf-8")
        result = _check_file("monitor_state", p)
        assert result["valid_json"] is True
        assert "실행 중" in result["info"]

    def test_valid_monitor_state_paused(self, tmp_path):
        p = tmp_path / "monitor_state.json"
        p.write_text(json.dumps({"reply_monitor_paused": True}), encoding="utf-8")
        result = _check_file("monitor_state", p)
        assert result["valid_json"] is True
        assert "정지" in result["info"]

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.json"
        p.write_text("{ not valid json {{", encoding="utf-8")
        result = _check_file("post_queue", p)
        assert result["exists"] is True
        assert result["valid_json"] is False
        assert result["error"] is not None
        assert "파싱 오류" in result["info"]


class TestRunStartupCheck:
    """run_startup_check 통합 테스트."""

    def test_returns_all_four_keys(self):
        fake_results = {k: {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}
                        for k in _STATE_FILES}
        with patch("app.utils.startup_check._check_file", return_value={"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}):
            results = run_startup_check()
        assert set(results.keys()) == set(_STATE_FILES.keys())

    def test_corrupt_file_triggers_warning(self, caplog):
        import logging
        corrupt_result = {"exists": True, "valid_json": False, "info": "JSON 파싱 오류", "error": "err"}
        ok_result = {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}

        def fake_check(label, path):
            if label == "post_queue":
                return corrupt_result
            return ok_result

        with patch("app.utils.startup_check._check_file", side_effect=fake_check):
            with caplog.at_level(logging.WARNING, logger="app.utils.startup_check"):
                run_startup_check()

        assert any("손상" in r.message for r in caplog.records)

    def test_all_missing_logs_info_not_warning(self, caplog):
        import logging
        ok_result = {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}
        with patch("app.utils.startup_check._check_file", return_value=ok_result):
            with caplog.at_level(logging.DEBUG, logger="app.utils.startup_check"):
                run_startup_check()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warnings


class TestFormatRecoverySummary:
    """format_recovery_summary 출력 형식 테스트."""

    def _make_results(self, **overrides):
        base = {k: {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}
                for k in _STATE_FILES}
        base.update(overrides)
        return base

    def test_all_missing_shows_white_circles(self):
        results = self._make_results()
        text = format_recovery_summary(results)
        assert "⚪" in text
        assert "❌" not in text

    def test_corrupt_shows_red_x(self):
        results = self._make_results(
            post_queue={"exists": True, "valid_json": False, "info": "JSON 파싱 오류", "error": "bad json"}
        )
        text = format_recovery_summary(results)
        assert "❌" in text
        assert "bad json" in text

    def test_valid_shows_check(self):
        results = self._make_results(
            activity={"exists": True, "valid_json": True, "info": "마지막 활동: 2026-04-05", "error": None}
        )
        text = format_recovery_summary(results)
        assert "✅" in text

    def test_includes_recovery_hint(self):
        results = self._make_results()
        text = format_recovery_summary(results)
        assert "data/" in text
