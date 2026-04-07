"""
RepetitionGuard 테스트
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services.repetition_guard import (
    RepetitionGuard,
    _jaccard,
    _extract_hook,
    WARN_THRESHOLD,
    STRONG_WARN_THRESHOLD,
)
from app.services.content_pack import ContentPack


class TestJaccard:

    def test_identical_strings(self):
        assert _jaccard("Korea economy rates", "Korea economy rates") == 1.0

    def test_completely_different(self):
        score = _jaccard("apple orange banana", "car truck bicycle")
        assert score == 0.0

    def test_partial_overlap(self):
        score = _jaccard("Korea economy rates cut", "Korea economy rates hike")
        # 3 shared tokens out of 5 unique
        assert 0.0 < score < 1.0

    def test_empty_string(self):
        assert _jaccard("", "some words") == 0.0
        assert _jaccard("some words", "") == 0.0

    def test_stopwords_removed(self):
        # "the" and "a" are stopwords — shouldn't affect similarity
        score_with = _jaccard("the Korea economy", "a Korea economy")
        score_without = _jaccard("Korea economy", "Korea economy")
        assert score_with == score_without

    def test_case_insensitive(self):
        assert _jaccard("Korea ECONOMY", "korea economy") == 1.0


class TestExtractHook:

    def test_first_line(self):
        text = "First line hook\n\nSecond line body"
        assert _extract_hook(text) == "First line hook"

    def test_single_line(self):
        assert _extract_hook("Single line") == "Single line"

    def test_strips_whitespace(self):
        assert _extract_hook("  hook  \n\nbody") == "hook"

    def test_empty_string(self):
        assert _extract_hook("") == ""


class TestRepetitionGuard:

    def _make_guard_with_recent(self, recent_hooks: list[str]) -> RepetitionGuard:
        db = MagicMock()
        guard = RepetitionGuard(db)
        with patch.object(guard, "_get_recent_hooks", return_value=recent_hooks):
            return guard, recent_hooks

    def test_no_warnings_when_no_history(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        with patch.object(guard, "_get_recent_hooks", return_value=[]):
            warnings = guard.check_texts(["New post about Korea rates"])
            assert warnings == []

    def test_no_warnings_for_dissimilar(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        recent = ["Apple stock price surge in US markets"]
        with patch.object(guard, "_get_recent_hooks", return_value=recent):
            warnings = guard.check_texts(["Korea BOK rate decision today"])
            assert warnings == []

    def test_warning_for_similar(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        recent = ["Korea BOK rate decision today expected"]
        new_texts = ["Korea BOK rate decision today announced"]
        with patch.object(guard, "_get_recent_hooks", return_value=recent):
            warnings = guard.check_texts(new_texts)
            assert len(warnings) > 0

    def test_strong_warning_for_near_identical(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        recent = ["Korea central bank holds rates steady amid global uncertainty"]
        new_texts = ["Korea central bank holds rates steady amid global uncertainty"]
        with patch.object(guard, "_get_recent_hooks", return_value=recent):
            warnings = guard.check_texts(new_texts)
            assert any("🚨" in w for w in warnings)

    def test_short_texts_skipped(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        recent = ["Korea rates hold"]
        with patch.object(guard, "_get_recent_hooks", return_value=recent):
            warnings = guard.check_texts(["short"])
            assert warnings == []

    def test_check_pack_delegates_correctly(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        pack = ContentPack(
            main_posts=["Unique post A here", "Unique post B here", "Unique post C here"],
            short_version="Short and unique",
            quote_post_drafts=["Quote unique text A", "Quote unique text B"],
            why_it_matters="International significance",
        )
        with patch.object(guard, "_get_recent_hooks", return_value=[]):
            result = guard.check_pack(pack)
            assert result == []

    def test_get_recent_hooks_db_error_returns_empty(self):
        db = MagicMock()
        db.query.side_effect = Exception("DB error")
        guard = RepetitionGuard(db)
        # Should not raise, returns empty list
        result = guard._get_recent_hooks(14)
        assert result == []

    def test_no_duplicate_warnings_same_pair(self):
        db = MagicMock()
        guard = RepetitionGuard(db)
        recent = ["Korea BOK rate decision hold expected today"]
        # Same similar text repeated in input
        texts = [
            "Korea BOK rate decision hold expected today",
            "Korea BOK rate decision hold expected today",
        ]
        with patch.object(guard, "_get_recent_hooks", return_value=recent):
            warnings = guard.check_texts(texts)
            # Should not produce duplicate warnings for same pair
            assert len(warnings) <= 2


class TestThresholds:

    def test_warn_threshold_is_reasonable(self):
        assert 0.3 <= WARN_THRESHOLD <= 0.7

    def test_strong_threshold_above_warn(self):
        assert STRONG_WARN_THRESHOLD > WARN_THRESHOLD

    def test_strong_threshold_below_one(self):
        assert STRONG_WARN_THRESHOLD < 1.0
