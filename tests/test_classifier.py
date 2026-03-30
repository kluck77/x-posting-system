"""
분류 서비스 테스트
==================
카테고리 분류, 위험도 분류, 승인 필요 여부를 테스트합니다.
"""

import pytest
from app.services.classifier import (
    classify_category, classify_risk, requires_approval,
)
from app.models.content import ContentCategory, RiskLevel


class TestClassifyCategory:
    """카테고리 분류 테스트"""

    def test_politics_category(self):
        cat = classify_category("대통령 선거 결과", "대통령 선거에서 여당 후보가 당선되었다")
        assert cat == ContentCategory.POLITICS

    def test_economy_category(self):
        cat = classify_category("Korea GDP growth", "The Korean economy grew by 2% with strong exports")
        assert cat == ContentCategory.ECONOMY

    def test_kpop_category(self):
        cat = classify_category("BTS new album", "K-pop group BTS released a new album to worldwide acclaim")
        assert cat == ContentCategory.KPOP_CULTURE

    def test_society_category(self):
        cat = classify_category("저출산 문제", "한국의 출산율이 세계 최저를 기록")
        assert cat == ContentCategory.SOCIETY

    def test_policy_category(self):
        cat = classify_category("새 규제 법안", "정부가 새로운 규제 법안을 발표")
        assert cat == ContentCategory.POLICY

    def test_unknown_defaults_to_evergreen(self):
        cat = classify_category("random text", "nothing matching any keyword here at all")
        assert cat == ContentCategory.EVERGREEN


class TestClassifyRisk:
    """위험도 분류 테스트"""

    def test_politics_at_least_medium(self):
        risk, _ = classify_risk("election news", "president election", ContentCategory.POLITICS)
        assert risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_high_risk_keywords(self):
        risk, reasoning = classify_risk(
            "Political scandal", "corruption arrest protest crisis",
            ContentCategory.POLITICS,
        )
        assert risk == RiskLevel.HIGH
        assert "고위험" in reasoning or "corruption" in reasoning.lower()

    def test_evergreen_low_risk(self):
        risk, _ = classify_risk(
            "Korean food guide", "How to make kimchi at home",
            ContentCategory.EVERGREEN,
        )
        assert risk == RiskLevel.LOW

    def test_kpop_controversy_medium(self):
        risk, _ = classify_risk(
            "Idol scandal", "K-pop star dating controversy",
            ContentCategory.KPOP_CULTURE,
        )
        assert risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)


class TestRequiresApproval:
    """승인 필요 여부 테스트"""

    def test_politics_always_requires_approval(self):
        assert requires_approval(RiskLevel.LOW, ContentCategory.POLITICS, auto_post_enabled=True) is True

    def test_policy_always_requires_approval(self):
        assert requires_approval(RiskLevel.LOW, ContentCategory.POLICY, auto_post_enabled=True) is True

    def test_economy_always_requires_approval(self):
        assert requires_approval(RiskLevel.LOW, ContentCategory.ECONOMY, auto_post_enabled=True) is True

    def test_society_always_requires_approval(self):
        assert requires_approval(RiskLevel.LOW, ContentCategory.SOCIETY, auto_post_enabled=True) is True

    def test_high_risk_always_requires(self):
        assert requires_approval(RiskLevel.HIGH, ContentCategory.EVERGREEN, auto_post_enabled=True) is True

    def test_medium_risk_always_requires(self):
        assert requires_approval(RiskLevel.MEDIUM, ContentCategory.EVERGREEN, auto_post_enabled=True) is True

    def test_low_evergreen_auto_off_requires(self):
        """자동 게시 꺼져있으면 low+evergreen도 승인 필요"""
        assert requires_approval(RiskLevel.LOW, ContentCategory.EVERGREEN, auto_post_enabled=False) is True

    def test_low_evergreen_auto_on_no_approval(self):
        """자동 게시 켜져있고 low+evergreen이면 승인 불필요"""
        assert requires_approval(RiskLevel.LOW, ContentCategory.EVERGREEN, auto_post_enabled=True) is False

    def test_default_auto_off(self):
        """기본값은 자동 게시 OFF → 모든 것이 승인 필요"""
        assert requires_approval(RiskLevel.LOW, ContentCategory.EVERGREEN) is True
