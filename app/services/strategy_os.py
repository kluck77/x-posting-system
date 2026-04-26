"""
Strategy OS 서비스 (Phase A — Read-only)
==========================================
콘텐츠 차별화 자산(positioning, pillars, series, hooks, rt triggers 등)을
시스템 안에 고정시키고 대시보드에서 읽을 수 있게 한다.

Phase A 범위:
- runtime_x/strategy/strategy_os.json 단일 파일을 소스로 사용
- 파일이 없으면 default seed 로 자동 생성
- 어떤 오류에서도 default 반환 — 대시보드 보호
- default fallback 책임은 이 모듈에만 존재 (호출부는 load_strategy_os 만 사용)

이후 Phase 에서 수정 UI / pack chain 연결 / 히스토리 등을 붙일 예정.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

STRATEGY_DIR = PROJECT_ROOT / "runtime_x" / "strategy"
STRATEGY_FILE = STRATEGY_DIR / "strategy_os.json"
HISTORY_DIR = STRATEGY_DIR / "history"
HISTORY_FILE = HISTORY_DIR / "strategy_os.prev.json"

# Phase B 검증용 스키마 메타 — default_strategy_os() 와 한 몸으로 유지.
_LIST_FIELDS = (
    "content_pillars",
    "series",
    "hook_library",
    "rt_trigger_rules",
    "banned_style",
    "good_examples",
    "bad_examples",
    "weekly_review_checklist",
)
_POSITIONING_FIELDS = {"one_liner", "do_not_do", "lenses"}
_ALLOWED_TOP_KEYS = {"positioning", *_LIST_FIELDS}


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
    # 호출 시점에 모듈 전역을 읽는다 — 테스트에서 monkeypatch 가능.
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
    Strategy OS 를 읽어 반환한다.
    파일이 없으면 default seed 로 생성 후 읽는다.
    어떤 오류가 나도 default 반환 — 대시보드 로딩을 망치지 않는다.
    누락된 top-level 필드는 default 로 채워 스키마 호환성을 유지한다.
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


# ── Phase B: validation + save + backup ──────────────────────────────────────


class StrategyOSValidationError(ValueError):
    """검증 실패. .field 에 어느 경로가 문제인지 저장."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def validate_strategy_os(payload: Any) -> dict[str, Any]:
    """
    payload 를 검증하고 default 와 병합된 최종 dict 을 반환한다.
    거절 조건은 StrategyOSValidationError 로 raise (400 매핑).

    거절:
      - 루트가 dict 아님
      - 모르는 top-level 키 포함 (오타/외부주입 차단, 데이터 유실 차단)
      - positioning 이 dict 아님 / one_liner 가 str 아님 /
        do_not_do·lenses 가 list 아님
      - 리스트 필드가 list 아님
      - JSON 직렬화 불가능한 값 포함
    """
    if not isinstance(payload, dict):
        raise StrategyOSValidationError(
            "root must be a JSON object", field="<root>"
        )

    unknown = sorted(set(payload.keys()) - _ALLOWED_TOP_KEYS)
    if unknown:
        raise StrategyOSValidationError(
            f"unknown top-level keys: {unknown}", field=unknown[0]
        )

    if "positioning" in payload:
        pos = payload["positioning"]
        if not isinstance(pos, dict):
            raise StrategyOSValidationError(
                "positioning must be an object", field="positioning"
            )
        unknown_pos = sorted(set(pos.keys()) - _POSITIONING_FIELDS)
        if unknown_pos:
            raise StrategyOSValidationError(
                f"unknown positioning keys: {unknown_pos}",
                field=f"positioning.{unknown_pos[0]}",
            )
        if "one_liner" in pos and not isinstance(pos["one_liner"], str):
            raise StrategyOSValidationError(
                "positioning.one_liner must be a string",
                field="positioning.one_liner",
            )
        for sub in ("do_not_do", "lenses"):
            if sub in pos and not isinstance(pos[sub], list):
                raise StrategyOSValidationError(
                    f"positioning.{sub} must be a list",
                    field=f"positioning.{sub}",
                )

    for key in _LIST_FIELDS:
        if key in payload and not isinstance(payload[key], list):
            raise StrategyOSValidationError(
                f"{key} must be a list", field=key
            )

    merged = default_strategy_os()
    if "positioning" in payload:
        merged["positioning"] = {**merged["positioning"], **payload["positioning"]}
    for key in _LIST_FIELDS:
        if key in payload:
            merged[key] = payload[key]

    try:
        json.dumps(merged, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise StrategyOSValidationError(
            f"payload not JSON-serializable: {e}", field="<root>"
        )

    return merged


def backup_previous_strategy_os(
    src: Path | None = None, dst: Path | None = None
) -> bool:
    """
    현재 strategy_os.json 이 있으면 history 로 덮어쓰기 복사한다.
    1 세대 고정 (같은 파일 매 저장마다 덮어씀).
    기존 파일 없음 = no-op, False 반환.
    실패 시 예외 전파 — 호출부(엔드포인트)에서 500 매핑.
    """
    source = src if src is not None else STRATEGY_FILE
    target = dst if dst is not None else HISTORY_FILE
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def save_strategy_os(merged: dict[str, Any], path: Path | None = None) -> Path:
    """
    merged 를 atomic 하게 파일로 쓴다 (tempfile + os.replace).
    호출 전에 validate_strategy_os 로 정규화한 결과를 넘겨야 한다.
    """
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(merged, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".strategy_os.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target
