"""
post_linter 라벨러 테스트.

Linter 는 라벨만 리턴하고 재작성 없다. 따라서 테스트는:
- 각 체크가 기대한 bool/enum 을 내는가
- 스키마 완전성
- 예외가 들어와도 전체 dict 리턴 (fail-open)
"""
import pytest

from app.services import post_linter
from app.services.post_linter import (
    LINTER_VERSION,
    run_post_linter,
    _check_linkless_context,
    _check_why_now,
    _check_company_context,
    _check_ending,
    _check_frame_rt,
    _check_emoji,
    _check_flags,
)


TOP_KEYS = {
    "linter_version",
    "linkless_context",
    "why_now",
    "company_context",
    "ending",
    "frame_rt",
    "emoji",
    "flags",
    "meta",
}


# ─── linkless_context ──────────────────────────────────────────────────────

def test_linkless_complete_ko():
    r = _check_linkless_context(
        hook="한국은행, 6월 18일 기준금리 동결 발표",
        body="한국은행이 2026년 6월 18일 기준금리를 동결한다고 발표했다. 국내 소비자물가 영향이 논의됐다.",
    )
    assert r["who_present"] is True
    assert r["what_present"] is True
    assert r["when_present"] is True
    assert r["market_or_country_present"] is True
    assert r["linkless_context_complete"] is True


def test_linkless_missing_when():
    r = _check_linkless_context(
        hook="BBC 보고서 공개",
        body="BBC 는 한국 주요 기업의 주가 변동 패턴을 분석했다고 공개했다.",
    )
    assert r["who_present"] is True
    assert r["what_present"] is True
    # 날짜 앵커 / 지금/오늘 류가 없으므로 False 기대
    assert r["when_present"] is False
    assert r["linkless_context_complete"] is False


def test_linkless_missing_market():
    r = _check_linkless_context(
        hook="발표",
        body="오늘 기업이 제품을 출시했다.",
    )
    assert r["market_or_country_present"] is False
    assert r["linkless_context_complete"] is False


# ─── why_now ───────────────────────────────────────────────────────────────

def test_why_now_applies_policy():
    r = _check_why_now("오늘 금융위가 가이드라인을 발표했다.", category="policy")
    assert r["applies"] is True
    assert r["why_now_present"] is True
    assert r["stage_status_present"] is True


def test_why_now_not_applies_evergreen():
    r = _check_why_now("한국 떡볶이의 역사 개관.", category="evergreen")
    assert r["applies"] is False


def test_why_now_date_anchor_patterns():
    r = _check_why_now("2026년 4월 20일 시행 예정이다.", category="regulation")
    assert r["date_anchor_present"] is True
    assert r["stage_status_present"] is True


def test_why_now_no_category():
    r = _check_why_now("문장 하나.", category=None)
    assert r["applies"] is False


# ─── company_context ───────────────────────────────────────────────────────

def test_company_context_needed_and_used():
    r = _check_company_context("NVIDIA(엔비디아)는 AI 가속기 시장을 주도한다.")
    assert r["company_context_needed"] is True
    # 괄호 수식 있음
    assert r["company_context_used"] is True
    assert r["entities_requiring_context"] == []


def test_company_context_missing():
    r = _check_company_context("NVIDIA 주가가 올랐다. BMW 는 조용했다.")
    assert r["company_context_needed"] is True
    assert r["company_context_used"] is False
    assert "NVIDIA" in r["entities_requiring_context"]


def test_company_context_no_entity():
    r = _check_company_context("오늘 날씨가 좋다.")
    assert r["company_context_needed"] is False
    assert r["entities_requiring_context"] == []


def test_company_context_caps_at_five():
    txt = "APPLE GOOGLE META AMAZON NVIDIA TESLA INTEL AMD QUALCOMM BMW"
    r = _check_company_context(txt)
    assert len(r["entities_requiring_context"]) <= 5


# ─── ending ────────────────────────────────────────────────────────────────

def test_ending_question_only():
    r = _check_ending("이번 결정이 시장에 어떤 영향을 줄까?")
    assert r["ending_type"] == "question_only"
    assert r["weak_ending_flag"] is True


def test_ending_position_plus_question():
    body = (
        "한국은행은 이번에도 동결을 선택했다. "
        "이 결정은 경기 하락 위험과 물가 압력 사이에서 절충으로 보인다. "
        "다음 분기에도 같은 경로를 유지할까?"
    )
    r = _check_ending(body)
    assert r["ending_type"] == "position_plus_question"


def test_ending_scenario():
    r = _check_ending("만약 이 정책이 연말까지 시행된다면, 중소기업 부담이 커질 수 있다.")
    assert r["ending_type"] == "scenario"


def test_ending_warning():
    r = _check_ending("⚠️ 주가 급락 위험. 단기 접근에 조심이 필요하다.")
    assert r["ending_type"] == "warning"


def test_ending_checklist():
    r = _check_ending(
        "체크 포인트:\n"
        "1. 금리 경로\n"
        "2. 환율 방향\n"
        "3. 외국인 자금 흐름"
    )
    assert r["ending_type"] == "checklist"


# ─── frame_rt ──────────────────────────────────────────────────────────────

def test_frame_rt_triggers_comparison_and_number():
    r = _check_frame_rt(
        hook="지난해 대비 2배",
        body="매출이 전년 대비 2배 늘었다. 업계 평균보다 30% 높다.",
        pack={"angle_pack": {"frame_type": "comparison"}},
    )
    assert r["frame_type"] == "comparison"
    assert "comparison" in r["rt_trigger_type"]
    assert "specific_number" in r["rt_trigger_type"]


def test_frame_rt_korea_angle_true():
    r = _check_frame_rt("한국 시장", "한국의 특이 구조가 드러난다.", pack=None)
    assert r["korea_angle_used"] is True
    assert r["identity_signal_present"] is True


def test_frame_rt_no_pack():
    r = _check_frame_rt("hook", "body", pack=None)
    assert r["frame_type"] is None
    assert isinstance(r["rt_trigger_type"], list)


# ─── emoji ─────────────────────────────────────────────────────────────────

def test_emoji_none():
    r = _check_emoji("hook", "body 본문")
    assert r["emoji_count"] == 0
    assert r["emoji_function"] == "none"


def test_emoji_structure():
    r = _check_emoji("⚠️ 주의", "📌 확인 필요\n✅ 완료")
    assert r["emoji_count"] >= 2
    assert r["emoji_function"] == "structure"


def test_emoji_other():
    r = _check_emoji("hook", "오늘은 기분이 🎉🥳")
    assert r["emoji_count"] >= 1
    assert r["emoji_function"] == "other"


# ─── flags ─────────────────────────────────────────────────────────────────

def test_flags_ai_tone_from_strategy_os(monkeypatch):
    """banned_style 인자 명시 시 Strategy OS 조회 없이 바로 사용."""
    r = _check_flags(
        hook="furthermore this is important",
        body="we must delve into nuanced discussion.",
        linkless={"linkless_context_complete": True},
        ending={"weak_ending_flag": False},
        banned_style=("furthermore", "delve into"),
    )
    assert r["ai_tone_flag"] is True


def test_flags_weak_share_no_numbers():
    r = _check_flags(
        hook="일반적인 진술",
        body="흥미로운 일이 있었다. 주목할 만한 변화다.",
        linkless={"linkless_context_complete": False},
        ending={"weak_ending_flag": False},
        banned_style=(),
    )
    assert r["weak_share_value_flag"] is True
    assert r["missing_context_flag"] is True


def test_flags_generic_cta():
    r = _check_flags(
        hook="소식",
        body="자세한 내용은 팔로우 해주세요.",
        linkless={"linkless_context_complete": True},
        ending={"weak_ending_flag": False},
        banned_style=(),
    )
    assert r["generic_cta_flag"] is True


def test_flags_none_triggered():
    r = _check_flags(
        hook="구체 수치 30% 증가",
        body="서울 매출이 전년 대비 30% 증가했다.",
        linkless={"linkless_context_complete": True},
        ending={"weak_ending_flag": False},
        banned_style=(),
    )
    assert r["ai_tone_flag"] is False
    assert r["weak_share_value_flag"] is False
    assert r["missing_context_flag"] is False
    assert r["weak_ending_flag"] is False
    assert r["generic_cta_flag"] is False


# ─── 통합 run_post_linter ─────────────────────────────────────────────────

def test_run_post_linter_full_schema():
    out = run_post_linter(
        hook="한국은행 6월 18일 기준금리 동결",
        body="한국은행은 2026년 6월 18일 기준금리를 동결한다고 발표했다. 시장 영향은 제한적이다.",
        pack={"angle_pack": {"frame_type": "policy_update"}},
        category="policy",
        title="한국은행 금리 결정",
    )
    assert out["linter_version"] == LINTER_VERSION
    assert set(out.keys()) == TOP_KEYS
    assert out["linkless_context"] is not None
    assert out["why_now"] is not None
    assert out["company_context"] is not None
    assert out["ending"] is not None
    assert out["frame_rt"]["frame_type"] == "policy_update"
    assert out["emoji"] is not None
    assert out["flags"] is not None
    assert out["meta"]["source_hook_len"] > 0
    assert out["meta"]["source_body_len"] > 0


def test_run_post_linter_fail_open_on_empty():
    out = run_post_linter(hook="", body="", pack=None, category=None, title=None)
    # 모든 영역이 채워진 dict 을 리턴해야 한다 (None 허용 필드는 내부값은 None 가능)
    assert set(out.keys()) == TOP_KEYS
    assert out["linter_version"] == LINTER_VERSION
    # 빈 본문에서도 스키마 자체는 온전해야 함
    assert isinstance(out["linkless_context"], dict)
    assert isinstance(out["why_now"], dict)


def test_run_post_linter_strategy_os_failure_uses_fallback(monkeypatch):
    """load_strategy_os 가 예외 던져도 fallback 써서 flags 생성."""
    from app.services import strategy_os as so
    def _boom(path=None):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(so, "load_strategy_os", _boom, raising=True)
    out = run_post_linter(
        hook="furthermore",
        body="we must delve into this nuanced matter.",
        pack=None, category=None, title=None,
    )
    assert out["flags"] is not None
    # 영어 fallback 단어가 포함돼 있으므로 ai_tone_flag True 이어야 함
    assert out["flags"]["ai_tone_flag"] is True


def test_run_post_linter_does_not_raise_on_corrupt_pack():
    out = run_post_linter(
        hook="h",
        body="b",
        pack="not a dict",  # type: ignore[arg-type]
        category=123,       # type: ignore[arg-type]
        title=["weird"],    # type: ignore[arg-type]
    )
    assert set(out.keys()) == TOP_KEYS
    assert out["linter_version"] == LINTER_VERSION
