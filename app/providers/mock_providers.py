"""
Mock 프로바이더 모음
====================
API 키 없이도 전체 시스템을 테스트할 수 있는 Mock 구현체들.
모든 6개 역할에 대한 Mock이 여기에 있습니다.
"""

import logging
from app.providers.base import (
    BaseDraftWriter, BaseReviewer, BaseResearcher,
    BaseTrendHunter, BaseFactChecker, BaseWebSearcher,
    DraftResult, ReviewResult, ResearchResult,
    TrendResult, FactCheckResult, WebSearchResult,
)

logger = logging.getLogger(__name__)


class MockDraftWriter(BaseDraftWriter):
    """Mock 초안 작성기. API 키 없이 데모용 초안을 생성합니다."""

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[Mock DraftWriter] 초안 생성: '{title[:50]}'")

        if source_type == "community_input":
            return DraftResult(
                hook=f"Korean online communities are reacting strongly to this: {title[:60]}",
                body=(
                    f"A recurring theme in Korean online discussion right now is concern about {title[:80]}. "
                    f"The sentiment is notably [pessimistic/skeptical] — though none of these claims are verified. "
                    f"Follow to track how this develops."
                ),
                thread_continuation=(
                    f"For non-Korean readers:\n\n"
                    f"Korean online forums (DCInside, FMKorea) tend to surface sentiment shifts "
                    f"before they show up in mainstream coverage. This is worth watching — but treat it as signal, not fact."
                ),
                category_suggestion="society",
                tone_notes="Mock community_input mode: sentiment signal, unverified claims flagged",
            )

        return DraftResult(
            hook=f"The numbers don't add up — and that's exactly the point. {title[:60]}",
            body=(
                f"Here's what's actually happening: {title[:100]}\n\n"
                f"Most coverage misses the context non-Koreans need to understand why this matters. "
                f"Follow to get Korea's economy in plain English — before it hits global headlines."
            ),
            thread_continuation=(
                f"Context for non-Koreans:\n\n"
                f"Korea's export-driven economy means moves like this ripple outward fast. "
                f"What looks local rarely stays local."
            ),
            category_suggestion="economy",
            tone_notes="Mock mode: number shock hook, 5-block structure",
        )


class MockReviewer(BaseReviewer):
    """Mock 리뷰어. 리스크 판단을 시뮬레이션합니다."""

    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research: ResearchResult | None = None,
        factcheck: FactCheckResult | None = None,
    ) -> ReviewResult:
        logger.info(f"[Mock Reviewer] 리뷰: '{title[:50]}'")
        return ReviewResult(
            hook=draft.hook,
            body=draft.body,
            thread_continuation=draft.thread_continuation,
            category=draft.category_suggestion or "society",
            risk_level="medium",
            risk_reasoning="Mock mode: default medium risk for safety.",
            ai_rationale="Mock review — draft explains Korean topic for international audience.",
            recommended_action="review",
        )


class MockResearcher(BaseResearcher):
    """Mock 리서처. 리서치 결과를 시뮬레이션합니다."""

    async def research(self, query: str, context: str = "") -> ResearchResult:
        logger.info(f"[Mock Researcher] 리서치: '{query[:60]}'")
        return ResearchResult(
            summary=(
                f"Research on: {query[:100]}\n\n"
                f"South Korea has seen significant developments in this area. "
                f"Key stakeholders include government, industry, and civil society."
            ),
            key_facts=[
                "South Korea is the 13th largest economy globally",
                "The topic has been covered by major Korean media",
                "International interest is growing",
            ],
            sources=["https://example.com/mock-source-1"],
        )


class MockTrendHunter(BaseTrendHunter):
    """Mock 트렌드 헌터. 트렌드 결과를 시뮬레이션합니다."""

    async def find_trends(self, topic_area: str = "korea") -> TrendResult:
        logger.info(f"[Mock TrendHunter] 트렌드 탐색: '{topic_area}'")
        return TrendResult(
            trending_topics=[
                "Korean semiconductor exports",
                "K-pop global influence",
                "South Korea birth rate",
            ],
            relevance_notes="Mock trends for demonstration",
        )


class MockFactChecker(BaseFactChecker):
    """Mock 팩트체커. 팩트체크 결과를 시뮬레이션합니다."""

    async def check_facts(self, claim: str, context: str = "") -> FactCheckResult:
        logger.info(f"[Mock FactChecker] 검증: '{claim[:60]}'")
        return FactCheckResult(
            verified=True,
            confidence="low",
            corrections=[],
            sources=["https://example.com/mock-verification"],
            raw_response="Mock fact-check: no real verification performed",
        )


class MockWebSearcher(BaseWebSearcher):
    """Mock 웹 검색기. API 키 없이 테스트용."""

    async def search(self, query: str, max_results: int = 5) -> WebSearchResult:
        logger.info(f"[Mock WebSearcher] 검색: '{query[:60]}'")
        return WebSearchResult(
            query=query,
            results=[
                {
                    "title":   f"Mock Result for: {query[:40]}",
                    "url":     "https://example.com/mock-search",
                    "content": "Mock web search result — no real search performed.",
                    "score":   0.5,
                }
            ],
            summary="Mock search summary — configure TAVILY_API_KEY for real results.",
        )
