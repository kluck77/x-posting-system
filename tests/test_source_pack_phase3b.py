"""
Phase 3b source_pack 완화 테스트.

- factcheck.verified=False 인 sources 가 [unverified] 태그 붙여서 통과
- factcheck.verified=True 는 기존 동작 유지 (태그 없음)
- research.summary 영어 비율 > 0.4 → confirmed fallback + korea_angle 에 [en] 프리픽스
- 모든 경로 실패 → confirmed=[] 유지 (format_handoff 메타 지시문 안전망 회귀 확인)
"""
from types import SimpleNamespace

import pytest

from app.services.source_pack import (
    ENGLISH_RATIO_THRESHOLD_SOURCE,
    _english_ratio,
    build_source_pack,
)


# ─── fixture helpers ─────────────────────────────────────────────────────

def _si(url: str = "https://example.com/a", title: str = "t", source_type: str = "manual"):
    """SourceItem / SourceItemCreate duck-typed stub."""
    return SimpleNamespace(url=url, title=title, source_type=source_type)


def _research(summary: str = "", key_facts=None, fact_labels=None, interpretation_gaps=None, sources=None):
    return SimpleNamespace(
        summary=summary,
        key_facts=key_facts or [],
        fact_labels=fact_labels or {},
        interpretation_gaps=interpretation_gaps or [],
        sources=sources or [],
    )


def _factcheck(verified: bool, sources=None, corrections=None,
               interpretation_opportunity: str = "",
               marketability_signal: str = "",
               confidence: str = "low"):
    return SimpleNamespace(
        verified=verified,
        sources=sources or [],
        corrections=corrections or [],
        interpretation_opportunity=interpretation_opportunity,
        marketability_signal=marketability_signal,
        confidence=confidence,
    )


# ─── english_ratio 유틸 ──────────────────────────────────────────────────

def test_english_ratio_mostly_korean():
    assert _english_ratio("한국은행 6월 18일 금리 결정 발표") < 0.1


def test_english_ratio_mostly_english():
    assert _english_ratio("Nvidia CEO comment fuels crypto rally discussion") > 0.9


def test_english_ratio_handles_empty():
    assert _english_ratio("") == 0.0
    assert _english_ratio(None) == 0.0  # type: ignore[arg-type]


# ─── 1. factcheck.verified=False → [unverified] 태그 ─────────────────

def test_unverified_factcheck_sources_pass_with_tag():
    """factcheck.verified=False 여도 sources 가 confirmed 에 통과하되
    각 항목 앞에 [unverified] 프리픽스가 붙어야 함."""
    fc = _factcheck(
        verified=False,
        sources=["한국은행 보도자료 2026-06-18", "기재부 정례 브리핑"],
    )
    pack = build_source_pack(
        _si(), _si(),
        research=_research(summary="한국 경제 동향 요약"),
        factcheck=fc,
    )
    # 두 sources 모두 통과
    tagged = [c for c in pack["confirmed_facts"] if c.startswith("[unverified]")]
    assert len(tagged) == 2
    assert any("한국은행 보도자료" in c for c in tagged)
    assert any("기재부 정례 브리핑" in c for c in tagged)


# ─── 2. factcheck.verified=True → 태그 없음 (회귀) ───────────────────

def test_verified_factcheck_sources_no_tag():
    """verified=True 는 태그 없이 append (기존 동작 유지)."""
    fc = _factcheck(
        verified=True,
        sources=["검증된 출처 A"],
    )
    pack = build_source_pack(
        _si(), _si(),
        research=None,
        factcheck=fc,
    )
    assert "검증된 출처 A" in pack["confirmed_facts"]
    # [unverified] 태그는 없어야 함
    for c in pack["confirmed_facts"]:
        assert not c.startswith("[unverified]")


# ─── 3. research.summary 영어 → [en] fallback + korea_angle ──────────

def test_english_summary_triggers_en_prefix_on_confirmed_fallback():
    """confirmed_facts/research.key_facts 모두 비어있고 summary 가 영어면
    summary 가 [en] 프리픽스로 confirmed 에 fallback 으로 들어가야 함."""
    r = _research(
        summary=(
            "Australia selects Japan's Mogami-class frigate over Germany's "
            "TKMS MEKO A-200 for the SEA 3000 general-purpose frigate program."
        ),
        key_facts=[],
        fact_labels={},
    )
    pack = build_source_pack(
        _si(), _si(),
        research=r,
        factcheck=None,
    )
    # confirmed fallback 에 [en] 프리픽스로 들어가야 함
    assert len(pack["confirmed_facts"]) >= 1
    assert pack["confirmed_facts"][0].startswith("[en] ")
    # korea_angle 에도 [en] 프리픽스가 붙어야 함
    assert len(pack["korea_angle"]) >= 1
    assert pack["korea_angle"][0].startswith("[en] ")


def test_korean_summary_does_not_get_en_prefix():
    """한국어 summary 는 [en] 프리픽스가 붙지 않아야 함 (임계 0.4 이하)."""
    r = _research(summary="호주가 일본 Mogami 함정을 선정했다고 발표.")
    pack = build_source_pack(_si(), _si(), research=r, factcheck=None)
    assert len(pack["korea_angle"]) >= 1
    assert not pack["korea_angle"][0].startswith("[en] ")


# ─── 4. 모든 경로 실패 → confirmed=[] 회귀 안전망 ────────────────────

def test_all_inputs_empty_leaves_confirmed_empty():
    """research / factcheck 모두 None → confirmed=[] 유지.
    format_handoff 의 "(확정 사실이 공급되지 않음)" 메타 지시문 경로는
    이번 수정으로도 여전히 존재해야 한다 (안전망 보존)."""
    pack = build_source_pack(_si(), _si(), research=None, factcheck=None)
    assert pack["confirmed_facts"] == []

    # format_handoff 가 빈 confirmed 를 받아서 메타 지시문을 삽입하는지 재확인
    from app.services.grok_handoff import format_handoff
    ap = {
        "winner_angle": {"angle": "A"},
        "core_tension": "",
        "frame_type": "underreported_angle",
        "story_spine": list(),
        "readability_risk": "medium",
        "share_trigger": "",
    }
    out = format_handoff(pack, ap, "본문")
    assert "(확정 사실이 공급되지 않음" in out


# ─── 5. 혼합 케이스: factcheck verified + research key_facts ─────────

def test_mixed_verified_factcheck_and_research_key_facts():
    """verified factcheck + labeled research → 둘 다 confirmed 에 통과."""
    fc = _factcheck(verified=True, sources=["검증 A"])
    r = _research(
        summary="요약",
        key_facts=["사실 1", "사실 2"],
        fact_labels={"사실 1": "confirms_common_narrative"},
    )
    pack = build_source_pack(_si(), _si(), research=r, factcheck=fc)
    joined = " ".join(pack["confirmed_facts"])
    assert "검증 A" in joined
    assert "사실 1 [confirms_common_narrative]" in joined
    assert "사실 2" in joined
