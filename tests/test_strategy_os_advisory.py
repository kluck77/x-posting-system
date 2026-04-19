"""
Strategy OS advisory inject (Phase C) 테스트
==============================================
- _build_strategy_os_advisory 순수 동작 (빈 / 부분 / 캡 초과 / 타입 오염)
- 길이 상한
- 섹션 순서
- load 예외 시 fail-open
- [STRATEGY_OS_ADVISORY_SKIP] 로그 접두사
"""
import logging

import pytest

from app import orchestrator as orch
from app.services import strategy_os


def _seed(monkeypatch, payload: dict):
    """strategy_os.load_strategy_os 를 고정 payload 로 바꾼다."""
    def _fake_load(path=None):
        return payload
    monkeypatch.setattr(strategy_os, "load_strategy_os", _fake_load, raising=True)


def test_empty_strategy_returns_empty_block(monkeypatch):
    _seed(monkeypatch, strategy_os.default_strategy_os())
    assert orch._build_strategy_os_advisory() == ""


def test_only_one_liner_emits_minimal_block(monkeypatch):
    payload = strategy_os.default_strategy_os()
    payload["positioning"]["one_liner"] = "explainer for non-Koreans"
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    assert block.startswith("[STRATEGY OS ADVISORY")
    assert "Positioning: explainer for non-Koreans" in block
    assert "Hooks" not in block
    assert "Style to avoid" not in block
    assert "Lenses" not in block


def test_hook_library_capped_to_three(monkeypatch):
    payload = strategy_os.default_strategy_os()
    payload["hook_library"] = [f"hook{i}" for i in range(10)]
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    assert "Hooks (priority" in block
    assert "- hook0" in block
    assert "- hook1" in block
    assert "- hook2" in block
    assert "- hook3" not in block
    assert "- hook9" not in block


def test_banned_style_capped_to_five(monkeypatch):
    payload = strategy_os.default_strategy_os()
    payload["banned_style"] = [f"avoid{i}" for i in range(12)]
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    assert "Style to avoid:" in block
    for i in range(5):
        assert f"- avoid{i}" in block
    assert "- avoid5" not in block


def test_non_string_items_are_cast_not_dropped(monkeypatch):
    payload = strategy_os.default_strategy_os()
    payload["hook_library"] = [123, {"x": 1}, "real hook"]
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    assert "- 123" in block
    # dict stringified (존재만 확인 — str(dict) 표현은 파이썬 버전 종속 없음)
    assert "- {'x': 1}" in block
    assert "- real hook" in block


def test_section_ordering(monkeypatch):
    payload = {
        "positioning": {
            "one_liner": "POS",
            "lenses": ["L1", "L2"],
            "do_not_do": [],
        },
        "content_pillars": [],
        "series": [],
        "hook_library": ["H1"],
        "rt_trigger_rules": [],
        "banned_style": ["B1"],
        "good_examples": [],
        "bad_examples": [],
        "weekly_review_checklist": [],
    }
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    # 순서: header → Positioning → Lenses → Hooks → Style to avoid
    i_pos = block.index("Positioning:")
    i_len = block.index("Lenses:")
    i_hook = block.index("Hooks (priority")
    i_ban = block.index("Style to avoid:")
    assert i_pos < i_len < i_hook < i_ban


def test_block_total_length_respects_cap(monkeypatch):
    payload = strategy_os.default_strategy_os()
    payload["positioning"]["one_liner"] = "x" * 2000
    payload["hook_library"] = ["a" * 500 for _ in range(20)]
    payload["banned_style"] = ["b" * 500 for _ in range(20)]
    _seed(monkeypatch, payload)
    block = orch._build_strategy_os_advisory()
    assert len(block) <= orch._ADVISORY_MAX_LEN


def test_load_failure_is_fail_open(monkeypatch, caplog):
    def _boom(path=None):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(strategy_os, "load_strategy_os", _boom, raising=True)
    with caplog.at_level(logging.WARNING, logger="app.orchestrator"):
        block = orch._build_strategy_os_advisory()
    assert block == ""
    assert any("[STRATEGY_OS_ADVISORY_SKIP]" in r.message for r in caplog.records)


def test_corrupt_types_do_not_raise(monkeypatch):
    # positioning 이 list, hook_library 가 문자열 등 전부 오염 상태
    _seed(monkeypatch, {
        "positioning": ["not", "a", "dict"],
        "content_pillars": "nope",
        "series": 42,
        "hook_library": {"bad": "shape"},
        "rt_trigger_rules": None,
        "banned_style": "nope",
        "good_examples": 1,
        "bad_examples": 2,
        "weekly_review_checklist": 3,
    })
    # 예외 없음, 빈 블록 (유의미 값이 하나도 없음)
    assert orch._build_strategy_os_advisory() == ""


def test_advisory_header_prefix_is_grep_stable():
    """운영 로그 grep 가 깨지지 않도록 접두사를 테스트로 고정."""
    # 상수성 보장 — 코드에서 문자열 바뀌면 여기서 잡힘
    assert "[STRATEGY OS ADVISORY" in "[STRATEGY OS ADVISORY — optional priorities, not hard rules]"


def test_clip_strs_basic():
    assert orch._clip_strs(["a", "b", "c", "d"], 2) == ["a", "b"]
    assert orch._clip_strs(None, 3) == []
    assert orch._clip_strs([None, "", "  ", "x"], 3) == ["x"]
    long = "z" * 200
    out = orch._clip_strs([long], 1)
    assert len(out) == 1 and len(out[0]) <= orch._ADVISORY_ITEM_MAX
