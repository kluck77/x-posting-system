"""
멘션 모니터 on/off 상태 관리.
data/monitor_state.json에 저장 (재시작 후에도 유지).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path("data/monitor_state.json")
_KEY = "reply_monitor_paused"


def _load() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"monitor_state 로드 실패: {e}")
        return {}


def _save(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"monitor_state 저장 실패: {e}")


def is_paused() -> bool:
    """멘션 모니터가 현재 정지 상태이면 True."""
    return bool(_load().get(_KEY, False))


def pause() -> None:
    """멘션 모니터 정지."""
    state = _load()
    state[_KEY] = True
    _save(state)


def resume() -> None:
    """멘션 모니터 재개."""
    state = _load()
    state[_KEY] = False
    _save(state)
