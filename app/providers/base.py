"""
AI 프로바이더 추상 인터페이스
==============================
5개 역할(Role)에 대한 공통 데이터 구조와 추상 클래스를 정의합니다.

역할:
  1. DraftWriter   — 초안 작성 (OpenAI / Claude)
  2. Reviewer       — 리스크 판단 & 최종 다듬기 (Claude)
  3. Researcher     — 리서치 & 데이터 분석 (Gemini / Perplexity)
  4. TrendHunter    — 실시간 트렌드 탐지 (Grok)
  5. FactChecker    — 팩트체크 & 출처 찾기 (Perplexity)

모든 프로바이더는 반드시 대응하는 Mock 구현체가 있어야 합니다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# =============================================================================
# 공유 계약 — 5-Criteria 신호
# =============================================================================

@dataclass
class CriteriaSignals:
    """
    5-Criteria 품질 신호 — 에이전트별 담당 영역만 채움.

    각 필드: {"score": float|None, "note": str}
      score — 정량 점수 (없으면 None)
      note  — 판단 근거 한 줄

    역할별 책임:
      Grok       → marketability, follower_quality (per-topic 점수 집계)
      Perplexity → interpretation, marketability (signal 수준)
      Gemini     → expertise, context_gap
      Reviewer   → criteria_scores (ReviewResult 별도 필드)로 최종 판단
    """
    marketability:    dict = field(default_factory=dict)
    follower_quality: dict = field(default_factory=dict)
    interpretation:   dict = field(default_factory=dict)
    expertise:        dict = field(default_factory=dict)
    context_gap:      dict = field(default_factory=dict)

    def any_populated(self) -> bool:
        return any(bool(v) for v in vars(self).values())

    def to_log_str(self) -> str:
        parts = []
        for name, val in [
            ("mkt", self.marketability), ("fol", self.follower_quality),
            ("interp", self.interpretation), ("exp", self.expertise),
            ("gap", self.context_gap),
        ]:
            if val:
                score = val.get("score")
                note = (val.get("note") or "")[:40]
                s = f"{'%.1f' % score if score is not None else '?'}"
                parts.append(f"{name}={s} ({note})")
        return " | ".join(parts) if parts else "—"


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
    # 재생성 가이드 — Reviewer가 "regenerate" 권고 시 DraftWriter에 전달할 구체적 힌트
    regeneration_hint: str = ""


@dataclass
class ResearchResult:
    """Researcher 가 찾은 정보"""
    summary: str
    key_facts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_response: str = ""
    # 5-criteria 지원 필드 (Gemini가 채움 — 기존 호환 유지)
    interpretation_gaps: list[str] = field(default_factory=list)
    # {"fact text": "confirms_common_narrative|challenges_assumption|missing_context"}
    fact_labels: dict[str, str] = field(default_factory=dict)
    # 구조화된 criteria_signals (위 두 필드를 매핑)
    criteria_signals: CriteriaSignals = field(default_factory=CriteriaSignals)


@dataclass
class TrendResult:
    """TrendHunter 가 발견한 트렌드"""
    trending_topics: list[str] = field(default_factory=list)
    relevance_notes: str = ""
    raw_response: str = ""
    # Grok이 채우는 5-criteria 신호 (marketability + follower_quality)
    criteria_signals: CriteriaSignals = field(default_factory=CriteriaSignals)


@dataclass
class FactCheckResult:
    """FactChecker 가 검증한 결과"""
    verified: bool = False
    confidence: str = "low"
    corrections: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_response: str = ""
    # 5-criteria 지원 필드 (Perplexity가 채움 — 기존 호환 유지)
    interpretation_opportunity: str = ""   # high|medium|low — reason
    marketability_signal: str = ""         # global|regional|local
    # 구조화된 criteria_signals (위 두 필드를 매핑)
    criteria_signals: CriteriaSignals = field(default_factory=CriteriaSignals)


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
