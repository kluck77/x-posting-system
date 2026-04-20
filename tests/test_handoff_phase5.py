"""
Phase 5 tests — grok_handoff 를 '편집장 지시서' 로 재편한 후 검증.

초점:
- 영어 잔존 제거 (_sanitize_ko / _korean_ratio)
- [unverified] 한국어 재포맷 (_reformat_unverified)
- evidence 중복 제거 (_dedupe_evidence)
- 신규 5 블록 + Phase 5 meta 필드 (editorial_goal / what_to_sharpen / what_to_cut)
- salvageability 블록이 맨 아래
- meta=None 회귀
"""
from __future__ import annotations

import pytest

from app.services.editorial_meta import (
    META_VERSION,
    build_editorial_meta,
    _derive_editorial_goal,
    _derive_what_to_sharpen,
    _derive_what_to_cut,
    _is_weak_hook,
)
from app.services.grok_handoff import (
    _HANDOFF_HARD_MAX,
    _korean_ratio,
    _sanitize_ko,
    _reformat_unverified,
    _dedupe_evidence,
    format_handoff,
)


# ─── fixture helpers ────────────────────────────────────────────────────

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
        "winner_angle": {"angle": "한국 앵글", "score": 70, "reason": ""},
        "core_tension": "",
        "frame_type": "contrast",
        "story_spine": ["hook","explain","evidence","contrast","close"],
        "readability_risk": "medium",
        "share_trigger": "",
        "scan_pattern": "",
        "method": "gemini",
    }
    base.update(o)
    return base


# ─── 1. sanitize utils ──────────────────────────────────────────────────

def test_korean_ratio_korean_dominant():
    # 숫자 토큰이 분모에 포함되므로 0.7 대역. 영어 dominant(<0.5)와는 확연히 차이.
    assert _korean_ratio("한국은행 6월 18일 금리 동결") > 0.7


def test_korean_ratio_english_dominant():
    assert _korean_ratio("Nvidia CEO comment fuels crypto") < 0.1


def test_sanitize_ko_english_replaced_with_placeholder():
    out = _sanitize_ko("This will be Japan's first warship export project")
    assert "한국어 압축 필요" in out


def test_sanitize_ko_korean_passes_through():
    s = "한국 원유 수입의 70%가 중동에서 온다"
    assert _sanitize_ko(s) == s


def test_sanitize_ko_empty_uses_fallback():
    assert _sanitize_ko("", fallback="(없음)") == "(없음)"


# ─── 2. _reformat_unverified ────────────────────────────────────────────

def test_reformat_unverified_korean():
    out = _reformat_unverified(["[unverified] Peter Thiel 친분", "[unverified] AI 낙관론자 규정"])
    assert out == ["Peter Thiel 친분는 현재 검증 부족", "AI 낙관론자 규정는 현재 검증 부족"]


def test_reformat_unverified_english_body_becomes_placeholder():
    """[unverified] 뒤 영어 body → 한국어 압축 필요 placeholder."""
    out = _reformat_unverified(["[unverified] Peter Thiel close relationship rumor"])
    assert len(out) == 1
    assert "한국어 압축 필요" in out[0]


def test_reformat_drops_empty_strings():
    assert _reformat_unverified(["", "  ", None]) == []


def test_reformat_en_prefix_becomes_placeholder():
    out = _reformat_unverified(["[en] Australia picks Japan Mogami-class frigate"])
    assert len(out) == 1
    assert "한국어 압축 필요" in out[0]


# ─── 3. _dedupe_evidence ────────────────────────────────────────────────

def test_dedupe_evidence_limits_to_2():
    items = ["한국은행 금리 동결 결정", "한국은행 금리 동결 결정", "원유 수입 70% 중동", "별도 사실"]
    out = _dedupe_evidence(items, limit=2)
    assert len(out) == 2
    assert out[0] == "한국은행 금리 동결 결정"
    assert out[1] == "원유 수입 70% 중동"


def test_dedupe_evidence_drops_english():
    items = ["Australia picks Japan Mogami frigate program details", "한국 사례 1", "한국 사례 2"]
    out = _dedupe_evidence(items, limit=3)
    assert "Australia" not in "".join(out)
    assert "한국 사례 1" in out


# ─── 4. Phase 5 meta 신규 3 필드 ────────────────────────────────────────

def test_meta_version_is_2():
    m = build_editorial_meta(hook="h", body="b")
    assert m["meta_version"] == "2"
    # 기존 too_obvious_reason 키 제거, too_obvious_warning 으로 리네이밍
    assert "too_obvious_warning" in m
    assert "too_obvious_reason" not in m


def test_editorial_goal_from_winner_reason():
    ap = _min_ap(winner_angle={"angle": "A", "score": 80,
                                 "reason": "이 각도는 차별화 포인트"})
    g = _derive_editorial_goal(ap, stake_sentence="", core_tension="", share_trigger="")
    assert g == "이 각도는 차별화 포인트"


def test_editorial_goal_skips_heuristic_fallback_reason():
    """reason 이 heuristic fallback placeholder 이면 파생 조합으로 대체."""
    ap = _min_ap(
        winner_angle={"angle": "A", "reason": "heuristic fallback (no Gemini call)"},
        core_tension="중동 변수", share_trigger="보험료 체크",
    )
    g = _derive_editorial_goal(ap, stake_sentence="", core_tension="중동 변수", share_trigger="보험료 체크")
    assert "중동 변수" in g
    assert "보험료 체크" in g


def test_what_to_sharpen_max_2_with_action_verb():
    out = _derive_what_to_sharpen(
        stop_scroll_line="한국 원유 70% 호르무즈",
        hidden_variable="보험료 재가격",
        stake_sentence="가계 예산 압박",
    )
    assert len(out) == 2
    assert any("첫 줄" in s for s in out)
    assert any("숨은 변수" in s for s in out)


def test_what_to_sharpen_empty_when_nothing():
    assert _derive_what_to_sharpen("", "", "") == []


def test_what_to_cut_uses_priority_and_caps_at_3():
    labels = {
        "flags": {
            "missing_context_flag": True,
            "weak_ending_flag": True,
            "generic_cta_flag": True,
            "ai_tone_flag": True,
        },
        "ending": {"ending_type": "question_only"},
    }
    out = _derive_what_to_cut(labels, too_obvious_flag=True, hook="짧음")
    assert len(out) == 3
    # weak_hook 이 우선순위 1 이므로 포함
    assert any("약한 훅" in s for s in out)
    # too_obvious 도 상위 우선순위
    assert any("표면 인과" in s for s in out)


def test_what_to_cut_empty_when_clean():
    out = _derive_what_to_cut(
        linter_labels={"flags": {}, "ending": {}},
        too_obvious_flag=False,
        hook="한국 원유 수입 70% 호르무즈 경유",
    )
    assert out == []


def test_is_weak_hook_detects_short_and_generic():
    assert _is_weak_hook("짧음") is True
    assert _is_weak_hook("일반적인 설명 문장입니다 결론") is True
    assert _is_weak_hook("한국은행 6월 동결 발표") is False
    assert _is_weak_hook("2026 매출 2배") is False


# ─── 5. build_editorial_meta 전체 ───────────────────────────────────────

def test_build_editorial_meta_v2_schema():
    m = build_editorial_meta(
        hook="한국 원유 수입 70% 호르무즈",
        body="2026년 6월 18일 한국은행 동결. 원유 30% 상승 시 CPI 0.2%p.",
        source_pack=_min_sp(
            conflicts_or_uncertainty=["일시 변동 vs 구조적 차질"],
            watch_next=["가계 예산 압박"],
        ),
        angle_pack=_min_ap(
            frame_type="contrast", method="gemini",
            share_trigger="보험료 체크", core_tension="중동 변수 비대칭",
            winner_angle={"angle": "호르무즈 비대칭", "reason": "한국 가계 비대칭 노출"},
        ),
        linter_labels={"flags": {}, "company_context": {"entities_requiring_context": []}},
        strategy_os={"positioning": {"one_liner": "non-KR 해설", "lenses": ["economy"]}},
        category="economy",
    )
    for key in ("editorial_goal", "what_to_sharpen", "what_to_cut", "too_obvious_warning"):
        assert key in m
    assert isinstance(m["what_to_sharpen"], list)
    assert isinstance(m["what_to_cut"], list)
    assert len(m["what_to_sharpen"]) <= 2
    assert len(m["what_to_cut"]) <= 3


# ─── 6. format_handoff 통합 ─────────────────────────────────────────────

def _rich_meta():
    return {
        "meta_version": "2",
        "stop_scroll_line": "한국 원유 70% 호르무즈",
        "rt_motive_type": "signal",
        "identity_signal": "economy 관점 독자 — non-KR 해설",
        "hidden_variable": "보험료 재가격",
        "stake_sentence": "가계 예산 압박",
        "too_obvious_flag": True,
        "too_obvious_warning": "표면 인과만 — 숨은 변수 부재",
        "editorial_goal": "중동 변수 → 한국 가계 비대칭 노출",
        "what_to_sharpen": ["첫 줄로 끌어올려라: 한국 원유 70%",
                             "숨은 변수 명시: 보험료 재가격"],
        "what_to_cut": ["약한 훅 문장 삭제 — 숫자·고유명사 들어간 줄로 교체",
                         "표면 인과 문장 삭제 — 숨은 변수 드러내기"],
        "salvageability": {"score": "B",
                             "reason": "숨은 변수 부재 보완 필요.",
                             "checks": {}},
    }


def test_format_handoff_phase5_block_headers_present():
    out = format_handoff(_min_sp(), _min_ap(), "본문 2026 30%", editorial_meta=_rich_meta())
    assert "## 🔥 왜 이 글을 세게 써야 하는가" in out
    assert "## 🏴 지금 초안이 평평한 이유" in out
    assert "## 💎 반드시 살릴 포인트" in out
    assert "## 우리 계정 편집 우선순위" not in out  # strategy_os 없으면 생략
    assert "## 🎯 살릴 가치" in out


# ─── 9. Phase 5.1: 🔥 블록에 core_tension / share_trigger 재노출 ──────

def test_why_push_block_includes_tension_and_trigger():
    """spec 섹션 6: editorial_goal + core_tension + share_trigger 모두
    🔥 블록에 한국어 1줄씩 표시."""
    ap = _min_ap(
        core_tension="중동 변수 → 한국 비대칭",
        share_trigger="지금 봐야 할 포인트: 보험료+스팟",
    )
    out = format_handoff(_min_sp(), ap, "본문", editorial_meta=_rich_meta())
    # 🔥 블록 추출
    why_idx = out.index("## 🔥 왜 이 글을 세게 써야 하는가")
    flat_idx = out.index("## 🏴") if "## 🏴" in out else len(out)
    why_block = out[why_idx:flat_idx]
    assert "- 편집 목표:" in why_block
    assert "- 핵심 긴장:" in why_block
    assert "중동 변수" in why_block
    assert "- 공유 트리거:" in why_block
    assert "보험료+스팟" in why_block


def test_why_push_block_skips_english_tension_and_trigger():
    """영어 dominant core_tension / share_trigger 는 placeholder 로 전환되어
    해당 줄 자체가 생략됨 (한글 0 + 영어 5+ → sanitize 버림)."""
    ap = _min_ap(
        core_tension="Uncertainty on record: Nvidia comment fuels rally",
        share_trigger="Global markets recovered fast while Korea lagged",
    )
    out = format_handoff(_min_sp(), ap, "본문", editorial_meta=_rich_meta())
    why_idx = out.index("## 🔥 왜 이 글을 세게 써야 하는가")
    flat_idx = out.index("## 🏴") if "## 🏴" in out else len(out)
    why_block = out[why_idx:flat_idx]
    # 영어 문장이 그대로 나오면 안 됨
    assert "Uncertainty on record" not in why_block
    assert "Global markets recovered" not in why_block
    # 편집 목표 / RT 동기 같은 다른 줄은 있을 수 있음 (rich_meta 기반)
    assert "- 편집 목표:" in why_block


def test_format_handoff_salvageability_is_last_block():
    out = format_handoff(_min_sp(), _min_ap(), "본문", editorial_meta=_rich_meta())
    assert "## 🎯 살릴 가치" in out
    # 마지막 블록이어야 함
    salv_idx = out.index("## 🎯 살릴 가치")
    # salv 뒤에 다른 ## 블록 없음
    tail = out[salv_idx + 10:]
    assert "## " not in tail


def test_format_handoff_phase5_what_to_cut_rendered_as_action():
    out = format_handoff(_min_sp(), _min_ap(), "본문", editorial_meta=_rich_meta())
    assert "잘라라:" in out
    assert "약한 훅 문장 삭제" in out


def test_format_handoff_phase5_what_to_sharpen_rendered():
    out = format_handoff(_min_sp(), _min_ap(), "본문", editorial_meta=_rich_meta())
    assert "세게 밀어라:" in out
    assert "첫 줄로 끌어올려라" in out


# ─── 7. 영어 sanitize 통합 ──────────────────────────────────────────────

def test_format_handoff_english_angle_sanitized():
    """winner_angle.angle 이 영어면 handoff 에 '앵글 원문 영어 — 편집장 한국어 압축 필요'."""
    ap = _min_ap(
        winner_angle={"angle": "This will be Japan's first warship export project"},
        core_tension="Uncertainty on record: Nvidia CEO",
    )
    out = format_handoff(_min_sp(), ap, "본문")
    assert "한국어 압축 필요" in out
    # 영어 원문이 그대로 노출되면 안 됨
    assert "This will be Japan" not in out
    assert "Uncertainty on record" not in out


def test_format_handoff_unverified_sources_reformatted():
    sp = _min_sp(confirmed_facts=[
        "[unverified] Peter Thiel 친분",
        "[unverified] AI 낙관론자 규정",
    ])
    out = format_handoff(sp, _min_ap(), "본문")
    assert "현재 검증 부족" in out
    assert "[unverified]" not in out


def test_format_handoff_english_concept_translation_block_omitted():
    """concept_translation 이 영어면 '어려운 개념 한 줄 번역' 블록 자체 생략."""
    sp = _min_sp(concept_translation="Hormuz Strait: world's key oil transit chokepoint")
    out = format_handoff(sp, _min_ap(), "본문")
    assert "## 어려운 개념 한 줄 번역" not in out


def test_format_handoff_evidence_dedupe_and_english_drop():
    sp = _min_sp(evidence_pack=[
        "한국은행 동결 결정",
        "한국은행 동결 결정",  # 중복
        "Australia picks Japan Mogami frigate details extensive",  # 영어 dominant
        "원유 수입 70% 중동",
    ])
    out = format_handoff(sp, _min_ap(), "본문")
    # 중복 제거 & 영어 제거 후 최대 2개만 보임
    assert out.count("한국은행 동결 결정") == 1
    assert "Australia" not in out


# ─── 8. meta=None 회귀 ──────────────────────────────────────────────────

def test_format_handoff_meta_none_no_phase5_blocks():
    out = format_handoff(_min_sp(), _min_ap(), "본문")
    for h in ("## 🔥 왜 이 글을 세게 써야 하는가",
              "## 🏴 지금 초안이 평평한 이유",
              "## 💎 반드시 살릴 포인트",
              "## 🎯 살릴 가치"):
        assert h not in out


def test_format_handoff_hard_cap_still_respected_phase5():
    huge = [f"항목 {i} " * 30 for i in range(30)]
    out = format_handoff(
        _min_sp(confirmed_facts=huge, evidence_pack=huge),
        _min_ap(core_tension="긴 " * 50, share_trigger="긴 " * 50),
        "본문 " * 400,
        editorial_meta=_rich_meta(),
    )
    assert len(out) <= _HANDOFF_HARD_MAX
