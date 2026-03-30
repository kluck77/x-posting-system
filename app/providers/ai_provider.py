"""
AI 프로바이더 매니저
====================
5개 역할에 맞는 프로바이더를 자동으로 선택하고 조립합니다.

역할 선택 규칙:
  - draft_writer: ACTIVE_DRAFT_PROVIDER 설정값 → 해당 키 확인 → fallback to mock
  - reviewer: ANTHROPIC_API_KEY 있으면 Claude, 없으면 mock
  - researcher: ACTIVE_RESEARCH_PROVIDER 설정값 → v1은 항상 mock
  - trend_hunter: GROK_API_KEY 있으면 [미래], v1은 항상 mock
  - fact_checker: ACTIVE_FACTCHECK_PROVIDER 설정값 → v1은 항상 mock
"""

import logging
from dataclasses import dataclass
from app.config import settings
from app.providers.base import (
    BaseDraftWriter, BaseReviewer, BaseResearcher,
    BaseTrendHunter, BaseFactChecker,
)
from app.providers.mock_providers import (
    MockDraftWriter, MockReviewer, MockResearcher,
    MockTrendHunter, MockFactChecker,
)

logger = logging.getLogger(__name__)


@dataclass
class AITeam:
    """
    5개 역할의 AI 프로바이더를 묶은 팀.

    draft_writer:  초안 작성 (ChatGPT / Claude / mock)
    reviewer:      리스크 판단 & 최종 다듬기 (Claude / mock)
    researcher:    리서치 [미래: Gemini / Perplexity]
    trend_hunter:  트렌드 탐지 [미래: Grok]
    fact_checker:  팩트체크 [미래: Perplexity]
    """
    draft_writer: BaseDraftWriter
    reviewer: BaseReviewer
    researcher: BaseResearcher
    trend_hunter: BaseTrendHunter
    fact_checker: BaseFactChecker


def create_ai_team() -> AITeam:
    """
    현재 .env 설정에 따라 AI 팀을 조립합니다.
    키가 없는 역할은 자동으로 Mock 으로 fallback 됩니다.
    """
    # --- 1. Draft Writer ---
    eff_draft = settings.get_effective_draft_provider()
    if eff_draft == "openai":
        from app.providers.openai_provider import OpenAIDraftWriter
        draft_writer = OpenAIDraftWriter()
        logger.info("✓ DraftWriter: OpenAI (ChatGPT)")
    elif eff_draft == "anthropic":
        from app.providers.anthropic_provider import AnthropicDraftWriter
        draft_writer = AnthropicDraftWriter()
        logger.info("✓ DraftWriter: Anthropic (Claude)")
    else:
        draft_writer = MockDraftWriter()
        logger.info("○ DraftWriter: Mock 모드")

    # --- 2. Reviewer ---
    if settings.has_anthropic:
        from app.providers.anthropic_provider import AnthropicReviewer
        reviewer = AnthropicReviewer()
        logger.info("✓ Reviewer: Anthropic (Claude)")
    else:
        reviewer = MockReviewer()
        logger.info("○ Reviewer: Mock 모드")

    # --- 3. Researcher [v1: mock 전용] ---
    researcher = MockResearcher()
    eff_research = settings.get_effective_research_provider()
    if eff_research != "mock":
        logger.info(f"  Researcher: {eff_research} 요청되었으나 v1은 mock만 지원")
    logger.info("○ Researcher: Mock 모드 (v1 기본)")

    # --- 4. Trend Hunter [v1: mock 전용] ---
    trend_hunter = MockTrendHunter()
    logger.info("○ TrendHunter: Mock 모드 (v1 기본)")

    # --- 5. Fact Checker [v1: mock 전용] ---
    fact_checker = MockFactChecker()
    eff_fact = settings.get_effective_factcheck_provider()
    if eff_fact != "mock":
        logger.info(f"  FactChecker: {eff_fact} 요청되었으나 v1은 mock만 지원")
    logger.info("○ FactChecker: Mock 모드 (v1 기본)")

    return AITeam(
        draft_writer=draft_writer,
        reviewer=reviewer,
        researcher=researcher,
        trend_hunter=trend_hunter,
        fact_checker=fact_checker,
    )
