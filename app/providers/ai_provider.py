"""
AI 프로바이더 매니저
====================
5개 역할에 맞는 프로바이더를 자동으로 선택하고 조립합니다.

역할 선택 규칙:
  - draft_writer: ACTIVE_DRAFT_PROVIDER 설정값 → 해당 키 확인 → fallback to mock
  - reviewer: ANTHROPIC_API_KEY 있으면 Claude, 없으면 mock
  - researcher: ACTIVE_RESEARCH_PROVIDER 설정값 → gemini/perplexity → fallback to mock
  - trend_hunter: ACTIVE_TREND_PROVIDER 설정값 → grok → fallback to mock
  - fact_checker: ACTIVE_FACTCHECK_PROVIDER 설정값 → perplexity → fallback to mock
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
    researcher:    리서치 (Gemini / Perplexity / mock)
    trend_hunter:  트렌드 탐지 (Grok / mock)
    fact_checker:  팩트체크 (Perplexity / mock)
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

    # --- 3. Researcher ---
    eff_research = settings.get_effective_research_provider()
    if eff_research == "gemini":
        from app.providers.gemini_provider import GeminiResearcher
        researcher = GeminiResearcher()
        logger.info("✓ Researcher: Google Gemini")
    elif eff_research == "perplexity":
        from app.providers.perplexity_provider import PerplexityFactChecker
        # Perplexity can also do research — wrap as researcher
        researcher = MockResearcher()
        logger.info("○ Researcher: Mock 모드 (Perplexity는 FactChecker로 사용)")
    else:
        researcher = MockResearcher()
        logger.info("○ Researcher: Mock 모드")

    # --- 4. Trend Hunter ---
    eff_trend = settings.get_effective_trend_provider()
    if eff_trend == "grok":
        from app.providers.grok_provider import GrokTrendHunter
        trend_hunter = GrokTrendHunter()
        logger.info("✓ TrendHunter: xAI Grok")
    else:
        trend_hunter = MockTrendHunter()
        logger.info("○ TrendHunter: Mock 모드")

    # --- 5. Fact Checker ---
    eff_fact = settings.get_effective_factcheck_provider()
    if eff_fact == "perplexity":
        from app.providers.perplexity_provider import PerplexityFactChecker
        fact_checker = PerplexityFactChecker()
        logger.info("✓ FactChecker: Perplexity")
    else:
        fact_checker = MockFactChecker()
        logger.info("○ FactChecker: Mock 모드")

    return AITeam(
        draft_writer=draft_writer,
        reviewer=reviewer,
        researcher=researcher,
        trend_hunter=trend_hunter,
        fact_checker=fact_checker,
    )
