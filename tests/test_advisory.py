"""
어드바이저리 레이블 테스트
==========================
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.advisory import priority_label, source_advisory, draft_advisory


class TestPriorityLabel:
    """priority_label() 기본 동작."""

    def test_high_score_returns_priority(self):
        assert priority_label(60) == "🔴 우선"
        assert priority_label(80) == "🔴 우선"
        assert priority_label(100) == "🔴 우선"

    def test_medium_score_returns_normal(self):
        assert priority_label(40) == "🟡 보통"
        assert priority_label(50) == "🟡 보통"
        assert priority_label(59) == "🟡 보통"

    def test_low_score_returns_hold(self):
        assert priority_label(0) == "⚪ 보류"
        assert priority_label(20) == "⚪ 보류"
        assert priority_label(39) == "⚪ 보류"

    def test_boundary_60(self):
        assert priority_label(59) == "🟡 보통"
        assert priority_label(60) == "🔴 우선"

    def test_boundary_40(self):
        assert priority_label(39) == "⚪ 보류"
        assert priority_label(40) == "🟡 보통"


class TestSourceAdvisory:
    """source_advisory() — morning_digest 중요도 점수 연동."""

    def test_high_importance_article(self):
        # Fed + US region → normalized score ≥ 60 → 우선
        article = {"title": "Fed raises interest rates amid inflation fears", "summary": "", "region": "US", "category": "economy"}
        label = source_advisory(article)
        assert label in ("🔴 우선", "🟡 보통", "⚪ 보류")
        assert label == "🔴 우선"

    def test_low_importance_article(self):
        article = {"title": "Local restaurant opens new branch", "summary": "", "region": "KR", "category": "community"}
        label = source_advisory(article)
        assert label == "⚪ 보류"

    def test_crypto_category_boosts_score(self):
        # bitcoin + US region + crypto category → normalized score ≥ 60 → 우선
        article = {"title": "Bitcoin ETF decision pending", "summary": "", "region": "US", "category": "crypto"}
        label = source_advisory(article)
        assert label == "🔴 우선"

    def test_empty_article_returns_hold(self):
        label = source_advisory({})
        assert label == "⚪ 보류"

    def test_returns_string_not_empty(self):
        article = {"title": "war sanctions tariff", "summary": "", "region": "US", "category": "politics"}
        label = source_advisory(article)
        assert isinstance(label, str)
        assert len(label) > 0


class TestDraftAdvisory:
    """draft_advisory() — quality_scorer 점수 연동."""

    def test_returns_valid_label(self):
        hook = "3 things Fed officials said that markets missed"
        body = "In Tuesday's testimony, Chair Powell signaled three distinct pivots. The bond market hasn't priced this in yet. Here's what it means for your portfolio."
        label = draft_advisory(hook, body)
        assert label in ("🔴 우선", "🟡 보통", "⚪ 보류")

    def test_empty_draft_returns_valid_label(self):
        label = draft_advisory("", "")
        assert label in ("🔴 우선", "🟡 보통", "⚪ 보류")

    def test_returns_string_on_any_input(self):
        label = draft_advisory("hook text", "body text with some content here")
        assert isinstance(label, str)
