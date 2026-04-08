"""
텔레그램 서비스 테스트
======================
콜백 파싱, 승인 카드 빌드를 테스트합니다.
"""

import pytest
from app.services.telegram_service import (
    parse_callback_data, build_approval_card, build_inline_keyboard,
    build_hold_card,
)
from app.models.content import (
    Draft, ContentCategory, RiskLevel, ApprovalStatus, SourceItem,
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


class TestBuildHoldCardKoreanSection:
    """
    Phase A.1 — hold 카드 한국어 보조 섹션 테스트.
    AI 호출 없이 source_item.language 만 보고 섹션이 붙는지 확인.
    기존 영어 섹션(Title/Preview/Score/Source)은 그대로 유지되어야 한다.
    """

    def _make_source(self, *, language: str, source_text: str,
                     title: str = "테스트 제목", score: int = 50) -> SourceItem:
        item = SourceItem(
            id=1,
            title=title,
            url="https://example.com/article",
            source_text=source_text,
            source_type="manual",
            language=language,
        )
        item.candidate_score = score
        return item

    def test_korean_source_has_korean_excerpt_section(self):
        item = self._make_source(
            language="ko",
            source_text=(
                "한국 반도체 수출이 미국과 중국 사이에서 압박을 받고 있다. "
                "삼성과 SK하이닉스는 정책 변화에 대응 중이다."
            ),
        )
        card = build_hold_card(item)
        # 한국어 섹션 존재
        assert "🇰🇷" in card
        assert "한국어 원문 발췌" in card
        # 기존 영어 섹션은 유지
        assert "<b>Title:</b>" in card
        assert "<b>Preview:</b>" in card
        assert "Heuristic Score" in card
        # 비한국어 경고 문구는 나오면 안 됨
        assert "번역 없음" not in card

    def test_korean_source_cuts_at_first_sentence_ending(self):
        item = self._make_source(
            language="ko",
            source_text="한국 경제가 회복되고 있다. 그 다음 문장은 잘려야 한다.",
        )
        card = build_hold_card(item)
        assert "한국 경제가 회복되고 있다." in card

    def test_english_source_has_no_translation_warning(self):
        item = self._make_source(
            language="en",
            source_text="Korea semiconductor policy reform for global chip supply.",
        )
        card = build_hold_card(item)
        assert "🇰🇷" in card
        assert "번역 없음" in card
        assert "language=en" in card
        # 영어 원문 섹션은 유지
        assert "<b>Preview:</b>" in card
        # 한국어 발췌 라벨은 나오면 안 됨
        assert "한국어 원문 발췌" not in card

    def test_empty_language_fallback_to_unknown(self):
        item = self._make_source(
            language="",
            source_text="Some foreign text without language tag.",
        )
        card = build_hold_card(item)
        assert "🇰🇷" in card
        assert "번역 없음" in card
        assert "language=unknown" in card

    def test_korean_empty_text_fallback(self):
        item = self._make_source(language="ko", source_text="")
        card = build_hold_card(item)
        assert "🇰🇷" in card
        assert "한국어 원문 발췌" in card
        assert "(원문 비어 있음)" in card

    def test_existing_english_sections_preserved(self):
        # 스펙: "기존 영어 섹션 삭제 금지, 한국어 섹션은 추가만"
        item = self._make_source(
            language="ko",
            source_text="한국어 원문 내용.",
        )
        card = build_hold_card(item)
        for must_have in (
            "HOLD QUEUE (Phase A)",
            "<b>Title:</b>",
            "<b>Preview:</b>",
            "Heuristic Score",
            "Source ID",
            "Status: hold",
        ):
            assert must_have in card, f"기존 섹션 손실: {must_have}"
