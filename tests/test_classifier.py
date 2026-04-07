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


class TestClassifyCommunityRisk:
    """커뮤니티 입력 리스크 재평가 테스트"""

    def test_minimum_medium_from_low(self):
        from app.services.classifier import classify_community_risk
        risk, _ = classify_community_risk(
            "비트코인 반감기 반응", "다들 지금 매수 타이밍이라고 함",
            ContentCategory.ECONOMY, RiskLevel.LOW, ""
        )
        assert risk == RiskLevel.MEDIUM

    def test_politics_always_high(self):
        from app.services.classifier import classify_community_risk
        risk, reasoning = classify_community_risk(
            "대선 여론", "커뮤에서 야당 지지율 올랐다고 함",
            ContentCategory.POLITICS, RiskLevel.MEDIUM, ""
        )
        assert risk == RiskLevel.HIGH
        assert "HIGH" in reasoning or "정치" in reasoning or "politics" in reasoning

    def test_policy_always_high(self):
        from app.services.classifier import classify_community_risk
        risk, _ = classify_community_risk(
            "규제 관련 커뮤 반응", "새 정책 반응",
            ContentCategory.POLICY, RiskLevel.LOW, ""
        )
        assert risk == RiskLevel.HIGH

    def test_fraud_keyword_triggers_high(self):
        from app.services.classifier import classify_community_risk
        risk, reasoning = classify_community_risk(
            "코인 사기 의혹", "이 프로젝트 먹튀라는 썰이 돔",
            ContentCategory.ECONOMY, RiskLevel.MEDIUM, ""
        )
        assert risk == RiskLevel.HIGH
        assert "먹튀" in reasoning or "커뮤니티" in reasoning

    def test_pump_dump_keywords_trigger_high(self):
        from app.services.classifier import classify_community_risk
        risk, _ = classify_community_risk(
            "코인 작전", "지금 세력 펌핑 중이라는 글이 올라옴",
            ContentCategory.ECONOMY, RiskLevel.LOW, ""
        )
        assert risk == RiskLevel.HIGH

    def test_rumor_keyword_triggers_high(self):
        from app.services.classifier import classify_community_risk
        risk, _ = classify_community_risk(
            "찌라시 유통", "미확인 루머 돌고 있음",
            ContentCategory.SOCIETY, RiskLevel.LOW, ""
        )
        assert risk == RiskLevel.HIGH

    def test_existing_high_preserved(self):
        from app.services.classifier import classify_community_risk
        risk, _ = classify_community_risk(
            "일반 경제 글", "그냥 경제 얘기",
            ContentCategory.ECONOMY, RiskLevel.HIGH, "이미 high"
        )
        assert risk == RiskLevel.HIGH

    def test_reasoning_contains_community_note(self):
        from app.services.classifier import classify_community_risk
        _, reasoning = classify_community_risk(
            "테스트", "내용",
            ContentCategory.EVERGREEN, RiskLevel.LOW, "기존 근거"
        )
        assert "커뮤니티" in reasoning


class TestBuildCommunityWarning:
    """커뮤니티 경고 문구 생성 테스트"""

    def test_returns_string(self):
        from app.services.classifier import build_community_warning
        result = build_community_warning("제목", "내용", ContentCategory.ECONOMY, RiskLevel.MEDIUM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_source_note(self):
        from app.services.classifier import build_community_warning
        result = build_community_warning("제목", "내용", ContentCategory.ECONOMY, RiskLevel.MEDIUM)
        assert "커뮤니티" in result

    def test_coin_manipulation_warning(self):
        from app.services.classifier import build_community_warning
        result = build_community_warning("코인 작전", "펌핑 세력 글", ContentCategory.ECONOMY, RiskLevel.HIGH)
        assert "조작" in result or "검증" in result

    def test_fraud_warning(self):
        from app.services.classifier import build_community_warning
        result = build_community_warning("고소장 공개", "사기 고발글", ContentCategory.SOCIETY, RiskLevel.HIGH)
        assert "법적" in result or "사실 확인" in result

    def test_high_risk_badge(self):
        from app.services.classifier import build_community_warning
        result = build_community_warning("제목", "내용", ContentCategory.POLITICS, RiskLevel.HIGH)
        assert "HIGH" in result or "🔴" in result
