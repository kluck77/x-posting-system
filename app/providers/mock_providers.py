"""
Mock 프로바이더 모음
====================
API 키 없이도 전체 시스템을 테스트할 수 있는 Mock 구현체들.
모든 5개 역할에 대한 Mock이 여기에 있습니다.
"""

import logging
from app.providers.base import (
    BaseDraftWriter, BaseReviewer, BaseResearcher,
    BaseTrendHunter, BaseFactChecker,
    DraftResult, ReviewResult, ResearchResult,
    TrendResult, FactCheckResult,
)

logger = logging.getLogger(__name__)


class MockDraftWriter(BaseDraftWriter):
    """Mock 초안 작성기. API 키 없이 데모용 초안을 생성합니다."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "en",
    ) -> DraftResult:
        logger.info(f"[Mock DraftWriter] 초안 생성: '{title[:50]}'")
        return DraftResult(
            hook=f"🇰🇷 Here's what you need to know: {title[:80]}",
            body=(
                f"South Korea update: {title}\n\n"
                f"Key takeaway — understanding Korean society "
                f"means looking beyond the surface.\n\n"
                f"This is what many overseas observers miss."
            ),
            thread_continuation=(
                f"Context for non-Koreans:\n\n"
                f"Korea's unique position as a rapidly developed democracy "
                f"means these stories carry different weight."
            ),
            category_suggestion="society",
            tone_notes="Mock mode: informative, accessible",
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
