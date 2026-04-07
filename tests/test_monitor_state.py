"""
monitor_state.py 테스트.
멘션 모니터 on/off 토글 동작 검증.
파일 I/O는 tmp_path로 격리.
"""

import pytest
from unittest.mock import patch
from pathlib import Path


def _module(tmp_path: Path):
    """monitor_state 모듈을 tmp_path 기반 상태 파일로 격리해서 임포트."""
    import importlib
    import app.services.growth.monitor_state as ms
    # 상태 파일 경로를 tmp_path로 교체
    with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
        yield ms


class TestMonitorState:
    def test_default_is_not_paused(self, tmp_path):
        """기본 상태는 ON (not paused)."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
            assert ms.is_paused() is False

    def test_pause_sets_paused(self, tmp_path):
        """pause() 후 is_paused() == True."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
            ms.pause()
            assert ms.is_paused() is True

    def test_resume_clears_paused(self, tmp_path):
        """pause() → resume() 후 is_paused() == False."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
            ms.pause()
            ms.resume()
            assert ms.is_paused() is False

    def test_repeated_pause_is_idempotent(self, tmp_path):
        """pause()를 여러 번 호출해도 True 유지."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
            ms.pause()
            ms.pause()
            assert ms.is_paused() is True

    def test_repeated_resume_is_idempotent(self, tmp_path):
        """resume()을 여러 번 호출해도 False 유지."""
        import app.services.growth.monitor_state as ms
        with patch.object(ms, "_STATE_FILE", tmp_path / "monitor_state.json"):
            ms.pause()
            ms.resume()
            ms.resume()
            assert ms.is_paused() is False

    def test_state_persists_across_calls(self, tmp_path):
        """pause() 후 is_paused()가 파일에서 올바르게 읽힌다."""
        import app.services.growth.monitor_state as ms
        state_file = tmp_path / "monitor_state.json"
        with patch.object(ms, "_STATE_FILE", state_file):
            ms.pause()
            # 파일이 생성됐는지 확인
            assert state_file.exists()
            # 다시 읽어도 동일
            assert ms.is_paused() is True

    def test_missing_state_file_returns_not_paused(self, tmp_path):
        """상태 파일이 없으면 is_paused() == False (기본값)."""
        import app.services.growth.monitor_state as ms
        nonexistent = tmp_path / "nonexistent.json"
        with patch.object(ms, "_STATE_FILE", nonexistent):
            assert ms.is_paused() is False
