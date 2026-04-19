"""
Strategy OS 서비스 (Phase A — Read-only)
==========================================
콘텐츠 차별화 자산(positioning, pillars, series, hooks, rt triggers 등)을
시스템 안에 고정시키고 대시보드에서 읽을 수 있게 한다.

Phase A 범위:
- runtime_x/strategy/strategy_os.json 단일 파일을 소스로 사용
- 파일이 없으면 default seed 로 자동 생성
- 어떤 오류에서도 default 반환 (대시보드 보호)

이후 Phase 에서 수정 UI / pack chain 연결 / 히스토리 등을 붙일 예정.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

STRATEGY_DIR = PROJECT_ROOT / "runtime_x" / "strategy"
STRATEGY_FILE = STRATEGY_DIR / "strategy_os.json"


def default_strategy_os() -> dict[str, Any]:
    """Phase A default seed. 빈 구조만 제공 — 운영자가 이후 채움."""
    return {
        "positioning": {
            "one_liner": "",
            "do_not_do": [],
            "lenses": [],
        },
        "content_pillars": [],
        "series": [],
        "hook_library": [],
        "rt_trigger_rules": [],
        "banned_style": [],
        "good_examples": [],
        "bad_examples": [],
        "weekly_review_checklist": [],
    }


def _resolve_path(path: Path | None) -> Path:
    # 호출 시점에 모듈 전역을 읽는다 — 테스트에서 monkeypatch 가능하도록.
    return path if path is not None else STRATEGY_FILE


def ensure_strategy_os(path: Path | None = None) -> Path:
    """파일이 없으면 default seed 로 생성. 있으면 경로만 반환."""
    target = _resolve_path(path)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(default_strategy_os(), ensure_ascii=False, indent=2)
        target.write_text(payload, encoding="utf-8")
        logger.info(f"[StrategyOS] seed 생성: {target}")
    return target


def load_strategy_os(path: Path | None = None) -> dict[str, Any]:
    """
    Strategy OS 를 읽어서 반환한다.
    파일이 없으면 default seed 로 생성 후 읽는다.
    어떤 오류가 나도 default 반환 — 대시보드 로딩을 망치지 않는다.
    누락된 top-level 필드는 default 로 채워서 스키마 호환성을 유지한다.
    """
    target = _resolve_path(path)
    try:
        ensure_strategy_os(target)
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("strategy_os.json root must be an object")
        merged = default_strategy_os()
        for k, v in data.items():
            merged[k] = v
        return merged
    except Exception as e:
        logger.warning(f"[StrategyOS] load 실패, default 반환: {e}")
        return default_strategy_os()
