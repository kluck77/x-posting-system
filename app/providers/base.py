"""
AI 프로바이더 추상 인터페이스
==============================
6개 역할(Role)에 대한 공통 데이터 구조와 추상 클래스를 정의합니다.

역할:
  1. DraftWriter   — 초안 작성 (OpenAI / Claude / DeepSeek / Groq / Together)
  2. Reviewer       — 리스크 판단 & 최종 다듬기 (Claude / Mistral)
  3. Researcher     — 리서치 & 데이터 분석 (Gemini / Perplexity)
  4. TrendHunter    — 실시간 트렌드 탐지 (Grok)
  5. FactChecker    — 팩트체크 & 출처 찾기 (Perplexity)
  6. WebSearcher    — 실시간 웹 검색 & 컨텍스트 보강 (Tavily)  ← NEW

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


@dataclass
class WebSearchResult:
    """WebSearcher 가 수집한 실시간 웹 검색 결과."""
    query: str
    results: list[dict] = field(default_factory=list)  # [{title, url, content, score}]
    summary: str = ""

    def as_context(self, max_chars: int = 1500) -> str:
        """프롬프트 주입용 컨텍스트 문자열로 변환합니다."""
        if not self.results:
            return ""
        lines = [f"[Web Search: {self.query}]"]
        total = 0
        for r in self.results:
            snippet = f"• {r.get('title','')} — {r.get('content','')[:300]}"
            total += len(snippet)
            if total > max_chars:
                break
            lines.append(snippet)
        return "\n".join(lines)


# =============================================================================
# 추상 클래스 — 각 역할의 인터페이스
# =============================================================================

class BaseDraftWriter(ABC):
    """역할 1: 초안 작성."""

    @abstractmethod
    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        ...


class BaseReviewer(ABC):
    """역할 2: 리스크 판단 & 최종 다듬기."""

    @abstractmethod
    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research: ResearchResult | None = None,
        factcheck: FactCheckResult | None = None,
    ) -> ReviewResult:
        ...


class BaseResearcher(ABC):
    """역할 3: 리서치 & 데이터 분석."""

    @abstractmethod
    async def research(self, query: str, context: str = "") -> ResearchResult:
        ...


class BaseTrendHunter(ABC):
    """역할 4: 실시간 트렌드 탐지."""

    @abstractmethod
    async def find_trends(self, topic_area: str = "korea") -> TrendResult:
        ...


class BaseFactChecker(ABC):
    """역할 5: 팩트체크 & 출처 찾기."""

    @abstractmethod
    async def check_facts(self, claim: str, context: str = "") -> FactCheckResult:
        ...


class BaseWebSearcher(ABC):
    """역할 6: 실시간 웹 검색 & 컨텍스트 보강 (Tavily)."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> WebSearchResult:
        """실시간 웹 검색을 수행하고 결과를 반환합니다."""
        ...
