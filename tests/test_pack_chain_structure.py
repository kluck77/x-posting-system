"""
Phase 1.1 구조 강화 테스트
==========================
- source_pack 4개 신 필드 (historical_parallel / concept_translation / evidence_pack / closing_signal)
- angle_pack 5개 신 필드 (frame_type / story_spine / readability_risk / share_trigger / scan_pattern)
- grok_handoff 편집 카드 포맷 (<=1800, 5 고정 블록, URL 덤프 없음)
- compose 헬퍼 역호환
- Pack Chain 플래그 기본값 off (회귀)

외부 호출 없이 순수 구조 검증만 수행.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.source_pack import (
    SOURCE_PACK_KEYS,
    build_source_pack,
    validate_source_pack,
)
from app.services.angle_pack import (
    ANGLE_PACK_KEYS,
    _heuristic_angle_pack,
    _normalize_angle_pack,
    validate_angle_pack,
)
from app.services.grok_handoff import (
    format_handoff,
    compose_enriched_source,
    compose_pack_context,
)


# ─────────────────────────────────────────────────────────────
# 더미 Research / FactCheck / SourceItem / Input
# ─────────────────────────────────────────────────────────────

def _make_research():
    key_facts = [
        "Samsung Q1 operating profit hit 6.6 trillion won, up 931% YoY.",
        "Unlike the 2017 memory cycle, current HBM demand comes from AI accelerators.",
        '"We will focus on HBM3E for 2026," the CEO said.',
        "Korean memory makers now ship over 70% of global HBM.",
        "BOK held the base rate at 3.5% in April.",
    ]
    return SimpleNamespace(
        summary=(
            "Samsung posted Q1 operating profit of 6.6 trillion won. "
            "Unlike the 2017 memory cycle, the current wave is AI-driven. "
            "The CEO said HBM3E will be the 2026 focus. "
            "BOK held rates steady."
        ),
        key_facts=key_facts,
        fact_labels={
            key_facts[0]: "confirms_common_narrative",
            key_facts[1]: "challenges_assumption",
            key_facts[3]: "missing_context",
        },
        interpretation_gaps=[
            "Western outlets are missing the HBM3E qualification question.",
            "Bloomberg framing omits the foundry loss context.",
        ],
        sources=["https://example.com/samsung-q1"],
    )


def _make_factcheck():
    return SimpleNamespace(
        verified=True,
        confidence="high",
        corrections=["Unclear if NVIDIA has qualified Samsung HBM3E yet."],
        interpretation_opportunity="Qualification status is the real signal.",
        marketability_signal="HBM3E qualification window expected next month.",
        sources=["https://example.com/samsung-q1"],
    )


def _make_source_item():
    return SimpleNamespace(
        source_type="news",
        url="https://example.com/samsung-q1",
        title="Samsung Q1 earnings",
    )


def _make_input_data():
    return SimpleNamespace(
        source_type="news",
        url="https://example.com/samsung-q1",
        title="Samsung Q1 earnings",
    )


def _make_source_pack():
    return build_source_pack(
        source_item=_make_source_item(),
        input_data=_make_input_data(),
        research=_make_research(),
        factcheck=_make_factcheck(),
    )


# ─────────────────────────────────────────────────────────────
# source_pack Phase 1.1
# ─────────────────────────────────────────────────────────────

def test_source_pack_has_structure_keys():
    pack = _make_source_pack()
    for k in ("historical_parallel", "concept_translation", "evidence_pack", "closing_signal"):
        assert k in pack, f"missing key: {k}"
        assert k in SOURCE_PACK_KEYS
    validate_source_pack(pack)


def test_source_pack_evidence_pack_cap():
    pack = _make_source_pack()
    assert isinstance(pack["evidence_pack"], list)
    assert len(pack["evidence_pack"]) <= 5


def test_source_pack_evidence_item_length_cap():
    pack = _make_source_pack()
    for item in pack["evidence_pack"]:
        assert isinstance(item, str)
        assert len(item) <= 240


def test_source_pack_no_hallucination_evidence_pack():
    """evidence_pack 은 research / factcheck 원문에서만 뽑혀야 한다."""
    research = _make_research()
    factcheck = _make_factcheck()
    pack = build_source_pack(
        source_item=_make_source_item(),
        input_data=_make_input_data(),
        research=research,
        factcheck=factcheck,
    )
    haystack_parts = list(research.key_facts) + [research.summary] + list(research.interpretation_gaps)
    haystack_parts += list(factcheck.corrections) + [factcheck.interpretation_opportunity]
    haystack = " ".join(str(x) for x in haystack_parts)
    for e in pack["evidence_pack"]:
        assert e in haystack, f"evidence item not grounded: {e}"


def test_source_pack_historical_parallel_matches_hint():
    """'Unlike the 2017 memory cycle' 문장이 historical_parallel 로 픽되는지."""
    pack = _make_source_pack()
    hp = pack["historical_parallel"]
    assert hp  # non-empty
    # 힌트 단어 중 하나가 포함되어야 함
    assert any(t in hp.lower() for t in ("unlike", "2017", "previously", "as in", "vs", "compared to"))


def test_source_pack_concept_translation_prefers_missing_context():
    pack = _make_source_pack()
    ct = pack["concept_translation"]
    assert "70%" in ct or "HBM" in ct  # missing_context 라벨 팩트와 연결


def test_source_pack_empty_inputs_defaults():
    """research / factcheck 가 None 이어도 안전하게 동작."""
    pack = build_source_pack(
        source_item=_make_source_item(),
        input_data=_make_input_data(),
        research=None,
        factcheck=None,
    )
    assert pack["historical_parallel"] == ""
    assert pack["concept_translation"] == ""
    assert pack["evidence_pack"] == []
    assert pack["closing_signal"] == ""
    validate_source_pack(pack)


def test_validate_source_pack_rejects_oversized_evidence_item():
    pack = _make_source_pack()
    pack["evidence_pack"] = ["x" * 300]
    with pytest.raises(ValueError):
        validate_source_pack(pack)


# ─────────────────────────────────────────────────────────────
# angle_pack Phase 1.1
# ─────────────────────────────────────────────────────────────

def test_angle_pack_has_structure_keys():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    for k in ("frame_type", "story_spine", "readability_risk", "share_trigger", "scan_pattern"):
        assert k in ap
        assert k in ANGLE_PACK_KEYS
    validate_angle_pack(ap)


def test_angle_pack_frame_type_enum():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    assert ap["frame_type"] in ("parallel", "contrast", "hidden_signal", "underreported_angle")


def test_angle_pack_frame_type_parallel_when_historical_present():
    sp = _make_source_pack()
    # historical_parallel 이 비어있지 않으면 frame_type 은 parallel
    if sp["historical_parallel"]:
        ap = _heuristic_angle_pack(sp)
        assert ap["frame_type"] == "parallel"


def test_angle_pack_readability_risk_enum():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    assert ap["readability_risk"] in ("low", "medium", "high")


def test_angle_pack_story_spine_default_non_empty():
    sp = {
        "confirmed_facts": [], "conflicts_or_uncertainty": [], "korea_angle": [],
        "global_angle": [], "watch_next": [], "source_quality": {},
        "historical_parallel": "", "concept_translation": "",
        "evidence_pack": [], "closing_signal": "",
    }
    ap = _heuristic_angle_pack(sp)
    assert isinstance(ap["story_spine"], list)
    assert len(ap["story_spine"]) >= 3
    assert len(ap["story_spine"]) == len(set(ap["story_spine"]))


def test_angle_pack_normalize_rejects_bad_enum():
    sp = _make_source_pack()
    raw = {
        "core_tension": "tension",
        "angle_options": [{"angle": "A", "hook": "h", "risk": "low"}],
        "winner_angle": {"angle": "A", "score": 80, "reason": "r"},
        "series_type": "analysis",
        "follow_reason": "f",
        "share_reason": "s",
        "frame_type": "BOGUS_VALUE",
        "story_spine": ["hook", "explain", "evidence"],
        "readability_risk": "WRONG",
        "share_trigger": "t",
        "scan_pattern": "sp",
    }
    ap = _normalize_angle_pack(raw, sp)
    assert ap["frame_type"] in ("parallel", "contrast", "hidden_signal", "underreported_angle")
    assert ap["readability_risk"] in ("low", "medium", "high")


def test_angle_pack_normalize_story_spine_filters_bad_phases():
    sp = _make_source_pack()
    raw = {
        "core_tension": "tension",
        "angle_options": [{"angle": "A", "hook": "h", "risk": "low"}],
        "winner_angle": {"angle": "A", "score": 80, "reason": "r"},
        "series_type": "analysis",
        "follow_reason": "f",
        "share_reason": "s",
        "frame_type": "contrast",
        "story_spine": ["hook", "ILLEGAL", "evidence", "hook"],  # dup + illegal
        "readability_risk": "low",
        "share_trigger": "t",
        "scan_pattern": "sp",
    }
    ap = _normalize_angle_pack(raw, sp)
    assert "ILLEGAL" not in ap["story_spine"]
    assert len(ap["story_spine"]) == len(set(ap["story_spine"]))


# ─────────────────────────────────────────────────────────────
# grok_handoff Phase 1.1 (편집 카드)
# ─────────────────────────────────────────────────────────────

def test_grok_handoff_length_cap():
    from app.services.grok_handoff import _HANDOFF_HARD_MAX
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    body = "X" * 3000
    out = format_handoff(sp, ap, body)
    # grok-handoff-signals phase 에서 편집 목표 1줄 + weakness/tone 블록
    # 추가로 하드 상한이 _HANDOFF_HARD_MAX (2800) 으로 상향됨.
    assert len(out) <= _HANDOFF_HARD_MAX


def test_grok_handoff_has_5_required_blocks():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "Sample final body.")
    for title in (
        "## 원문 초안",
        "## 이 글의 핵심 각도",
        "## 절대 바꾸지 말 것",
        "## 바꿔도 되는 것",
        "## 최종 출력 규칙",
    ):
        assert title in out, f"required block missing: {title}"


def test_grok_handoff_no_url_dump():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "body")
    assert "http://" not in out
    assert "https://" not in out


def test_grok_handoff_no_legacy_verbose_headers():
    sp = _make_source_pack()
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "body")
    for banned in (
        "GROK HANDOFF — angle-aware edit pass",
        "### Edit instructions",
        "### Global angle (what English coverage misses)",
    ):
        assert banned not in out, f"legacy verbose block leaked: {banned}"


def test_grok_handoff_optional_concept_translation():
    sp = _make_source_pack()
    sp["concept_translation"] = "HBM3E is the AI-era DRAM tollgate Nvidia must pay."
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "body")
    assert "## 어려운 개념 한 줄 번역" in out


def test_grok_handoff_optional_evidence_block():
    sp = _make_source_pack()
    sp["evidence_pack"] = [
        "Samsung Q1 operating profit 6.6 trillion won (up 931%)",
        "HBM share: >70% from Korean makers",
    ]
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "body")
    assert "## 핵심 근거 2~3개" in out


def test_grok_handoff_drops_optional_blocks_when_oversized():
    """본문이 너무 길면 선택 블록부터 잘려야 한다."""
    from app.services.grok_handoff import _HANDOFF_HARD_MAX
    sp = _make_source_pack()
    sp["concept_translation"] = "something"
    sp["evidence_pack"] = ["alpha", "beta", "gamma"]
    ap = _heuristic_angle_pack(sp)
    out = format_handoff(sp, ap, "X" * 1800)
    assert len(out) <= _HANDOFF_HARD_MAX
    # 5 고정 블록은 반드시 남아야 한다
    for title in (
        "## 원문 초안",
        "## 이 글의 핵심 각도",
        "## 절대 바꾸지 말 것",
        "## 바꿔도 되는 것",
        "## 최종 출력 규칙",
    ):
        assert title in out


# ─────────────────────────────────────────────────────────────
# compose_* 헬퍼 회귀
# ─────────────────────────────────────────────────────────────

def test_compose_enriched_source_includes_new_fields():
    sp = _make_source_pack()
    sp["concept_translation"] = "HBM3E is the AI-era DRAM tollgate."
    out = compose_enriched_source("orig text", sp, {"angle": "demo"})
    assert "orig text" in out
    assert "=== ORIGINAL SOURCE ===" in out
    assert "Concept in one line" in out


def test_compose_pack_context_backward_compatible_with_phase1_dict():
    """Phase 1 스키마 (새 키 없음) 를 받아도 터지지 않아야 한다."""
    legacy_sp = {
        "confirmed_facts": ["a"],
        "conflicts_or_uncertainty": [],
        "korea_angle": [],
        "global_angle": [],
        "watch_next": [],
        "source_quality": {},
    }
    out = compose_pack_context(legacy_sp, {"angle": "w", "score": 70, "reason": "r"})
    assert "PACK CONTEXT" in out
    assert "Winner Angle" in out


# ─────────────────────────────────────────────────────────────
# Pack Chain 플래그 회귀
# ─────────────────────────────────────────────────────────────

def test_pack_chain_flag_default_off():
    from app.config import Settings
    default_val = Settings.model_fields["pack_chain_enabled"].default
    assert default_val is False
