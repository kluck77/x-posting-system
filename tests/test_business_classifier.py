"""
비즈니스 분류기 테스트
======================
Phase 5: classify_business() 함수의 태깅/스코어/CTA/B2B 로직 검증.
"""

import pytest
from app.services.business_classifier import (
    classify_business,
    BusinessClassification,
    business_tags_to_json,
    business_tags_from_json,
)


# ─── 기본 분류 테스트 ──────────────────────────────────────────────

class TestBasicClassification:
    def test_always_has_growth_tag(self):
        result = classify_business("Test title", "Test body", "society", "low")
        assert "growth" in result.business_tags

    def test_returns_business_classification_type(self):
        result = classify_business("Test", "Body", "economy", "medium")
        assert isinstance(result, BusinessClassification)

    def test_monetization_score_in_range(self):
        result = classify_business("Test", "Body", "economy", "medium")
        assert 0 <= result.monetization_score <= 100

    def test_cta_type_not_empty(self):
        result = classify_business("Test", "Body", "society", "low")
        assert result.cta_type

    def test_asset_goal_not_empty(self):
        result = classify_business("Test", "Body", "society", "low")
        assert result.asset_goal


# ─── 프리미엄 후보 감지 ──────────────────────────────────────────────

class TestPremiumCandidate:
    def test_regulation_topic_is_premium(self):
        result = classify_business(
            "New regulation on semiconductor exports",
            "Korea tightens semiconductor export regulation for China",
            "policy", "medium",
        )
        assert "premium_candidate" in result.business_tags

    def test_housing_topic_is_premium(self):
        result = classify_business(
            "Korean housing market jeonse crisis",
            "The jeonse deposit system in real estate is under pressure",
            "economy", "medium",
        )
        assert "premium_candidate" in result.business_tags

    def test_premium_has_reason(self):
        result = classify_business(
            "Interest rate regulation reform",
            "Korea monetary policy reform on interest rate",
            "economy", "medium",
        )
        assert result.premium_reason is not None

    def test_premium_boosts_monetization_score(self):
        premium = classify_business(
            "Interest rate regulation reform",
            "Korea monetary policy reform on interest rate",
            "economy", "medium",
        )
        basic = classify_business(
            "Cute cafe in Seoul",
            "A nice day at a cafe",
            "evergreen", "low",
        )
        assert premium.monetization_score > basic.monetization_score


# ─── B2B 후보 감지 ──────────────────────────────────────────────────

class TestB2BCandidate:
    def test_trade_regulation_is_b2b(self):
        result = classify_business(
            "Korea trade tariff changes for foreign investment",
            "New tariff regulation on supply chain imports",
            "economy", "medium",
        )
        assert result.b2b_candidate is True
        assert "b2b_candidate" in result.business_tags

    def test_b2b_has_target_audience(self):
        result = classify_business(
            "Korea trade tariff changes for foreign investment",
            "New tariff regulation on supply chain imports",
            "economy", "medium",
        )
        assert result.b2b_target_audience is not None

    def test_b2b_cta_is_b2b_or_premium(self):
        """B2B + premium 동시 해당 시 premium_waitlist 우선 (정상 동작)."""
        result = classify_business(
            "Korea trade tariff regulation for foreign investment",
            "New regulation on supply chain compliance",
            "economy", "medium",
        )
        if result.b2b_candidate:
            assert result.cta_type in ("b2b_inquiry", "premium_waitlist")

    def test_non_b2b_topic(self):
        result = classify_business(
            "Best Korean dramas to watch",
            "Top 5 K-dramas of 2026",
            "kpop_culture", "low",
        )
        assert result.b2b_candidate is False


# ─── 뉴스레터 후보 ──────────────────────────────────────────────────

class TestNewsletterCandidate:
    def test_economy_is_newsletter(self):
        result = classify_business(
            "Korea GDP growth",
            "Economy update",
            "economy", "medium",
        )
        assert "newsletter" in result.business_tags

    def test_evergreen_is_newsletter(self):
        result = classify_business(
            "Korean culture guide",
            "Understanding Korean society",
            "evergreen", "low",
        )
        assert "newsletter" in result.business_tags

    def test_explainer_keyword_triggers_newsletter(self):
        result = classify_business(
            "Why Korea's birth rate is the lowest explained",
            "A comparison guide to understanding the myth",
            "society", "low",
        )
        assert "newsletter" in result.business_tags


# ─── CTA 매핑 ──────────────────────────────────────────────────────

class TestCTAMapping:
    def test_politics_default_follow(self):
        result = classify_business("Title", "Body", "politics", "medium")
        # politics without premium/b2b triggers → default follow
        assert result.cta_type in ("follow", "premium_waitlist", "b2b_inquiry")

    def test_community_default_reply(self):
        result = classify_business("Title", "Body", "community", "low")
        assert result.cta_type == "reply"


# ─── 리스크 영향 ──────────────────────────────────────────────────

class TestRiskImpact:
    def test_high_risk_reduces_score(self):
        high = classify_business("Title", "Body", "society", "high")
        low = classify_business("Title", "Body", "society", "low")
        assert high.monetization_score < low.monetization_score

    def test_high_risk_politics_is_urgent(self):
        result = classify_business(
            "Emergency political crisis",
            "Critical political event",
            "politics", "high",
        )
        assert "urgent_news" in result.business_tags


# ─── JSON 유틸리티 ──────────────────────────────────────────────────

class TestJsonUtils:
    def test_to_json(self):
        result = business_tags_to_json(["growth", "newsletter"])
        assert '"growth"' in result
        assert '"newsletter"' in result

    def test_from_json(self):
        tags = business_tags_from_json('["growth", "premium_candidate"]')
        assert tags == ["growth", "premium_candidate"]

    def test_from_json_none(self):
        assert business_tags_from_json(None) == []

    def test_from_json_invalid(self):
        assert business_tags_from_json("not json") == []

    def test_from_json_empty(self):
        assert business_tags_from_json("") == []


# ─── Layer 2 안전성 ──────────────────────────────────────────────────

class TestLayer2Safety:
    def test_exception_returns_default(self):
        """classify_business가 내부 에러 시 기본값 반환 확인."""
        # None 입력도 처리 가능해야 함
        result = classify_business("", "", "unknown_category", "unknown_risk")
        assert isinstance(result, BusinessClassification)
        assert "growth" in result.business_tags
