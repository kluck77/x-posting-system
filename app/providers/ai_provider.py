"""
AI 프로바이더 매니저
====================
5개 프로바이더를 5개 역할에 자동으로 배분합니다.
API 키가 있는 프로바이더는 자동 활성화됩니다.

역할 선택 우선순위:
  DraftWriter:  ACTIVE_DRAFT_PROVIDER 설정값 → 키 보유 순(openai→anthropic) → mock
  Reviewer:     anthropic → mock
  Researcher:   gemini → perplexity → mock
  TrendHunter:  grok → mock
  FactChecker:  perplexity → mock

월 $30 예산 배분 (30 posts/day 기준):
  OpenAI GPT-4o-mini   DraftWriter   ~$2/월
  Claude Haiku         Reviewer      ~$3/월
  Google Gemini Flash  Researcher     무료
  xAI Grok             TrendHunter   ~$1/월
  Perplexity Sonar     FactChecker   ~$2/월
  ─────────────────────────────────────
  합계                               ~$8/월 (여유 $22)
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

    draft_writer:   초안 작성
    reviewer:       리스크 판단 & 최종 다듬기
    researcher:     리서치 & 분석
    trend_hunter:   트렌드 탐지
    fact_checker:   팩트체크
    """
    draft_writer:  BaseDraftWriter
    reviewer:      BaseReviewer
    researcher:    BaseResearcher
    trend_hunter:  BaseTrendHunter
    fact_checker:  BaseFactChecker


def create_ai_team() -> AITeam:
    """
    .env 설정 기반으로 AI 팀을 조립합니다.
    키가 없는 역할은 자동으로 Mock으로 fallback됩니다.
    """

    # ── 1. Draft Writer ───────────────────────────────────────────────────────
    eff = settings.get_effective_draft_provider()
    if eff == "openai":
        from app.providers.openai_provider import OpenAIDraftWriter
        draft_writer: BaseDraftWriter = OpenAIDraftWriter()
        logger.info("✓ DraftWriter: OpenAI GPT-4o-mini")
    elif eff == "anthropic":
        from app.providers.anthropic_provider import AnthropicDraftWriter
        draft_writer = AnthropicDraftWriter()
        logger.info("✓ DraftWriter: Anthropic Claude")
    else:
        draft_writer = MockDraftWriter()
        logger.info("○ DraftWriter: Mock 모드")

    # ── 2. Reviewer ───────────────────────────────────────────────────────────
    eff_rev = settings.get_effective_review_provider()
    if eff_rev == "anthropic":
        from app.providers.anthropic_provider import AnthropicReviewer
        reviewer: BaseReviewer = AnthropicReviewer()
        logger.info("✓ Reviewer: Anthropic Claude")
    else:
        reviewer = MockReviewer()
        logger.info("○ Reviewer: Mock 모드")

    # ── 3. Researcher ─────────────────────────────────────────────────────────
    eff_res = settings.get_effective_research_provider()
    if eff_res == "gemini":
        from app.providers.gemini_provider import GeminiResearcher
        researcher: BaseResearcher = GeminiResearcher()
        logger.info("✓ Researcher: Google Gemini Flash (무료)")
    elif eff_res == "perplexity":
        from app.providers.perplexity_provider import PerplexityResearcher
        researcher = PerplexityResearcher()
        logger.info("✓ Researcher: Perplexity Sonar")
    else:
        researcher = MockResearcher()
        logger.info("○ Researcher: Mock 모드")

    # ── 4. Trend Hunter ───────────────────────────────────────────────────────
    if settings.has_grok:
        from app.providers.grok_provider import GrokTrendHunter
        trend_hunter: BaseTrendHunter = GrokTrendHunter()
        logger.info("✓ TrendHunter: xAI Grok")
    else:
        trend_hunter = MockTrendHunter()
        logger.info("○ TrendHunter: Mock 모드")

    # ── 5. Fact Checker ───────────────────────────────────────────────────────
    if settings.has_perplexity:
        from app.providers.perplexity_provider import PerplexityFactChecker
        fact_checker: BaseFactChecker = PerplexityFactChecker()
        logger.info("✓ FactChecker: Perplexity Sonar")
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
