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
    """quality advisory (초안 우선순위 레이블) 테스트."""

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

    def test_advisory_label_shown_in_card(self):
        """초안 우선순위 레이블이 카드에 표시된다."""
        hook = "South Korea changes policy"
        body = "This is a short post with no special elements."
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert "초안 우선순위" in card
        assert "참고용" in card

    def test_advisory_label_contains_valid_value(self):
        """우선순위 레이블이 유효한 값(우선/보통/보류) 중 하나다."""
        hook = "BOK cuts rates 25bp — what you need to know"
        body = "Korea's central bank just cut rates. What does this mean for you and your investments?"
        draft = self._make_draft(hook, body)
        card = build_approval_card(draft)
        assert any(label in card for label in ("우선", "보통", "보류"))

    def test_advisory_failure_does_not_crash_card(self):
        """draft_advisory가 예외를 던져도 카드 자체는 정상 생성된다."""
        import unittest.mock as mock
        hook = "BOK raises rates"
        body = "Short body."
        draft = self._make_draft(hook, body)
        with mock.patch(
            "app.services.advisory.draft_advisory",
            side_effect=RuntimeError("advisory error"),
        ):
            card = build_approval_card(draft)
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


class TestBuildApprovalCardTopicTags:
    """topic_tags 표시 + 글자수 경고 테스트."""

    def _make_draft(self, body: str, topic_tags=None, text_length=None):
        from unittest.mock import MagicMock
        draft = MagicMock()
        draft.id = 1
        draft.version = 1
        draft.hook = "BOK cuts rates 25bp"
        draft.body = body
        draft.thread_continuation = None
        draft.category = ContentCategory.ECONOMY
        draft.risk_level = RiskLevel.LOW
        draft.risk_reasoning = None
        draft.ai_rationale = None
        draft.community_warning = None
        draft.predicted_publish_at = None
        draft.prediction_reasoning = None
        draft.topic_tags = topic_tags
        draft.text_length = text_length if text_length is not None else len(body)
        return draft

    def test_topic_tags_shown_in_card(self):
        """topic_tags JSON 문자열이 있으면 # 해시태그로 카드에 표시된다."""
        import json
        tags = json.dumps(["KoreaEconomy", "#BOK", "RatesWatch"])
        draft = self._make_draft("Some body text.", topic_tags=tags)
        card = build_approval_card(draft)
        assert "#KoreaEconomy" in card
        assert "#BOK" in card
        assert "#RatesWatch" in card
        assert "🏷" in card

    def test_topic_tags_limited_to_five(self):
        """topic_tags가 6개 이상이어도 최대 5개만 표시된다."""
        import json
        tags = json.dumps(["T1", "T2", "T3", "T4", "T5", "T6", "T7"])
        draft = self._make_draft("Some body.", topic_tags=tags)
        card = build_approval_card(draft)
        assert "#T5" in card
        assert "#T6" not in card

    def test_no_topic_tags_section_when_none(self):
        """topic_tags가 None이면 🏷 섹션이 없다."""
        draft = self._make_draft("Some body.", topic_tags=None)
        card = build_approval_card(draft)
        assert "🏷" not in card

    def test_invalid_topic_tags_json_does_not_crash(self):
        """topic_tags가 잘못된 JSON이어도 카드가 정상 생성된다."""
        draft = self._make_draft("Some body.", topic_tags="not-valid-json")
        card = build_approval_card(draft)
        assert "NEW DRAFT FOR REVIEW" in card
        assert "🏷" not in card

    def test_char_count_within_limit_no_warning(self):
        """글자수 280 이하면 초과 경고 없음."""
        draft = self._make_draft("Short post.", text_length=150)
        card = build_approval_card(draft)
        assert "Characters: 150" in card
        assert "X 한도 초과" not in card

    def test_char_count_over_280_shows_warning(self):
        """글자수 281 이상이면 X 한도 초과 경고 표시."""
        draft = self._make_draft("x" * 300, text_length=300)
        card = build_approval_card(draft)
        assert "Characters: 300" in card
        assert "X 한도 초과" in card
        assert "편집 필요" in card

    def test_char_count_exactly_280_no_warning(self):
        """글자수 정확히 280이면 경고 없음."""
        draft = self._make_draft("x" * 280, text_length=280)
        card = build_approval_card(draft)
        assert "Characters: 280" in card
        assert "X 한도 초과" not in card
