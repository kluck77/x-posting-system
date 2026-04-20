"""
grok_handoff 편집 신호 테스트 (Phase: grok-handoff-signals).

- 편집 목표: 기존 `## 이 글의 핵심 각도` 블록에 `- 편집 목표` 1줄 append
  (중복 방지를 위해 별도 `## 편집 신호` 블록은 만들지 않음)
- 블록 B: ## 시스템이 감지한 약한 지점 (True 만 1줄씩)
- 블록 C: ## 계정 톤 (참고)  (Strategy OS compact: one_liner, hooks 상위 2, banned 상위 3)

핵심 검증: 값 비면 블록 전체 생략. 하드 상한 _HANDOFF_HARD_MAX.
"""
from app.services.grok_handoff import (
    _HANDOFF_HARD_MAX,
    _build_weakness_block,
    _build_account_tone_block,
    _derive_editorial_goal,
    _derive_weak_hook,
    _derive_too_obvious,
    format_handoff,
)


# ─── 최소 source_pack / angle_pack fixture ──────────────────────────────

def _min_sp(**overrides):
    base = {
        "confirmed_facts": [],
        "concept_translation": "",
        "evidence_pack": [],
        "korea_angle": "",
        "global_angle": "",
        "conflicts_or_uncertainty": [],
        "scan_pattern": "",
    }
    base.update(overrides)
    return base


def _min_ap(**overrides):
    base = {
        "winner_angle": {"angle": "테스트 앵글"},
        "core_tension": "",
        "frame_type": "",
        "story_spine": [],
        "readability_risk": "",
        "share_trigger": "",
        "scan_pattern": "",
    }
    base.update(overrides)
    return base


# ─── 회귀: 새 옵션 없이 호출하면 기존 동작 ─────────────────────────────

def test_backward_compat_no_editorial_kwargs():
    out = format_handoff(_min_sp(), _min_ap(), "본문 내용")
    # 기존 5블록 헤더 모두 존재
    assert "## 원문 초안" in out
    assert "## 이 글의 핵심 각도" in out
    assert "## 절대 바꾸지 말 것" in out
    assert "## 바꿔도 되는 것" in out
    assert "## 최종 출력 규칙" in out
    # 새 블록 헤더는 없어야 함 (angle_pack 에 core_tension/share_trigger 둘 다 없음)
    assert "편집 목표:" not in out
    assert "## 시스템이 감지한 약한 지점" not in out
    assert "## 계정 톤 (참고)" not in out


# ─── 블록 A (편집 신호) ─────────────────────────────────────────────────

def test_editorial_goal_from_reason_preferred():
    ap = _min_ap(
        winner_angle={"angle": "A", "reason": "이 각도가 차별화"},
        core_tension="긴장",
        share_trigger="공유트리거",
    )
    assert _derive_editorial_goal(ap) == "이 각도가 차별화"


def test_editorial_goal_falls_back_to_tension_plus_trigger():
    ap = _min_ap(core_tension="긴장A", share_trigger="트리거B")
    goal = _derive_editorial_goal(ap)
    assert "긴장A" in goal and "트리거B" in goal and "→" in goal


def test_editorial_goal_empty_when_all_missing():
    assert _derive_editorial_goal(_min_ap()) == ""
    assert _derive_editorial_goal({}) == ""


def test_editorial_goal_line_appended_to_angle_section():
    """편집 목표는 `## 이 글의 핵심 각도` 블록 끝에 `- 편집 목표: ...` 1줄로."""
    out = format_handoff(
        _min_sp(),
        _min_ap(core_tension="CT", share_trigger="ST"),
        "본문",
    )
    # 별도 블록 아님 — angle 섹션 내부
    assert "## 편집 신호" not in out
    assert "- 편집 목표:" in out
    # 편집 목표 줄이 angle 섹션 안에 위치
    angle_section_idx = out.index("## 이 글의 핵심 각도")
    lock_section_idx = out.index("## 절대 바꾸지 말 것")
    goal_idx = out.index("- 편집 목표:")
    assert angle_section_idx < goal_idx < lock_section_idx


# ─── 블록 B (시스템이 감지한 약한 지점) ───────────────────────────────

def test_derive_weak_hook_short():
    assert _derive_weak_hook("짧음") is True


def test_derive_weak_hook_no_number_no_entity():
    # 길고 숫자/대문자/한국기관 없음 → weak_hook
    assert _derive_weak_hook("한 해협이 한국 경제를 좌우할 수 있다는 의미") is True


def test_derive_weak_hook_with_number():
    assert _derive_weak_hook("한국 원유 수입의 70%는 호르무즈 경유") is False


def test_derive_too_obvious():
    # 100자 이상, 숫자 없음
    body = "에너지 비용이 오르면 무역수지가 악화되고 소비자물가가 오른다. " * 4
    assert _derive_too_obvious(body) is True


def test_derive_too_obvious_short_body_false():
    assert _derive_too_obvious("짧은 본문") is False


def test_derive_too_obvious_with_number():
    body = "에너지 비용이 2026년 6월 기준 30% 상승했다는 분석. " * 3
    assert _derive_too_obvious(body) is False


def test_weakness_block_only_detected_rendered():
    labels = {
        "flags": {
            "missing_context_flag": False,
            "weak_ending_flag": True,
            "generic_cta_flag": False,
            "ai_tone_flag": False,
        }
    }
    lines = _build_weakness_block(
        hook="2026년 정부 규제안 통과",   # 숫자 있어서 weak_hook 아님
        body="본문 안에 2026 숫자 있음. 짧게.",
        linter_labels=labels,
    )
    joined = "\n".join(lines)
    assert lines[0] == "## 시스템이 감지한 약한 지점"
    assert "weak_ending" in joined
    # 나머지는 나오지 말아야 함
    assert "missing_context" not in joined
    assert "generic_cta" not in joined
    assert "ai_tone" not in joined
    assert "too_obvious" not in joined
    assert "weak_hook" not in joined


def test_weakness_block_all_false_returns_empty():
    labels = {
        "flags": {
            "missing_context_flag": False,
            "weak_ending_flag": False,
            "generic_cta_flag": False,
            "ai_tone_flag": False,
        }
    }
    lines = _build_weakness_block(
        hook="2026년 한국은행 기준금리 동결 발표 헤드라인",
        body="본문 2026 숫자. 짧은 본문은 too_obvious 스킵.",
        linter_labels=labels,
    )
    assert lines == []


# ─── 블록 C (계정 톤, 참고) ────────────────────────────────────────────

def test_account_tone_block_caps_hooks_to_two_banned_to_three():
    so = {
        "positioning": {"one_liner": "non-KR 독자에게 한국 해설"},
        "hook_library": ["h1", "h2", "h3", "h4", "h5"],
        "banned_style": ["b1", "b2", "b3", "b4", "b5", "b6"],
    }
    lines = _build_account_tone_block(so)
    joined = "\n".join(lines)
    assert lines[0] == "## 계정 톤 (참고)"
    assert "훅 참고: h1 | h2" in joined
    assert "h3" not in joined
    assert "b1, b2, b3" in joined
    assert "b4" not in joined


def test_account_tone_block_empty_when_strategy_empty():
    so = {
        "positioning": {"one_liner": ""},
        "hook_library": [],
        "banned_style": [],
    }
    assert _build_account_tone_block(so) == []
    assert _build_account_tone_block(None) == []


# ─── 통합: format_handoff ───────────────────────────────────────────────

def test_format_handoff_with_all_editorial_signals():
    labels = {
        "flags": {
            "missing_context_flag": True,
            "weak_ending_flag": True,
            "generic_cta_flag": False,
            "ai_tone_flag": False,
        }
    }
    out = format_handoff(
        _min_sp(),
        _min_ap(core_tension="중동 변수", share_trigger="지금 봐야 할 포인트"),
        "본문 — 2026년 30% 변동이라는 구체 수치.",
        final_hook="훅은 2026년 기준",
        strategy_os={
            "positioning": {"one_liner": "non-KR 독자에게 한국 해설"},
            "hook_library": ["Korea just X:", "N년 전엔 Y였다.", "세 번째"],
            "banned_style": ["it is worth noting", "furthermore", "다름아닌", "바야흐로"],
        },
        linter_labels=labels,
    )
    assert "- 편집 목표:" in out
    assert "## 시스템이 감지한 약한 지점" in out
    assert "## 계정 톤 (참고)" in out
    # 길이 하드 상한
    assert len(out) <= _HANDOFF_HARD_MAX
    # 목표 길이 (넉넉하게 2500자 내로)
    assert len(out) <= 2500


def test_format_handoff_hard_cap_respected_with_huge_inputs():
    huge_list = [f"항목{i} " * 30 for i in range(30)]
    out = format_handoff(
        _min_sp(
            confirmed_facts=huge_list,
            conflicts_or_uncertainty=huge_list,
            concept_translation="긴 번역 " * 120,
            evidence_pack=huge_list,
        ),
        _min_ap(
            core_tension="긴 긴장 " * 60,
            share_trigger="긴 트리거 " * 60,
            winner_angle={"angle": "긴 앵글 " * 60, "reason": "긴 이유 " * 60},
        ),
        "본문 " * 400,
        final_hook="훅",  # weak_hook True
        strategy_os={
            "positioning": {"one_liner": "정의 " * 100},
            "hook_library": ["훅 " * 50 for _ in range(10)],
            "banned_style": ["금지 " * 50 for _ in range(10)],
        },
        linter_labels={"flags": {"missing_context_flag": True, "weak_ending_flag": True,
                                   "generic_cta_flag": True, "ai_tone_flag": True}},
    )
    assert len(out) <= _HANDOFF_HARD_MAX
    # 고정 5블록은 유지
    assert "## 원문 초안" in out
    assert "## 이 글의 핵심 각도" in out
    assert "## 절대 바꾸지 말 것" in out
    assert "## 바꿔도 되는 것" in out
    assert "## 최종 출력 규칙" in out


def test_format_handoff_target_length_normal_case():
    """일반적인 입력: 블록 A + B + C 포함, 전체 ≤ 2200자 목표."""
    out = format_handoff(
        _min_sp(
            confirmed_facts=["한국은행은 6월 18일 동결 결정", "원유 수입 70% 중동 경유"],
            concept_translation="호르무즈 해협: 세계 원유 수송 핵심 관문",
            conflicts_or_uncertainty=["일시적 변동 vs 구조적 차질"],
            scan_pattern="Short sentences, clear contrast points",
        ),
        _min_ap(
            core_tension="중동 변수 → 한국 비대칭 노출",
            share_trigger="지금 봐야 할 포인트: 보험료와 스팟 계약",
            winner_angle={"angle": "호르무즈 비대칭 노출"},
            frame_type="risk_exposure",
            readability_risk="중",
        ),
        "한국은행 기준금리 동결 발표. 중동 변수로 인한 에너지 비용 불확실성 증가. 2026년 6월 데이터로 본 한국 원유 수입 구조.",
        final_hook="호르무즈 해협이 한국 경제의 아킬레스건",
        strategy_os={
            "positioning": {"one_liner": "non-KR 독자에게 한국 해설"},
            "hook_library": ["Korea just X:", "N년 전엔 Y였다."],
            "banned_style": ["it is worth noting", "furthermore", "다름아닌"],
        },
        linter_labels={"flags": {"missing_context_flag": False, "weak_ending_flag": False,
                                   "generic_cta_flag": False, "ai_tone_flag": False}},
    )
    assert len(out) <= 2200


def test_format_handoff_block_order_weakness_tone_after_existing():
    """블록 B (약한 지점) / 블록 C (계정 톤) 는 기존 블록들 뒤에 와야 함."""
    out = format_handoff(
        _min_sp(),
        _min_ap(),
        "본문 — 2026 기준",
        final_hook="2026년 한국은행 발표 상세 기준 문장",
        strategy_os={"positioning": {"one_liner": "정의"}, "hook_library": [], "banned_style": []},
        linter_labels={"flags": {"missing_context_flag": True, "weak_ending_flag": True,
                                   "generic_cta_flag": False, "ai_tone_flag": False}},
    )
    i_rules = out.index("## 최종 출력 규칙")
    i_weak = out.index("## 시스템이 감지한 약한 지점")
    i_tone = out.index("## 계정 톤 (참고)")
    assert i_rules < i_weak < i_tone


def test_format_handoff_empty_signals_produce_no_blocks():
    """strategy_os + linter_labels 는 제공했지만 전부 비어있는 경우."""
    out = format_handoff(
        _min_sp(),
        _min_ap(),
        "본문",
        final_hook="2026년 기준 30% 상승 동결 결정 발표 헤드",  # weak_hook=False
        strategy_os={"positioning": {"one_liner": ""}, "hook_library": [], "banned_style": []},
        linter_labels={"flags": {"missing_context_flag": False, "weak_ending_flag": False,
                                   "generic_cta_flag": False, "ai_tone_flag": False}},
    )
    assert "## 시스템이 감지한 약한 지점" not in out
    assert "## 계정 톤 (참고)" not in out
