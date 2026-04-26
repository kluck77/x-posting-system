"""
Phase 3b angle_pack heuristic 영어 차단 테스트.

- 영어 conflicts[0] → winner_angle placeholder 로 대체
  + method="heuristic_en_blocked"
  + reason 에 "heuristic" + "fallback" 두 키워드 모두 포함 (Phase 1.5a 감지용)
- 한국어 conflicts[0] → 기존 120자 절단 angle 유지 + method="heuristic"
- build_angle_pack Gemini 성공 경로는 method="gemini"

build_angle_pack 의 Gemini 경로는 실 API 호출이라 테스트는 _normalize_angle_pack
출력을 흉내내거나 monkeypatch 로 _call_gemini_angle 대체.
"""
import asyncio

import pytest

from app.services.angle_pack import (
    _heuristic_angle_pack,
    build_angle_pack,
    validate_angle_pack,
)


# ─── 1. 영어 conflicts → placeholder 대체 ───────────────────────────

def test_english_conflicts_blocks_heuristic_angle():
    """영어 conflicts[0] → winner_angle placeholder 로 교체.
    method="heuristic_en_blocked", reason 에 heuristic + fallback 포함."""
    source_pack = {
        "confirmed_facts": [],
        "conflicts_or_uncertainty": [
            "This will be Japan's first ever warship export project, "
            "and the first ship is scheduled to be delivered to the Royal"
        ],
        "korea_angle": [],
        "global_angle": [],
        "watch_next": [],
        "closing_signal": "",
    }
    pack = _heuristic_angle_pack(source_pack)
    assert pack.get("method") == "heuristic_en_blocked"
    wa = pack["winner_angle"]
    assert "[angle 재작성 필요" in wa["angle"]
    assert wa["score"] == 0
    # Phase 1.5a detect_angle_pack_heuristic 매칭을 위해 두 키워드 둘 다 필수
    low = wa["reason"].lower()
    assert "heuristic" in low
    assert "fallback" in low
    # validator 통과
    validate_angle_pack(pack)


# ─── 2. 한국어 conflicts → 기존 120자 절단 (회귀) ────────────────────

def test_korean_conflicts_keeps_heuristic_behavior():
    """한국어 conflicts → 기존 동작 (120자 절단) 유지, method='heuristic'."""
    source_pack = {
        "confirmed_facts": [],
        "conflicts_or_uncertainty": [
            "한국은행의 6월 기준금리 결정이 원/달러 환율에 미칠 영향은 "
            "일시적인지 구조적인지 구분이 필요하다."
        ],
        "korea_angle": [],
        "global_angle": [],
        "watch_next": [],
        "closing_signal": "",
    }
    pack = _heuristic_angle_pack(source_pack)
    assert pack.get("method") == "heuristic"
    wa = pack["winner_angle"]
    # placeholder 아님 — 실제 한국어 conflicts 기반 angle
    assert "[angle 재작성 필요" not in wa["angle"]
    assert wa["score"] == 50
    assert "heuristic fallback (Gemini 미호출)" == wa["reason"]
    validate_angle_pack(pack)


# ─── 3. method 필드 세 값 검증 ───────────────────────────────────────

def test_method_values_three_paths(monkeypatch):
    """gemini / heuristic / heuristic_en_blocked 세 값이 정확히 세팅되는지."""

    # 경로 1: heuristic_en_blocked — 영어 conflicts
    pack_en = _heuristic_angle_pack({
        "confirmed_facts": [],
        "conflicts_or_uncertainty": ["Japan signed first warship export deal with Australia."],
        "korea_angle": [], "global_angle": [], "watch_next": [],
        "closing_signal": "",
    })
    assert pack_en["method"] == "heuristic_en_blocked"

    # 경로 2: heuristic — 한국어 conflicts
    pack_ko = _heuristic_angle_pack({
        "confirmed_facts": [],
        "conflicts_or_uncertainty": ["호주가 일본 함정을 선정한 배경은 불확실."],
        "korea_angle": [], "global_angle": [], "watch_next": [],
        "closing_signal": "",
    })
    assert pack_ko["method"] == "heuristic"

    # 경로 3: gemini — 호출 성공 흉내. has_gemini True + _call_gemini_angle
    # 을 가짜 JSON 반환으로 monkeypatch.
    from app.services import angle_pack as ap_mod

    fake_pack = {
        "core_tension": "한국 정책 긴장",
        "angle_options": [{"angle": "A", "hook": "H", "risk": "low"}],
        "winner_angle": {"angle": "A", "score": 80, "reason": "Gemini 가 선정한 각도"},
        "series_type": "analysis",
        "follow_reason": "F", "share_reason": "S",
        "frame_type": "contrast", "story_spine": ["hook","explain","evidence","contrast","close"],
        "readability_risk": "medium",
        "share_trigger": "T", "scan_pattern": "P",
    }

    async def _fake_call(source_pack):
        return fake_pack

    def _fake_normalize(raw, source_pack):
        return dict(raw)

    class _FakeSettings:
        has_gemini = True
        gemini_api_key = "test-key"

    monkeypatch.setattr(ap_mod, "_call_gemini_angle", _fake_call)
    monkeypatch.setattr(ap_mod, "_normalize_angle_pack", _fake_normalize)
    monkeypatch.setattr(ap_mod, "settings", _FakeSettings())

    result = asyncio.run(ap_mod.build_angle_pack({
        "confirmed_facts": ["f"],
        "conflicts_or_uncertainty": ["한국어 conflict"],
        "korea_angle": ["한국"], "global_angle": [], "watch_next": [],
        "closing_signal": "",
    }))
    assert result["method"] == "gemini"


# ─── 4. build_angle_pack Gemini 실패 시 heuristic method 세팅 ────────

def test_build_angle_pack_gemini_fail_falls_back_to_heuristic(monkeypatch):
    """Gemini 호출 예외 → _heuristic_angle_pack 호출 → method='heuristic' (또는 _en_blocked)."""
    from app.services import angle_pack as ap_mod

    async def _raise(source_pack):
        raise RuntimeError("gemini boom")

    class _FakeSettings:
        has_gemini = True
        gemini_api_key = "test-key"

    monkeypatch.setattr(ap_mod, "_call_gemini_angle", _raise)
    monkeypatch.setattr(ap_mod, "settings", _FakeSettings())

    result = asyncio.run(ap_mod.build_angle_pack({
        "confirmed_facts": [],
        "conflicts_or_uncertainty": ["한국어 conflict 문장."],
        "korea_angle": [], "global_angle": [], "watch_next": [],
        "closing_signal": "",
    }))
    assert result["method"] in ("heuristic", "heuristic_en_blocked")
