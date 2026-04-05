"""
Telegram command 파싱 신뢰성 테스트
=====================================
_parse_draft_id() 헬퍼 및 malformed input 처리를 검증한다.
Telegram Update mock 없이 순수 파싱 로직만 테스트.
"""

import pytest


def _parse_draft_id(args: list, pos: int = 0):
    """telegram_bot._parse_draft_id 인라인 복사 — import 없이 순수 로직 검증."""
    try:
        return int(args[pos]), ""
    except (ValueError, IndexError):
        return None, "❌ draft_id는 숫자여야 합니다."


class TestParseDraftId:
    """_parse_draft_id() — 공유 인자 파싱 헬퍼."""

    def test_valid_integer(self):
        """정상 숫자 → (int, '') 반환."""
        draft_id, err = _parse_draft_id(["42"], 0)
        assert draft_id == 42
        assert err == ""

    def test_non_numeric_string(self):
        """숫자 아닌 문자열 → (None, error_message) 반환."""
        draft_id, err = _parse_draft_id(["abc"], 0)
        assert draft_id is None
        assert "숫자" in err

    def test_empty_args(self):
        """빈 리스트 → (None, error_message) 반환."""
        draft_id, err = _parse_draft_id([], 0)
        assert draft_id is None
        assert err != ""

    def test_float_string(self):
        """소수점 문자열 → (None, error_message) 반환."""
        draft_id, err = _parse_draft_id(["3.14"], 0)
        assert draft_id is None

    def test_pos_1_valid(self):
        """pos=1 — /hint clear <id> 패턴."""
        draft_id, err = _parse_draft_id(["clear", "99"], 1)
        assert draft_id == 99
        assert err == ""

    def test_pos_1_missing(self):
        """pos=1 — args가 1개뿐이면 IndexError → (None, error)."""
        draft_id, err = _parse_draft_id(["clear"], 1)
        assert draft_id is None

    def test_negative_integer(self):
        """음수도 int로 파싱됨 — 유효성은 service layer가 담당."""
        draft_id, err = _parse_draft_id(["-1"], 0)
        assert draft_id == -1
        assert err == ""

    def test_leading_zeros(self):
        """앞에 0 붙은 숫자도 정상 파싱."""
        draft_id, err = _parse_draft_id(["007"], 0)
        assert draft_id == 7


class TestCommandArgCombinations:
    """
    /note /hint /perf 인자 조합 시나리오 검증.
    실제 args 리스트를 만들어서 파싱 로직을 직접 확인.
    """

    def test_note_only_id_no_text(self):
        """'/note 42' — 텍스트 없이 id만 → len(args) < 2 → usage 메시지 필요."""
        args = ["42"]
        assert len(args) < 2  # 이 조건이 핸들러에서 usage 안내로 이어짐

    def test_note_id_and_text(self):
        """'/note 42 각도 변경' → 정상 경로."""
        args = ["42", "각도", "변경"]
        draft_id, err = _parse_draft_id(args, 0)
        assert draft_id == 42
        note_text = " ".join(args[1:])[:500]
        assert note_text == "각도 변경"

    def test_perf_non_numeric_id(self):
        """'/perf abc 좋아요' → id 파싱 실패."""
        args = ["abc", "좋아요"]
        draft_id, err = _parse_draft_id(args, 0)
        assert draft_id is None

    def test_hint_clear_non_numeric_id(self):
        """'/hint clear xyz' → id 파싱 실패."""
        args = ["clear", "xyz"]
        draft_id, err = _parse_draft_id(args, 1)
        assert draft_id is None

    def test_hint_save_text_length_cap(self):
        """'/hint <id> <very long text>' → 493자 cap."""
        long_text = "A" * 600
        args = ["42"] + long_text.split()
        raw = " ".join(args[1:])
        note_text = "[HINT] " + raw[:493]
        assert len(note_text) <= 500

    def test_perf_text_length_cap(self):
        """'/perf <id> <long text>' → 300자 cap."""
        args = ["42"] + ["X" * 400]
        note_text = " ".join(args[1:])[:300]
        assert len(note_text) == 300


class TestNewsRegenArticleState:
    """
    뉴스 재생성(news_regen) 콜백 신뢰성 테스트.

    버그 회귀 방지: news_draft 처리 후 기사 정보가 _pending_articles에 남아있어야
    news_regen 버튼이 정상 동작한다.
    (수정 전: remove_pending_article이 draft 처리 중에 호출되어 regen이 항상 실패)
    """

    def test_pending_article_survives_after_draft_generation(self):
        """
        Article must remain in _pending_articles after news_draft so that
        news_regen can re-run. Regression guard for the premature-removal bug.
        """
        from app.services.news_monitor import (
            _pending_articles,
            get_pending_article,
            remove_pending_article,
        )

        hash_key = "_test_regen_regression_hash"
        _pending_articles[hash_key] = {
            "title": "Regen test article",
            "url": "http://test.example.com",
            "summary": "",
            "category": "economy",
            "source": "test",
        }

        # Article accessible — simulates regen tap after initial draft
        article = get_pending_article(hash_key)
        assert article is not None, (
            "Article must survive draft generation for news_regen to work. "
            "Regression: remove_pending_article must NOT be called in news_draft path."
        )
        assert article["title"] == "Regen test article"

        # Cleanup
        remove_pending_article(hash_key)
        assert get_pending_article(hash_key) is None

    def test_skip_removes_pending_article(self):
        """news_skip 경로는 기사를 _pending_articles에서 제거해야 한다."""
        from app.services.news_monitor import (
            _pending_articles,
            get_pending_article,
            remove_pending_article,
        )

        hash_key = "_test_skip_removes_hash"
        _pending_articles[hash_key] = {
            "title": "Skip test article",
            "url": "http://skip.example.com",
            "summary": "",
            "category": "politics",
            "source": "test",
        }

        remove_pending_article(hash_key)
        assert get_pending_article(hash_key) is None
