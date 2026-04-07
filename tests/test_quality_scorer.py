"""quality_scorer 테스트"""
import pytest
from app.providers.base import DraftResult
from app.services.quality_scorer import score_draft, should_regenerate, REGEN_THRESHOLD


def _draft(hook: str, body: str) -> DraftResult:
    return DraftResult(hook=hook, body=body)


class TestScoreDraft:
    def test_high_score_good_draft(self):
        d = _draft(
            hook="Korea's household debt hit 105% of GDP. That's not a typo.",
            body="The BOK held rates at 3.5% for the 6th time. Trapped. "
                 "Cut and the won collapses. Hold and debt gets worse. "
                 "If you track Korea, you see what's coming for Asia. Follow.",
        )
        score, _ = score_draft(d)
        assert score >= 60

    def test_penalizes_south_korea_start(self):
        d = _draft(
            hook="South Korea's economy is struggling right now.",
            body="South Korea raised interest rates again. Follow.",
        )
        score, reasons = score_draft(d)
        assert any("South Korea" in r for r in reasons)

    def test_penalizes_banned_words(self):
        d = _draft(
            hook="Furthermore Korea's numbers look bad",
            body="However, it is worth noting that rates rose. Follow.",
        )
        score, reasons = score_draft(d)
        assert any("-15" in r for r in reasons)

    def test_rewards_number_in_hook(self):
        d = _draft(
            hook="18% drop in chip exports. Korea just blinked.",
            body="Samsung output fell 18% QoQ. Your next iPhone might cost more. Follow.",
        )
        score, reasons = score_draft(d)
        assert any("+20" in r for r in reasons)

    def test_rewards_cta(self):
        d = _draft(
            hook="A number nobody talks about.",
            body="Korea debt 105% GDP. Follow to get Korea signals early.",
        )
        score, reasons = score_draft(d)
        assert any("+15" in r for r in reasons)

    def test_penalizes_long_body(self):
        long_body = "x " * 200  # ~400 chars
        d = _draft(hook="Some hook", body=long_body)
        score, reasons = score_draft(d)
        assert any("초과" in r for r in reasons)

    def test_community_input_rewards_sentiment(self):
        d = _draft(
            hook="Korean crypto forums are panicking right now.",
            body="Traders on Korean boards are bearish. Concern is spreading. Follow.",
        )
        score, reasons = score_draft(d, source_type="community_input")
        assert any("+10" in r and "감정" in r for r in reasons)


class TestShouldRegenerate:
    def test_below_threshold(self):
        assert should_regenerate(REGEN_THRESHOLD - 1) is True

    def test_at_threshold(self):
        assert should_regenerate(REGEN_THRESHOLD) is False

    def test_above_threshold(self):
        assert should_regenerate(90) is False
