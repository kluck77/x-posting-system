"""
AI 프로바이더 테스트
====================
Mock 프로바이더 5종이 올바르게 동작하는지 테스트합니다.
"""

import pytest
from app.providers.mock_providers import (
    MockDraftWriter, MockReviewer, MockResearcher,
    MockTrendHunter, MockFactChecker,
)
from app.providers.base import DraftResult, ResearchResult


class TestMockDraftWriter:
    @pytest.mark.asyncio
    async def test_generates_draft(self):
        writer = MockDraftWriter()
        result = await writer.generate_draft("한국 경제 성장", "경제 기사 내용")
        assert result.hook
        assert result.body
        assert result.category_suggestion

    @pytest.mark.asyncio
    async def test_accepts_phase8_kwargs(self):
        """[Phase 8-γ] Mock 가 OpenAI/Anthropic 의 dormant kwargs 를 수용해야 한다."""
        writer = MockDraftWriter()
        result = await writer.generate_draft(
            "t", "s", language="en",
            source_type="rss", criteria_context="ctx",
        )
        assert result.body


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

    @pytest.mark.asyncio
    async def test_accepts_phase8_kwargs(self):
        """[Phase 8-γ] MockReviewer 가 Anthropic 의 dormant criteria_context 를 수용해야 한다."""
        reviewer = MockReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="society")
        result = await reviewer.review_and_refine(
            title="t", source_text="s", draft=draft, criteria_context="ctx",
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
