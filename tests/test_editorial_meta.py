"""
Phase 4 editorial_meta 테스트.

- 7 필드 각각의 파생 동작
- salvageability A/B/C 등급 경계
- fail-open (입력 None / 손상 시에도 스키마 유지)
- format_handoff 통합 (3 블록 + 살릴 가치 뱃지)
- 회귀: meta=None 일 때 기존 handoff 완전 동일
"""
import pytest

from app.services.editorial_meta import (
    META_VERSION,
    build_editorial_meta,
    _derive_stop_scroll_line,
    _derive_rt_motive,
    _derive_identity_signal,
    _derive_hidden_variable,
    _derive_stake_sentence,
    _derive_too_obvious_warning,
    _compute_too_obvious_flag,
    _score_salvageability,
)
from app.services.grok_handoff import format_handoff


TOP_KEYS = {
    "meta_version",
    "stop_scroll_line",
    "rt_motive_type",
    "identity_signal",
    "hidden_variable",
    "stake_sentence",
    "too_obvious_flag",
    "too_obvious_warning",
    # Phase 5 신규 3 필드
    "editorial_goal",
    "what_to_sharpen",
    "what_to_cut",
    "salvageability",
}


def _min_sp(**o):
    base = {
        "confirmed_facts": [],
        "conflicts_or_uncertainty": [],
        "korea_angle": [], "global_angle": [], "watch_next": [],
        "concept_translation": "", "evidence_pack": [], "scan_pattern": "",
    }
    base.update(o)
    return base


def _min_ap(**o):
    base = {
        "winner_angle": {"angle": "앵글 1"},
        "core_tension": "",
        "frame_type": "contrast",
        "story_spine": ["hook","explain","evidence","contrast","close"],
        "readability_risk": "medium",
        "share_trigger": "",
        "scan_pattern": "",
        "method": "heuristic",
    }
    base.update(o)
    return base


# ─── 1. stop_scroll_line ──────────────────────────────────────────────

def test_stop_scroll_prefers_hook_with_numbers():
    line = _derive_stop_scroll_line(
        "한국 원유 수입 70% 호르무즈 경유",
        _min_ap(share_trigger="보험료 상승 주목", core_tension="중동 변수"),
    )
    assert "70%" in line


def test_stop_scroll_falls_back_to_share_trigger():
    line = _derive_stop_scroll_line("", _min_ap(share_trigger="지금 주목", core_tension=""))
    assert line == "지금 주목"


def test_stop_scroll_empty_when_all_empty():
    assert _derive_stop_scroll_line("", _min_ap()) == ""


# ─── 2. rt_motive_type ────────────────────────────────────────────────

def test_rt_motive_identity():
    labels = {"frame_rt": {"identity_signal_present": True, "korea_angle_used": True}}
    assert _derive_rt_motive("우리 한국 가계가 충격을 흡수한다", None, labels, None) == "identity"


def test_rt_motive_argue():
    assert _derive_rt_motive("실제로는 구조적 변화가 더 크다 반박 필요", None, None, None) == "argue"


def test_rt_motive_practical():
    assert _derive_rt_motive("체크: 환율 2% 변동 시 가계 부담 30% 증가. 주의", None, None, None) == "practical"


def test_rt_motive_signal():
    assert _derive_rt_motive("2026년 매출 2배 증가, 전년 대비 30% 성장", "economy", None, None) == "signal"


def test_rt_motive_approval():
    assert _derive_rt_motive("정확히 이 말이 맞다. 공감한다.", None, None, None) == "approval"


def test_rt_motive_unclear_fallback():
    assert _derive_rt_motive("단순 요약 본문입니다.", None, None, None) == "unclear"


# ─── 3. identity_signal ───────────────────────────────────────────────

def test_identity_signal_from_strategy_lens_match():
    so = {
        "positioning": {
            "one_liner": "non-KR 독자에게 한국 해설",
            "lenses": ["policy", "economy", "society"],
        }
    }
    sig = _derive_identity_signal("economy 측면에서 본 한국 구조", so)
    assert "economy" in sig
    assert "해설" in sig


def test_identity_signal_falls_back_to_one_liner():
    so = {"positioning": {"one_liner": "기본 정의", "lenses": ["policy"]}}
    assert _derive_identity_signal("정책 없는 본문", so) == "기본 정의"


def test_identity_signal_empty_when_no_strategy():
    assert _derive_identity_signal("아무 문장", None) == ""


# ─── 4. hidden_variable ───────────────────────────────────────────────

def test_hidden_variable_from_conflicts():
    sp = _min_sp(conflicts_or_uncertainty=["[gap] 중동 변수와 보험료 재가격 상호작용"])
    hv = _derive_hidden_variable(sp)
    assert "보험료" in hv
    assert not hv.startswith("[gap]")


def test_hidden_variable_empty():
    assert _derive_hidden_variable(_min_sp()) == ""


# ─── 5. stake_sentence ────────────────────────────────────────────────

def test_stake_from_watch_next_priority():
    sp = _min_sp(watch_next=["[marketability] 가계 예산 압박 임계"], )
    ap = _min_ap(share_trigger="다른 값")
    s = _derive_stake_sentence(sp, ap)
    assert "가계 예산" in s


def test_stake_falls_back_to_share_trigger():
    sp = _min_sp()
    ap = _min_ap(share_trigger="지금 봐야 할 포인트")
    assert _derive_stake_sentence(sp, ap) == "지금 봐야 할 포인트"


# ─── 6. too_obvious_warning ────────────────────────────────────────────

def test_too_obvious_no_numbers():
    body = "에너지 비용 상승이 무역 수지에 영향을 미친다. " * 5
    assert _compute_too_obvious_flag(body, None) is True
    assert _derive_too_obvious_warning(body, None) is not None
    assert "수치" in _derive_too_obvious_warning(body, None)


def test_too_obvious_with_numbers_no_flag():
    body = "2026년 30% 변동 기록. " * 10
    assert _compute_too_obvious_flag(body, None) is False


def test_too_obvious_warning_none_when_short_body():
    assert _derive_too_obvious_warning("짧음", None) is None


# ─── 7. salvageability 등급 경계 ──────────────────────────────────────

def test_salvageability_A():
    r = _score_salvageability(
        angle_pack={"frame_type": "contrast", "method": "gemini"},
        stake_sentence="가계 예산 압박 임계",
        hidden_variable="보험료 재가격",
        rt_motive_type="signal",
        linter_labels={
            "flags": {"missing_context_flag": False, "ai_tone_flag": False},
            "company_context": {"entities_requiring_context": []},
        },
        too_obvious_flag=False,
    )
    assert r["score"] == "A"
    # reason 은 grade prefix 없이 content 만. 뱃지에서 조립 시 "A — {reason}".
    assert "핵심 요소" in r["reason"] or "보완" in r["reason"]


def test_salvageability_B_missing_stake_and_hidden():
    r = _score_salvageability(
        angle_pack={"frame_type": "contrast", "method": "gemini"},
        stake_sentence="",
        hidden_variable="",
        rt_motive_type="signal",
        linter_labels={
            "flags": {"missing_context_flag": False, "ai_tone_flag": False},
            "company_context": {"entities_requiring_context": []},
        },
        too_obvious_flag=False,
    )
    assert r["score"] == "B"


def test_salvageability_C_heuristic_en_blocked():
    r = _score_salvageability(
        angle_pack={"frame_type": "contrast", "method": "heuristic_en_blocked"},
        stake_sentence="",
        hidden_variable="",
        rt_motive_type="unclear",
        linter_labels={
            "flags": {"missing_context_flag": True, "ai_tone_flag": True},
            "company_context": {"entities_requiring_context": ["NVIDIA"]},
        },
        too_obvious_flag=True,
    )
    assert r["score"] == "C"
    # reason 에는 grade prefix 없음. 뱃지 조립 시 붙음.
    assert "reject" in r["reason"]


# ─── 8. build_editorial_meta 전체 스키마 ──────────────────────────────

def test_build_editorial_meta_full_schema():
    meta = build_editorial_meta(
        hook="한국 원유 수입 70% 호르무즈",
        body="2026년 6월 18일 한국은행 동결 발표. 원유 30% 상승 시 CPI 0.2%p.",
        source_pack=_min_sp(
            conflicts_or_uncertainty=["일시 변동 vs 구조적 차질"],
            watch_next=["가계 예산 압박"],
        ),
        angle_pack=_min_ap(
            frame_type="contrast", method="gemini",
            share_trigger="보험료 체크",
            core_tension="중동 변수 비대칭",
        ),
        linter_labels={"flags": {"missing_context_flag": False, "ai_tone_flag": False,
                                 "weak_ending_flag": False, "generic_cta_flag": False},
                       "company_context": {"entities_requiring_context": []}},
        strategy_os={"positioning": {"one_liner": "non-KR 해설", "lenses": ["economy"]}},
        category="economy",
    )
    assert set(meta.keys()) == TOP_KEYS
    assert meta["meta_version"] == META_VERSION
    assert meta["salvageability"]["score"] in ("A", "B", "C")


def test_build_editorial_meta_fail_open_all_none():
    meta = build_editorial_meta(hook=None, body=None)
    assert set(meta.keys()) == TOP_KEYS
    assert meta["rt_motive_type"] == "unclear"
    assert meta["stop_scroll_line"] == ""
    assert meta["salvageability"]["score"] == "C"


def test_build_editorial_meta_handles_corrupt_inputs():
    meta = build_editorial_meta(
        hook="h", body="b" * 150,
        source_pack="not a dict",  # type: ignore[arg-type]
        angle_pack=42,              # type: ignore[arg-type]
        linter_labels=[1, 2, 3],    # type: ignore[arg-type]
        strategy_os="also wrong",   # type: ignore[arg-type]
        category=123,               # type: ignore[arg-type]
    )
    assert set(meta.keys()) == TOP_KEYS


# ─── 9. format_handoff 통합 ───────────────────────────────────────────

def test_format_handoff_phase5_blocks_render():
    """Phase 5 블록 헤더 4개 렌더 + 값 반영 확인."""
    meta = {
        "meta_version": "2",
        "stop_scroll_line": "한국 원유 70% 호르무즈",
        "rt_motive_type": "signal",
        "identity_signal": "economy 관점 독자 — non-KR 해설",
        "hidden_variable": "보험료 재가격",
        "stake_sentence": "가계 예산 압박",
        "too_obvious_flag": True,
        "too_obvious_warning": "표면 인과만 — 숨은 변수 부재",
        "editorial_goal": "중동 변수 → 한국 비대칭",
        "what_to_sharpen": ["첫 줄로 끌어올려라: 한국 원유 70%"],
        "what_to_cut": ["표면 인과 문장 삭제 — 숨은 변수 드러내기"],
        "salvageability": {"score": "B", "reason": "숨은 변수 부재 보완."},
    }
    out = format_handoff(
        _min_sp(), _min_ap(),
        "본문 2026년 30% 기록.",
        editorial_meta=meta,
    )
    assert "## 🔥 왜 이 글을 세게 써야 하는가" in out
    assert "## 🏴 지금 초안이 평평한 이유" in out
    assert "## 💎 반드시 살릴 포인트" in out
    assert "## 🎯 살릴 가치" in out
    assert "- 등급: B" in out
    # 값들 반영
    assert "signal" in out
    assert "economy 관점" in out
    assert "보험료 재가격" in out
    assert "한국 원유 70%" in out
    # 하드 상한
    from app.services.grok_handoff import _HANDOFF_HARD_MAX
    assert len(out) <= _HANDOFF_HARD_MAX


def test_format_handoff_meta_none_backwards_compat():
    """editorial_meta=None 일 때 Phase 5 블록 전부 미생성."""
    out = format_handoff(_min_sp(), _min_ap(), "본문")
    assert "## 🎯 살릴 가치" not in out
    assert "## 🔥 왜 이 글을 세게" not in out
    assert "## 🏴 지금 초안이 평평한" not in out
    assert "## 💎 반드시 살릴 포인트" not in out


def test_format_handoff_c_grade_block_renders():
    """salvageability C 는 블록 맨 아래에 '- 등급: C' 로 표시."""
    meta = {
        "salvageability": {"score": "C", "reason": "frame 부재. 재각도/reject 권장."},
        "rt_motive_type": "unclear",
        "too_obvious_flag": False,
    }
    out = format_handoff(_min_sp(), _min_ap(), "본문", editorial_meta=meta)
    assert "## 🎯 살릴 가치" in out
    assert "- 등급: C" in out


def test_format_handoff_empty_meta_no_phase5_blocks():
    """editorial_meta 가 빈 dict 이면 모든 Phase 5 블록 생략."""
    out = format_handoff(_min_sp(), _min_ap(), "본문", editorial_meta={})
    assert "## 🎯 살릴 가치" not in out
    assert "## 🔥 왜 이 글을 세게" not in out
    assert "## 💎 반드시 살릴 포인트" not in out
