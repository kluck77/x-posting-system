"""
Strategy OS (Phase A + B) 테스트
=================================
Phase A:
- default 스키마 완전성
- 파일 없을 때 자동 생성
- 부분 데이터 병합
- 손상 JSON 에 대한 graceful fallback
- FastAPI GET /control/strategy-os + corrupt 내성

Phase B:
- validate_strategy_os: 정상 / 부분 / 루트 비객체 / 미지 키 / 타입 오류 거절
- save_strategy_os: atomic roundtrip
- backup_previous_strategy_os: 히스토리 생성 / 1 세대 유지 / 소스 부재 no-op
- FastAPI POST /control/strategy-os: 저장 + 백업 + 400 reject + 손상 파일 복구
"""
import json

from fastapi.testclient import TestClient

import pytest

from app.services import strategy_os
from app.services.strategy_os import (
    StrategyOSValidationError,
    backup_previous_strategy_os,
    default_strategy_os,
    ensure_strategy_os,
    load_strategy_os,
    save_strategy_os,
    validate_strategy_os,
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
    assert set(default_strategy_os().keys()) == REQUIRED_TOP_KEYS


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
    result = ensure_strategy_os(target)
    assert result == target
    assert target.exists()
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == REQUIRED_TOP_KEYS


def test_ensure_does_not_overwrite_existing(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text(
        json.dumps({"positioning": {"one_liner": "custom"}}), encoding="utf-8"
    )
    ensure_strategy_os(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "positioning": {"one_liner": "custom"}
    }


def test_load_creates_and_returns_default_when_missing(tmp_path):
    target = tmp_path / "strategy_os.json"
    data = load_strategy_os(target)
    assert target.exists()
    assert data == default_strategy_os()


def test_load_merges_partial_file_with_default(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text(
        json.dumps({
            "positioning": {"one_liner": "explainer for non-Koreans"},
            "hook_library": ["hook A", "hook B"],
        }),
        encoding="utf-8",
    )
    data = load_strategy_os(target)
    assert data["positioning"] == {"one_liner": "explainer for non-Koreans"}
    assert data["hook_library"] == ["hook A", "hook B"]
    assert data["content_pillars"] == []
    assert data["weekly_review_checklist"] == []


def test_load_returns_default_on_corrupt_json(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text("{this is not valid json", encoding="utf-8")
    assert load_strategy_os(target) == default_strategy_os()


def test_load_returns_default_when_root_not_object(tmp_path):
    target = tmp_path / "strategy_os.json"
    target.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert load_strategy_os(target) == default_strategy_os()


def test_endpoint_returns_schema(tmp_path, monkeypatch):
    """FastAPI 엔드포인트가 200 + 전체 스키마를 반환한다."""
    target = tmp_path / "strategy_os.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)

    from app.api.admin import app

    with TestClient(app) as client:
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

    with TestClient(app) as client:
        res = client.get("/control/strategy-os")
    assert res.status_code == 200
    assert res.json() == default_strategy_os()


# ── Phase B: validation / save / backup / POST endpoint ─────────────────────


def test_validate_accepts_full_valid_payload():
    payload = {
        "positioning": {
            "one_liner": "explainer for non-Koreans",
            "do_not_do": ["no propaganda"],
            "lenses": ["policy", "economy"],
        },
        "content_pillars": ["pillar1"],
        "series": [{"name": "weekly-explainer"}],
        "hook_library": ["hookA"],
        "rt_trigger_rules": ["rule1"],
        "banned_style": ["it's worth noting"],
        "good_examples": ["good1"],
        "bad_examples": ["bad1"],
        "weekly_review_checklist": ["item1"],
    }
    merged = validate_strategy_os(payload)
    assert merged["positioning"]["one_liner"] == "explainer for non-Koreans"
    assert merged["hook_library"] == ["hookA"]
    assert set(merged.keys()) == REQUIRED_TOP_KEYS


def test_validate_merges_partial_with_default():
    merged = validate_strategy_os({"hook_library": ["only hook"]})
    assert merged["hook_library"] == ["only hook"]
    assert merged["positioning"] == default_strategy_os()["positioning"]
    assert merged["content_pillars"] == []
    assert merged["weekly_review_checklist"] == []


def test_validate_rejects_non_object_root():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os(["a", "b"])
    assert exc.value.field == "<root>"


def test_validate_rejects_unknown_top_level_key():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os({"bogus_key": 1})
    assert "bogus_key" in str(exc.value)
    assert exc.value.field == "bogus_key"


def test_validate_rejects_unknown_positioning_key():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os({"positioning": {"wat": "x"}})
    assert exc.value.field == "positioning.wat"


def test_validate_rejects_wrong_one_liner_type():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os({"positioning": {"one_liner": 123}})
    assert exc.value.field == "positioning.one_liner"


def test_validate_rejects_wrong_list_field_type():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os({"hook_library": "not a list"})
    assert exc.value.field == "hook_library"


def test_validate_rejects_wrong_positioning_subfield_type():
    with pytest.raises(StrategyOSValidationError) as exc:
        validate_strategy_os({"positioning": {"lenses": "not a list"}})
    assert exc.value.field == "positioning.lenses"


def test_save_roundtrip(tmp_path, monkeypatch):
    target = tmp_path / "strategy_os.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)
    merged = validate_strategy_os({"hook_library": ["H1", "H2"]})
    saved_path = save_strategy_os(merged)
    assert saved_path == target
    roundtrip = load_strategy_os()
    assert roundtrip == merged


def test_backup_previous_creates_history(tmp_path, monkeypatch):
    src = tmp_path / "strategy_os.json"
    dst = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", src)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", dst)
    src.write_text(json.dumps({"positioning": {"one_liner": "v1"}}), encoding="utf-8")
    assert backup_previous_strategy_os() is True
    assert dst.exists()
    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "positioning": {"one_liner": "v1"}
    }


def test_backup_overwrites_single_generation(tmp_path, monkeypatch):
    src = tmp_path / "strategy_os.json"
    dst = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", src)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", dst)
    src.write_text(json.dumps({"positioning": {"one_liner": "gen1"}}), encoding="utf-8")
    backup_previous_strategy_os()
    src.write_text(json.dumps({"positioning": {"one_liner": "gen2"}}), encoding="utf-8")
    backup_previous_strategy_os()
    # history 파일은 딱 1개 + 최신 이전 상태(gen2) 를 보관
    assert dst.exists()
    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "positioning": {"one_liner": "gen2"}
    }
    assert list(dst.parent.iterdir()) == [dst]


def test_backup_noop_when_source_missing(tmp_path, monkeypatch):
    src = tmp_path / "strategy_os.json"
    dst = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", src)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", dst)
    assert backup_previous_strategy_os() is False
    assert not dst.exists()


def test_post_endpoint_saves_and_roundtrips(tmp_path, monkeypatch):
    target = tmp_path / "strategy_os.json"
    history = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", history)

    from app.api.admin import app

    payload = {"positioning": {"one_liner": "v1"}, "hook_library": ["h1"]}
    with TestClient(app) as client:
        # 첫 GET 으로 seed 확보 → 백업이 실제로 발생하도록
        seed = client.get("/control/strategy-os")
        assert seed.status_code == 200

        res = client.post("/control/strategy-os", json=payload)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True
        assert body["backed_up"] is True
        assert body["data"]["positioning"]["one_liner"] == "v1"
        assert body["data"]["hook_library"] == ["h1"]
        assert set(body["data"].keys()) == REQUIRED_TOP_KEYS

        # GET roundtrip
        got = client.get("/control/strategy-os").json()
        assert got["positioning"]["one_liner"] == "v1"
        assert got["hook_library"] == ["h1"]

    assert history.exists()


def test_post_endpoint_rejects_unknown_key(tmp_path, monkeypatch):
    target = tmp_path / "strategy_os.json"
    history = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", history)

    from app.api.admin import app

    with TestClient(app) as client:
        res = client.post("/control/strategy-os", json={"bogus_key": 1})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["ok"] is False
    assert detail["field"] == "bogus_key"


def test_post_endpoint_rejects_wrong_type(tmp_path, monkeypatch):
    target = tmp_path / "strategy_os.json"
    history = tmp_path / "history" / "strategy_os.prev.json"
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", history)

    from app.api.admin import app

    with TestClient(app) as client:
        res = client.post(
            "/control/strategy-os",
            json={"positioning": {"one_liner": 123}},
        )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["field"] == "positioning.one_liner"


def test_post_endpoint_survives_corrupt_existing_file(tmp_path, monkeypatch):
    """기존 파일이 깨져있어도 POST 저장은 성공해야 한다 (복구 경로)."""
    target = tmp_path / "strategy_os.json"
    history = tmp_path / "history" / "strategy_os.prev.json"
    target.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(strategy_os, "STRATEGY_FILE", target)
    monkeypatch.setattr(strategy_os, "HISTORY_FILE", history)

    from app.api.admin import app

    with TestClient(app) as client:
        res = client.post(
            "/control/strategy-os",
            json={"positioning": {"one_liner": "recovered"}},
        )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    # 손상된 이전 파일은 그대로 history 에 보존됨 (무조건 복사)
    assert history.exists()
    assert history.read_text(encoding="utf-8") == "not json"
    # 현재 파일은 유효한 JSON 으로 교체됨
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["positioning"]["one_liner"] == "recovered"
