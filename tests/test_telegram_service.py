"""
텔레그램 서비스 테스트
======================
콜백 파싱, 승인 카드 빌드를 테스트합니다.
"""

import pytest
from app.services.telegram_service import (
    parse_callback_data, build_approval_card, build_inline_keyboard,
)
from app.models.content import (
    Draft, ContentCategory, RiskLevel, ApprovalStatus,
)


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


class TestBuildApprovalCardQualityAdvisory:
    """quality advisory (score_draft < 40 경고) 테스트."""

    def _make_draft(self, hook: str, body: str):
        from unittest.mock import MagicMock
        draft = MagicMock()
        draft.id = 1
        draft.version = 1
        draft.hook = hook
        draft.body = body
        draft.thread_continuation = None
        draft.category = ContentCategory.ECONOMY
        draft.risk_level = RiskLevel.LOW
        draft.risk_reasoning = None
        draft.ai_rationale = None
        draft.community_warning = None
        draft.predicted_publish_at = None
        draft.prediction_reasoning = None
        draft.text_length = len(body)
        return draft

    def test_low_score_shows_warning(self):
        """score_draft < 40 이면 품질 경고가 카드에 포함된다."""
        # 낮은 점수 조건:
        # - 훅에 숫자 없음 (0점)
        # - "South Korea"로 시작 (0점, bad start)
        # - CTA 없음 (0점)
        # - body 270자 이하 (+15)
        # - "you" 없음 (0점)
        # - 구체적 맥락 없음 (0점)
        # - 일반 입력 면제 (+10)
        # = 25/100 → < 40
        hook = "South Korea changes policy"
        body = "This is a short post with no special elements."
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert "품질 경고" in card
        assert "/100" in card
        assert "참고용" in card

    def test_high_score_no_warning(self):
        """score_draft >= 40 이면 품질 경고가 카드에 없다."""
        # 높은 점수 조건:
        # - 훅에 숫자 (+20)
        # - 좋은 시작어 (+20)
        # - "you"와 CTA (+15 +10)
        # - Korea 언급 (+10)
        # - 일반 면제 (+10)
        # = 85/100 → >= 40
        hook = "BOK cuts rates 25bp — what you need to know"
        body = "Korea's central bank just cut rates. What does this mean for you and your investments?"
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert "품질 경고" not in card

    def test_score_failure_does_not_crash_card(self):
        """score_draft가 예외를 던져도 카드 자체는 정상 생성된다."""
        import unittest.mock as mock
        hook = "BOK raises rates"
        body = "Short body."
        draft = self._make_draft(hook, body)
        with mock.patch(
            "app.services.quality_scorer.score_draft",
            side_effect=RuntimeError("scorer error"),
        ):
            card = build_approval_card(draft)
        # 경고 없이 카드가 정상 생성됨
        assert "품질 경고" not in card
        assert "NEW DRAFT FOR REVIEW" in card


class TestBuildApprovalCardVoiceGuard:
    """VoiceGuard 단일 초안 연결 테스트 (Layer 2)."""

    def _make_draft(self, hook: str, body: str):
        from unittest.mock import MagicMock
        draft = MagicMock()
        draft.id = 1
        draft.version = 1
        draft.hook = hook
        draft.body = body
        draft.thread_continuation = None
        draft.category = ContentCategory.ECONOMY
        draft.risk_level = RiskLevel.LOW
        draft.risk_reasoning = None
        draft.ai_rationale = None
        draft.community_warning = None
        draft.predicted_publish_at = None
        draft.prediction_reasoning = None
        draft.text_length = len(body)
        return draft

    def test_voice_warning_shown_when_ai_phrase_present(self):
        """금지 표현 포함 시 Voice 경고가 카드에 표시된다."""
        hook = "BOK raises rates 25bp"
        body = "Furthermore, this underscores Korea's broader challenge. Follow."
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert "Voice 경고" in card

    def test_no_voice_warning_for_clean_text(self):
        """금지 표현 없으면 Voice 경고가 카드에 없다."""
        hook = "BOK cuts 25bp — what you need to know"
        body = "The central bank just cut rates 25bp. You should watch this. Follow."
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert "Voice 경고" not in card

    def test_voice_guard_failure_does_not_crash_card(self):
        """VoiceGuard 예외 시 카드 정상 생성된다."""
        import unittest.mock as mock
        hook = "BOK raises rates"
        body = "Short body."
        draft = self._make_draft(hook, body)
        with mock.patch(
            "app.services.voice_guard.check_voice",
            side_effect=RuntimeError("voice error"),
        ):
            card = build_approval_card(draft)
        assert "Voice 경고" not in card
        assert "NEW DRAFT FOR REVIEW" in card
