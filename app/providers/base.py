"""
AI 프로바이더 추상 인터페이스
==============================
5개 역할(Role)에 대한 공통 데이터 구조와 추상 클래스를 정의합니다.

역할:
  1. DraftWriter   — 초안 작성 (ChatGPT / Claude / mock)
  2. Reviewer       — 리스크 판단 & 최종 다듬기 (Claude / mock)
  3. Researcher     — 리서치 & 데이터 분석 [미래: Gemini]
  4. TrendHunter    — 실시간 트렌드 탐지 [미래: Grok]
  5. FactChecker    — 팩트체크 & 출처 찾기 [미래: Perplexity]

모든 프로바이더는 반드시 대응하는 Mock 구현체가 있어야 합니다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# =============================================================================
# 데이터 구조 — 각 역할의 입출력
# =============================================================================

@dataclass
class DraftResult:
    """DraftWriter 가 만든 초안"""
    hook: str
    body: str
    thread_continuation: str | None = None
    category_suggestion: str = "evergreen"
    tone_notes: str = ""


@dataclass
class ReviewResult:
    """Reviewer 가 내린 최종 판단"""
    hook: str
    body: str
    thread_continuation: str | None = None
    category: str = "evergreen"
    risk_level: str = "medium"
    risk_reasoning: str = ""
    ai_rationale: str = ""
    recommended_action: str = "review"
    korean_summary: str = ""


@dataclass
class ResearchResult:
    """Researcher 가 찾은 정보"""
    summary: str
    key_facts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_response: str = ""


@dataclass
class TrendResult:
    """TrendHunter 가 발견한 트렌드"""
    trending_topics: list[str] = field(default_factory=list)
    relevance_notes: str = ""
    raw_response: str = ""


@dataclass
class FactCheckResult:
    """FactChecker 가 검증한 결과"""
    verified: bool = False
    confidence: str = "low"
    corrections: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_response: str = ""


# =============================================================================
# 추상 클래스 — 각 역할의 인터페이스
# =============================================================================

class BaseDraftWriter(ABC):
    """역할 1: 초안 작성. ChatGPT 또는 Claude 가 담당."""

    @abstractmethod
    async def generate_draft(
        self, title: str, source_text: str, language: str = "en",
    ) -> DraftResult:
        """소스 텍스트를 기반으로 X 포스트 초안을 생성합니다."""
        ...


class BaseReviewer(ABC):
    """역할 2: 리스크 판단 & 최종 다듬기. Claude 가 담당."""

    @abstractmethod
    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research: ResearchResult | None = None,
        factcheck: FactCheckResult | None = None,
    ) -> ReviewResult:
        """초안을 리뷰하고 리스크 판단 + 최종 다듬기를 합니다."""
        ...


class BaseResearcher(ABC):
    """역할 3: 리서치 & 데이터 분석. [미래: Gemini]"""

    @abstractmethod
    async def research(self, query: str, context: str = "") -> ResearchResult:
        """주제에 대한 리서치를 수행합니다."""
        ...


class BaseTrendHunter(ABC):
    """역할 4: 실시간 트렌드 탐지. [미래: Grok]"""

    @abstractmethod
    async def find_trends(self, topic_area: str = "korea") -> TrendResult:
        """실시간 트렌드를 탐지합니다."""
        ...


class BaseFactChecker(ABC):
    """역할 5: 팩트체크 & 출처 찾기. [미래: Perplexity]"""

    @abstractmethod
    async def check_facts(self, claim: str, context: str = "") -> FactCheckResult:
        """주장의 사실 여부를 검증합니다."""
        ...
