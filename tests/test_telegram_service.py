"""
텔레그램 서비스 테스트
======================
콜백 파싱, 승인 카드 빌드를 테스트합니다.
"""

import types
import pytest
from app.services.telegram_service import (
    parse_callback_data, build_approval_card, build_inline_keyboard,
    _recommended_action,
)
from app.services.advisory import draft_advisory
from app.models.content import (
    Draft, ContentCategory, RiskLevel, ApprovalStatus,
)


def _mock_draft(risk: RiskLevel) -> "Draft":
    """Draft 인스턴스 대체 — _recommended_action 은 risk_level 만 읽는다."""
    return types.SimpleNamespace(risk_level=risk)  # type: ignore[return-value]


class TestParseCallbackData:
    def test_valid_approve(self):
        result = parse_callback_data("approve:42")
        assert result == ("approve", 42)

    def test_valid_reject(self):
        result = parse_callback_data("reject:1")
        assert result == ("reject", 1)

    def test_valid_defer(self):
        result = parse_callback_data("defer:100")
        assert result == ("defer", 100)

    def test_valid_regenerate(self):
        result = parse_callback_data("regenerate:5")
        assert result == ("regenerate", 5)

    def test_invalid_action(self):
        result = parse_callback_data("delete:42")
        assert result is None

    def test_invalid_format_no_colon(self):
        result = parse_callback_data("approve42")
        assert result is None

    def test_invalid_format_too_many_parts(self):
        result = parse_callback_data("approve:42:extra")
        assert result is None

    def test_invalid_id_not_number(self):
        result = parse_callback_data("approve:abc")
        assert result is None

    def test_empty_string(self):
        result = parse_callback_data("")
        assert result is None


class TestBuildInlineKeyboard:
    def test_keyboard_has_buttons(self):
        kb = build_inline_keyboard(42)
        assert "inline_keyboard" in kb
        rows = kb["inline_keyboard"]
        assert len(rows) == 2  # 2줄

        # 첫 줄: Approve, Reject
        assert len(rows[0]) == 2
        assert rows[0][0]["callback_data"] == "approve:42"
        assert rows[0][1]["callback_data"] == "reject:42"

        # 둘째 줄: Defer, Regenerate
        assert rows[1][0]["callback_data"] == "defer:42"
        assert rows[1][1]["callback_data"] == "regenerate:42"


class TestRecommendedActionQualityGate:
    """
    _recommended_action 이 품질 점수를 존중하는지 회귀 확인.

    과거 버그: 위험 LOW 이면 품질 20/100 이어도 '✅ 승인 가능' 이 떴고,
    같은 카드에 '5대 기준 품질 분석 20/100' + '초안 우선순위 🔴 우선' +
    '추천 ✅ 승인 가능' 이 동시에 표시돼 서로 충돌했다.
    """

    # ── quality_action == "reject" (5-criteria total < 50) ─────────────────
    def test_quality_reject_low_risk_not_approve(self):
        """품질 거절이면 위험 LOW 이어도 '승인 가능' 이 뜨면 안 된다."""
        rec = _recommended_action(_mock_draft(RiskLevel.LOW), quality_action="reject")
        assert "승인 가능" not in rec
        assert "거절 권장" in rec

    def test_quality_reject_medium_risk_still_reject(self):
        rec = _recommended_action(_mock_draft(RiskLevel.MEDIUM), quality_action="reject")
        assert "거절 권장" in rec

    def test_quality_reject_high_risk_still_reject(self):
        rec = _recommended_action(_mock_draft(RiskLevel.HIGH), quality_action="reject")
        assert "거절 권장" in rec

    # ── quality_action == "warn" (50 ≤ total < 70) ─────────────────────────
    def test_quality_warn_low_risk_review(self):
        rec = _recommended_action(_mock_draft(RiskLevel.LOW), quality_action="warn")
        assert "승인 가능" not in rec
        assert "검토" in rec

    def test_quality_warn_high_risk_reject(self):
        """품질 경고 + 고위험 = 거절 권장 (가장 보수적)."""
        rec = _recommended_action(_mock_draft(RiskLevel.HIGH), quality_action="warn")
        assert "거절 권장" in rec

    # ── quality_action == "pass" (total ≥ 70) ──────────────────────────────
    def test_quality_pass_low_risk_approve(self):
        rec = _recommended_action(_mock_draft(RiskLevel.LOW), quality_action="pass")
        assert "승인 가능" in rec

    def test_quality_pass_medium_risk_review(self):
        rec = _recommended_action(_mock_draft(RiskLevel.MEDIUM), quality_action="pass")
        assert "검토 권장" in rec

    def test_quality_pass_high_risk_cautious(self):
        rec = _recommended_action(_mock_draft(RiskLevel.HIGH), quality_action="pass")
        assert "신중" in rec
        assert "승인 가능" not in rec

    # ── backward compat: quality_action is None → risk-only 폴백 ───────────
    def test_none_quality_low_risk_fallback_approve(self):
        """scorer 실패 시에는 과거 동작(risk LOW → 승인 가능) 유지."""
        rec = _recommended_action(_mock_draft(RiskLevel.LOW), quality_action=None)
        assert "승인 가능" in rec

    def test_none_quality_high_risk_fallback_cautious(self):
        rec = _recommended_action(_mock_draft(RiskLevel.HIGH), quality_action=None)
        assert "신중" in rec


class TestDraftAdvisoryUrgencyAxis:
    """
    draft_advisory 가 '품질' 이 아니라 '시의성/운영 중요도' 축으로
    동작하는지 확인. 과거 버그는 score_draft(=품질) 을 우선순위로
    라벨링해 카드 품질 점수와 충돌했다.
    """

    def test_manual_is_high_priority(self):
        """운영자 직접 입력 = 시의성 있음으로 가정."""
        label = draft_advisory("한국은행 기준금리 동결", "본문", "manual")
        assert "우선" in label

    def test_community_input_is_high_priority(self):
        label = draft_advisory("fmkorea 반응", "본문", "community_input")
        assert "우선" in label

    def test_naver_auto_is_not_high_priority(self):
        """자동수집 배치는 🔴 로 올라오면 안 된다."""
        label = draft_advisory("자동수집", "본문", "naver_auto")
        assert "우선" not in label

    def test_news_link_medium(self):
        label = draft_advisory("일반 기사", "본문", "news_link")
        assert label in ("🟡 보통", "🔴 우선")  # breaking 키워드 없으면 🟡

    def test_breaking_keyword_boost(self):
        """news_link(55) + breaking(+20) = 75 → 🔴 우선."""
        label = draft_advisory("Breaking: 뭐뭐가 발생", "본문", "news_link")
        assert "우선" in label

    def test_속보_keyword_boost(self):
        label = draft_advisory("속보: 한국은행 동결", "본문", "news_link")
        assert "우선" in label

    def test_advisory_does_not_call_quality_scorer(self):
        """
        회귀 방지: draft_advisory 는 이제 score_draft 를 부르지 않는다.
        품질이 낮은 본문이어도 source_type 만으로 🔴 판정이 나와야 한다.
        """
        # 품질적으로 완전히 빈약한 본문
        label = draft_advisory("a", "b", "manual")
        assert "우선" in label  # source_type=manual → 70 → 🔴


class TestCardConsistencyRegression:
    """
    실제 운영에서 본 충돌 케이스 재현 회귀 테스트.

    시나리오 (draft_id=819 가 실제로 찍은 카드):
      - 한국어 hook/body (한국은행 기준금리 동결, 해석·관점이 빈약한 요약)
      - 이전 버그 관측값:
          · 5대 기준 품질 분석: 20/100 (영어 regex 전용이라 한국어는 0점 수렴)
          · 초안 우선순위: 🔴 우선 (score_draft 를 잘못 품질-as-우선순위로 라벨링)
          · 추천: ✅ 승인 가능 (risk=LOW 만 보고 승인)
      - 세 값이 서로 모순.

    수정 이력:
      (1) 2026-04-11 a: draft_advisory 를 시의성 축으로 분리, _recommended_action
          에 품질 게이트 추가.
      (2) 2026-04-11 b: score_5criteria 에 한국어 패턴 추가 → 한국어 본문도 정상
          평가. 이 BOK 본문은 해석/글로벌/팔로워/재방문 신호가 모두 부실해 점수가
          30 근처로 오르지만 여전히 reject 영역(<50)에 머문다 — 즉 "빈약한 한국어
          요약은 여전히 거절 권장" 이라는 운영 불변량이 유지된다.

    불변량:
      - 초안 우선순위: source_type=manual → 🔴 (시의성 축)
      - 추천: 품질 reject 이므로 ❌ 거절 권장 (승인 가능 아님)
    """

    def test_korean_bok_draft_no_longer_recommends_approve(self):
        from app.services.quality_scorer import score_5criteria

        hook = "한국은행, 7회 연속 기준금리 2.75% 동결"
        body = (
            "가계부채 증가 속도가 둔화되고 내수가 부진한 상황에서 한국은행은 "
            "안정성을 우선시하며 통화정책의 신중함을 보였다."
        )

        result = score_5criteria(hook, body)
        # 해석/글로벌/팔로워/재방문 신호가 없는 한국어 요약이므로 reject(<50) 여야 한다.
        # 한국어 패턴 추가 후에도 이 불변량은 유지된다. 만약 이 본문이 warn/pass 로
        # 올라온다면 한국어 패턴이 너무 느슨해 저품질 요약도 통과시키는 것이므로
        # 패턴을 다시 조여야 한다.
        assert result["action"] == "reject", (
            f"회귀 전제 깨짐: 해석 없는 한국어 요약이 더 이상 reject 가 아님. "
            f"total={result['total']}. 한국어 패턴이 너무 느슨함. scorer 를 다시 조여라."
        )

        rec = _recommended_action(
            _mock_draft(RiskLevel.LOW),
            quality_action=result["action"],
        )
        assert "승인 가능" not in rec, (
            f"품질 {result['total']}/100 (reject) 인데 추천이 '{rec}' 로 "
            f"여전히 승인 가능. 게이트가 안 걸리고 있음."
        )
        assert "거절 권장" in rec

        # 초안 우선순위는 여전히 🔴 로 뜰 수 있다 — 시의성 축이므로
        adv = draft_advisory(hook, body, "manual")
        assert adv == "🔴 우선"
        # 하지만 이게 추천을 오버라이드하지 않는다 (위 assertion 이 그 증명)
