"""
AI 프로바이더 테스트
====================
Mock 프로바이더 5종 + 실제 프로바이더 클래스 검증을 테스트합니다.
"""

import pytest
from app.providers.mock_providers import (
    MockDraftWriter, MockReviewer, MockResearcher,
    MockTrendHunter, MockFactChecker,
)
from app.providers.base import (
    DraftResult, ResearchResult,
    BaseResearcher, BaseTrendHunter, BaseFactChecker,
)


class TestMockDraftWriter:
    @pytest.mark.asyncio
    async def test_generates_draft(self):
        writer = MockDraftWriter()
        result = await writer.generate_draft("한국 경제 성장", "경제 기사 내용")
        assert result.hook
        assert result.body
        assert result.category_suggestion


class TestMockReviewer:
    @pytest.mark.asyncio
    async def test_reviews_draft(self):
        reviewer = MockReviewer()
        draft = DraftResult(
            hook="test hook", body="test body",
            category_suggestion="economy",
        )
        result = await reviewer.review_and_refine(
            title="테스트", source_text="테스트 텍스트",
            draft=draft,
        )
        assert result.hook
        assert result.body
        assert result.risk_level in ("low", "medium", "high")
        assert result.category

    @pytest.mark.asyncio
    async def test_reviews_with_research(self):
        reviewer = MockReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="society")
        research = ResearchResult(summary="Some research", key_facts=["fact1"])
        result = await reviewer.review_and_refine(
            title="t", source_text="s", draft=draft, research=research,
        )
        assert result.risk_level


class TestMockResearcher:
    @pytest.mark.asyncio
    async def test_researches(self):
        researcher = MockResearcher()
        result = await researcher.research("한국 출산율")
        assert result.summary
        assert isinstance(result.key_facts, list)
        assert isinstance(result.sources, list)


class TestMockTrendHunter:
    @pytest.mark.asyncio
    async def test_finds_trends(self):
        hunter = MockTrendHunter()
        result = await hunter.find_trends("korea")
        assert isinstance(result.trending_topics, list)
        assert len(result.trending_topics) > 0


class TestMockFactChecker:
    @pytest.mark.asyncio
    async def test_checks_facts(self):
        checker = MockFactChecker()
        result = await checker.check_facts("Korea GDP grew 2%")
        assert isinstance(result.verified, bool)
        assert result.confidence in ("low", "medium", "high")
        assert isinstance(result.sources, list)


class TestProviderFallback:
    """프로바이더 fallback 동작 테스트"""

    @pytest.mark.asyncio
    async def test_all_mocks_work_together(self):
        """5개 Mock이 모두 함께 동작하는지 테스트"""
        writer = MockDraftWriter()
        reviewer = MockReviewer()
        researcher = MockResearcher()
        hunter = MockTrendHunter()
        checker = MockFactChecker()

        # 1. 리서치
        research = await researcher.research("test topic")
        # 2. 초안 생성
        draft = await writer.generate_draft("test", "test text")
        # 3. 팩트체크
        facts = await checker.check_facts(draft.body)
        # 4. 리뷰
        review = await reviewer.review_and_refine(
            "test", "test text", draft, research, facts,
        )
        # 5. 트렌드 (독립)
        trends = await hunter.find_trends()

        assert review.hook
        assert review.risk_level
        assert trends.trending_topics


class TestNewProviderImports:
    """새 프로바이더 클래스가 올바르게 import 되고 인터페이스를 구현하는지 테스트"""

    def test_gemini_researcher_is_base_researcher(self):
        from app.providers.gemini_provider import GeminiResearcher
        assert issubclass(GeminiResearcher, BaseResearcher)

    def test_grok_trend_hunter_is_base_trend_hunter(self):
        from app.providers.grok_provider import GrokTrendHunter
        assert issubclass(GrokTrendHunter, BaseTrendHunter)

    def test_perplexity_fact_checker_is_base_fact_checker(self):
        from app.providers.perplexity_provider import PerplexityFactChecker
        assert issubclass(PerplexityFactChecker, BaseFactChecker)

    def test_gemini_researcher_instantiates(self):
        from app.providers.gemini_provider import GeminiResearcher
        r = GeminiResearcher()
        assert r is not None

    def test_grok_trend_hunter_instantiates(self):
        from app.providers.grok_provider import GrokTrendHunter
        t = GrokTrendHunter()
        assert t is not None

    def test_perplexity_fact_checker_instantiates(self):
        from app.providers.perplexity_provider import PerplexityFactChecker
        f = PerplexityFactChecker()
        assert f is not None


class TestReviewResultQualityFlags:
    """ReviewResult.quality_flags 후방 호환 + 기본값 테스트."""

    def test_review_result_quality_flags_defaults_empty(self):
        """quality_flags 미제공 시 빈 dict 기본값."""
        from app.providers.base import ReviewResult
        r = ReviewResult(hook="h", body="b")
        assert r.quality_flags == {}

    def test_review_result_quality_flags_set(self):
        """quality_flags 명시 설정 가능."""
        from app.providers.base import ReviewResult
        flags = {"hook_strong": True, "specific_fact_present": False}
        r = ReviewResult(hook="h", body="b", quality_flags=flags)
        assert r.quality_flags["hook_strong"] is True
        assert r.quality_flags["specific_fact_present"] is False

    @pytest.mark.asyncio
    async def test_mock_reviewer_returns_empty_quality_flags(self):
        """MockReviewer는 quality_flags = {} 반환 (후방 호환)."""
        from app.providers.mock_providers import MockReviewer
        from app.providers.base import DraftResult
        reviewer = MockReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="economy")
        result = await reviewer.review_and_refine(
            title="test", source_text="text", draft=draft
        )
        assert isinstance(result.quality_flags, dict)


class TestAITeamCreation:
    """create_ai_team()이 다양한 설정에서 올바르게 동작하는지 테스트"""

    def test_creates_all_mock_team(self):
        from app.providers.ai_provider import create_ai_team
        team = create_ai_team()
        assert team.draft_writer is not None
        assert team.reviewer is not None
        assert team.researcher is not None
        assert team.trend_hunter is not None
        assert team.fact_checker is not None
