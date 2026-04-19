"""
Strategy OS (Phase A) 테스트
=============================
- default 스키마 완전성
- 파일 없을 때 자동 생성
- 부분 데이터 병합
- 손상된 JSON 에 대한 graceful fallback
- FastAPI /control/strategy-os 엔드포인트 응답
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import strategy_os
from app.services.strategy_os import (
    default_strategy_os,
    ensure_strategy_os,
    load_strategy_os,
)


REQUIRED_TOP_KEYS = {
    "positioning",
    "content_pillars",
    "series",
    "hook_library",
    "rt_trigger_rules",
    "banned_style",
    "good_examples",
    "bad_examples",
    "weekly_review_checklist",
}

POSITIONING_KEYS = {"one_liner", "do_not_do", "lenses"}


def test_default_has_required_top_level_keys():
    data = default_strategy_os()
    assert set(data.keys()) == REQUIRED_TOP_KEYS


def test_default_positioning_shape():
    p = default_strategy_os()["positioning"]
    assert set(p.keys()) == POSITIONING_KEYS
    assert p["one_liner"] == ""
    assert p["do_not_do"] == []
    assert p["lenses"] == []


def test_default_lists_are_empty():
    data = default_strategy_os()
    for key in REQUIRED_TOP_KEYS - {"positioning"}:
        assert data[key] == [], f"{key} should default to []"


def test_ensure_creates_file_when_missing(tmp_path):
    target = tmp_path / "strategy" / "strategy_os.json"
    assert not target.exists()
    result_path = ensure_strategy_os(target)
    assert result_path == target
    assert target.exists()
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == REQUIRED_TOP_KEYS


def test_ensure_does_not_overwrite_existing(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text(json.dumps({"positioning": {"one_liner": "custom"}}), encoding="utf-8")
    ensure_strategy_os(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "positioning": {"one_liner": "custom"}
    }


def test_load_creates_and_returns_default_when_missing(tmp_path):
    target = tmp_path / "strategy_os.json"
    data = load_strategy_os(target)
    assert target.exists()
    assert set(data.keys()) == REQUIRED_TOP_KEYS
    assert data == default_strategy_os()


def test_load_merges_partial_file_with_default(tmp_path):
    target = tmp_path / "strategy_os.json"
    partial = {
        "positioning": {"one_liner": "explainer for non-Koreans"},
        "hook_library": ["hook A", "hook B"],
    }
    target.write_text(json.dumps(partial), encoding="utf-8")
    data = load_strategy_os(target)
    assert data["positioning"] == {"one_liner": "explainer for non-Koreans"}
    assert data["hook_library"] == ["hook A", "hook B"]
    assert data["content_pillars"] == []
    assert data["weekly_review_checklist"] == []


def test_load_returns_default_on_corrupt_json(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text("{this is not valid json", encoding="utf-8")
    data = load_strategy_os(target)
    assert data == default_strategy_os()


def test_load_returns_default_when_root_not_object(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    data = load_strategy_os(target)
    assert data == default_strategy_os()


def test_endpoint_returns_schema(tmp_path, monkeypatch):
    """FastAPI 엔드포인트가 200 + 전체 스키마를 반환한다."""
    target = tmp_path / "strategy_os.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)

    # admin.py 는 이미 import 되어 app 이 만들어져 있을 수 있으므로
    # 여기선 라우터가 load_strategy_os() 를 호출할 때 monkeypatch 된 경로를 쓰도록 함.
    from app.api.admin import app

    client = TestClient(app)
    res = client.get("/control/strategy-os")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == REQUIRED_TOP_KEYS
    assert set(body["positioning"].keys()) == POSITIONING_KEYS


def test_endpoint_survives_corrupt_file(tmp_path, monkeypatch):
    """JSON 이 깨져있어도 엔드포인트는 200 + default 반환 (대시보드 보호)."""
    target = tmp_path / "strategy_os.json"
    target.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)

    from app.api.admin import app

    client = TestClient(app)
    res = client.get("/control/strategy-os")
    assert res.status_code == 200
    assert res.json() == default_strategy_os()
