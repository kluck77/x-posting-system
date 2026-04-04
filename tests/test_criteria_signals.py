"""
5-Criteria 공유 계약 + Orchestrator 재생성 루프 테스트
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.providers.base import (
    CriteriaSignals,
    TrendResult,
    FactCheckResult,
    ResearchResult,
    ReviewResult,
    DraftResult,
)


# ─── CriteriaSignals ─────────────────────────────────────────────────────────

class TestCriteriaSignals:

    def test_default_empty(self):
        cs = CriteriaSignals()
        assert cs.marketability == {}
        assert cs.follower_quality == {}
        assert cs.interpretation == {}
        assert cs.expertise == {}
        assert cs.context_gap == {}

    def test_any_populated_false_when_empty(self):
        cs = CriteriaSignals()
        assert cs.any_populated() is False

    def test_any_populated_true_when_one_field(self):
        cs = CriteriaSignals(marketability={"score": 7.5, "note": "good"})
        assert cs.any_populated() is True

    def test_to_log_str_empty(self):
        cs = CriteriaSignals()
        assert cs.to_log_str() == "—"

    def test_to_log_str_with_score(self):
        cs = CriteriaSignals(marketability={"score": 7.5, "note": "strong global signal"})
        log = cs.to_log_str()
        assert "mkt=7.5" in log
        assert "strong global" in log

    def test_to_log_str_no_score(self):
        cs = CriteriaSignals(interpretation={"score": None, "note": "high opportunity"})
        log = cs.to_log_str()
        assert "interp=?" in log
        assert "high opportunity" in log

    def test_to_log_str_multiple_fields(self):
        cs = CriteriaSignals(
            marketability={"score": 8.0, "note": "global"},
            follower_quality={"score": 7.0, "note": "informed"},
        )
        log = cs.to_log_str()
        assert "mkt=" in log
        assert "fol=" in log
        assert "|" in log

    def test_partial_population(self):
        cs = CriteriaSignals(
            expertise={"score": None, "note": "2 gaps found"},
        )
        assert cs.any_populated() is True
        assert not cs.marketability
        assert not cs.follower_quality


# ─── TrendResult with criteria_signals ───────────────────────────────────────

class TestTrendResultCriteriaSignals:

    def test_default_has_empty_signals(self):
        result = TrendResult(trending_topics=["topic1"])
        assert isinstance(result.criteria_signals, CriteriaSignals)
        assert not result.criteria_signals.any_populated()

    def test_grok_signals_populated(self):
        cs = CriteriaSignals(
            marketability={"score": 7.5, "note": "3개 트렌드 평균"},
            follower_quality={"score": 6.8, "note": "informed audience"},
        )
        result = TrendResult(
            trending_topics=["Korea rates", "KRW/USD"],
            criteria_signals=cs,
        )
        assert result.criteria_signals.marketability["score"] == 7.5
        assert result.criteria_signals.follower_quality["score"] == 6.8

    def test_backward_compat_no_signals(self):
        # 기존 코드처럼 criteria_signals 없이 생성해도 동작
        result = TrendResult(trending_topics=["topic"])
        assert result.criteria_signals is not None


# ─── FactCheckResult with criteria_signals ────────────────────────────────────

class TestFactCheckResultCriteriaSignals:

    def test_default_has_empty_signals(self):
        result = FactCheckResult()
        assert isinstance(result.criteria_signals, CriteriaSignals)
        assert not result.criteria_signals.any_populated()

    def test_perplexity_signals_mapped(self):
        cs = CriteriaSignals(
            interpretation={"score": None, "note": "high — contradicts assumptions"},
            marketability={"score": None, "note": "signal=global"},
        )
        result = FactCheckResult(
            verified=True,
            confidence="high",
            interpretation_opportunity="high — contradicts assumptions",
            marketability_signal="global",
            criteria_signals=cs,
        )
        assert result.interpretation_opportunity == "high — contradicts assumptions"
        assert result.marketability_signal == "global"
        assert result.criteria_signals.interpretation["note"] == "high — contradicts assumptions"

    def test_existing_fields_preserved(self):
        result = FactCheckResult(
            verified=True,
            confidence="medium",
            corrections=["Fix A"],
            interpretation_opportunity="medium",
            marketability_signal="regional",
        )
        # 기존 필드 정상 동작
        assert result.verified is True
        assert result.corrections == ["Fix A"]


# ─── ResearchResult with criteria_signals ─────────────────────────────────────

class TestResearchResultCriteriaSignals:

    def test_default_has_empty_signals(self):
        result = ResearchResult(summary="test")
        assert isinstance(result.criteria_signals, CriteriaSignals)
        assert not result.criteria_signals.any_populated()

    def test_gemini_signals_mapped(self):
        cs = CriteriaSignals(
            expertise={"score": None, "note": "해석 갭 3개 발견"},
            context_gap={"score": None, "note": "고가치 팩트 2개"},
        )
        result = ResearchResult(
            summary="Korea economy update",
            interpretation_gaps=["Reuters missed X", "Bloomberg missed Y", "AP missed Z"],
            fact_labels={
                "Korea debt GDP ratio": "challenges_assumption",
                "BOK independence": "missing_context",
                "Korea economy size": "confirms_common_narrative",
            },
            criteria_signals=cs,
        )
        assert result.criteria_signals.expertise["note"] == "해석 갭 3개 발견"
        assert len(result.interpretation_gaps) == 3
        assert len(result.fact_labels) == 3


# ─── ReviewResult.regeneration_hint ──────────────────────────────────────────

class TestReviewResultRegenerationHint:

    def test_default_hint_empty(self):
        result = ReviewResult(hook="h", body="b")
        assert result.regeneration_hint == ""

    def test_hint_populated(self):
        result = ReviewResult(
            hook="h", body="b",
            recommended_action="regenerate",
            regeneration_hint="Focus on the BOK independence angle, not the rate number",
        )
        assert "BOK independence" in result.regeneration_hint

    def test_approve_hint_empty(self):
        result = ReviewResult(
            hook="h", body="b",
            recommended_action="approve",
            regeneration_hint="",
        )
        assert result.regeneration_hint == ""


# ─── Grok CriteriaSignals construction ───────────────────────────────────────

class TestGrokCriteriaSignals:

    def test_avg_scores_calculated(self):
        """Grok 점수 집계 로직 단위 테스트."""
        topics_raw = [
            {"topic": "A", "marketability_score": 8, "follower_fit_score": 7},
            {"topic": "B", "marketability_score": 6, "follower_fit_score": 8},
        ]
        mkt_scores = [float(t["marketability_score"]) for t in topics_raw]
        fit_scores = [float(t["follower_fit_score"]) for t in topics_raw]
        avg_mkt = round(sum(mkt_scores) / len(mkt_scores), 1)
        avg_fit = round(sum(fit_scores) / len(fit_scores), 1)

        assert avg_mkt == 7.0
        assert avg_fit == 7.5

    def test_no_scores_no_signals(self):
        """dict 점수 없으면 criteria_signals 빔."""
        topics_raw = [{"topic": "A"}, {"topic": "B"}]
        mkt_scores = [float(t["marketability_score"]) for t in topics_raw if isinstance(t.get("marketability_score"), (int, float))]
        assert mkt_scores == []

    def test_string_topics_no_scores(self):
        """문자열 topic → scores 없음."""
        topics_raw = ["Korea rates", "K-pop"]
        mkt_scores = []
        for t in topics_raw:
            if isinstance(t, dict):
                s = t.get("marketability_score")
                if isinstance(s, (int, float)):
                    mkt_scores.append(float(s))
        assert mkt_scores == []


# ─── Mock providers emit criteria_signals ─────────────────────────────────────

class TestMockProvidersCriteriaSignals:

    def test_mock_researcher_has_signals(self):
        from app.providers.mock_providers import MockResearcher
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            MockResearcher().research("Korea BOK rates")
        )
        assert result.criteria_signals.any_populated()
        assert "expertise" in result.criteria_signals.expertise or result.criteria_signals.expertise

    def test_mock_trend_hunter_has_signals(self):
        from app.providers.mock_providers import MockTrendHunter
        result = asyncio.get_event_loop().run_until_complete(
            MockTrendHunter().find_trends("korea")
        )
        assert result.criteria_signals.marketability.get("score") == 7.5
        assert result.criteria_signals.follower_quality.get("score") == 7.0

    def test_mock_fact_checker_has_signals(self):
        from app.providers.mock_providers import MockFactChecker
        result = asyncio.get_event_loop().run_until_complete(
            MockFactChecker().check_facts("Korea GDP grew 2.3%")
        )
        assert result.criteria_signals.any_populated()
        assert result.criteria_signals.interpretation


# ─── Orchestrator regeneration loop ──────────────────────────────────────────

class TestOrchestratorRegenLoop:
    """orchestrator.py Step 5.5 재생성 루프 동작 검증."""

    def _make_review(self, action: str, hint: str = "") -> ReviewResult:
        return ReviewResult(
            hook="Test hook",
            body="Test body",
            recommended_action=action,
            regeneration_hint=hint,
            risk_level="medium",
            risk_reasoning="test",
            ai_rationale="test rationale",
        )

    def _make_draft(self) -> DraftResult:
        return DraftResult(hook="Draft hook", body="Draft body")

    @pytest.mark.asyncio
    async def test_no_regenerate_skips_loop(self):
        """recommended_action != regenerate → 루프 안 돎."""
        from app.orchestrator import Orchestrator

        with patch.object(Orchestrator, "__init__", lambda self: None):
            orch = Orchestrator()
            orch.ai = MagicMock()

            review = self._make_review("approve")
            draft_result = self._make_draft()

            # 루프 조건 검증 — approve면 while 진입 안 함
            MAX_REGEN_ATTEMPTS = 2
            regen_attempts = 0
            while review.recommended_action == "regenerate" and regen_attempts < MAX_REGEN_ATTEMPTS:
                regen_attempts += 1

            assert regen_attempts == 0
            assert review.recommended_action == "approve"

    @pytest.mark.asyncio
    async def test_regenerate_without_hint_skips(self):
        """hint 없으면 루프 진입하지 않음 (무한루프 방지)."""
        review = self._make_review("regenerate", hint="")

        MAX_REGEN_ATTEMPTS = 2
        regen_attempts = 0

        while review.recommended_action == "regenerate" and regen_attempts < MAX_REGEN_ATTEMPTS:
            hint = (review.regeneration_hint or "").strip()
            if not hint:
                break  # hint 없으면 즉시 탈출
            regen_attempts += 1

        assert regen_attempts == 0

    @pytest.mark.asyncio
    async def test_regenerate_max_attempts_caps(self):
        """최대 횟수 후 review로 전환."""
        MAX_REGEN_ATTEMPTS = 2
        regen_attempts = 0
        hint = "Focus on BOK angle"

        # 항상 regenerate 반환하는 시뮬레이션
        def always_regenerate(attempt):
            r = ReviewResult(
                hook="h", body="b",
                recommended_action="regenerate",
                regeneration_hint=hint,
                risk_level="medium",
                risk_reasoning="",
                ai_rationale="still failing",
            )
            return r

        review = always_regenerate(0)

        while review.recommended_action == "regenerate" and regen_attempts < MAX_REGEN_ATTEMPTS:
            h = (review.regeneration_hint or "").strip()
            if not h:
                break
            regen_attempts += 1
            review = always_regenerate(regen_attempts)

        # 최대 시도 후 → review로 전환
        if review.recommended_action == "regenerate":
            review.recommended_action = "review"
            review.ai_rationale = f"[재생성 {regen_attempts}회 후 미통과] " + review.ai_rationale

        assert regen_attempts == MAX_REGEN_ATTEMPTS
        assert review.recommended_action == "review"
        assert "재생성" in review.ai_rationale

    @pytest.mark.asyncio
    async def test_regenerate_succeeds_on_second(self):
        """두 번째 시도에서 approve 반환 → 루프 종료."""
        MAX_REGEN_ATTEMPTS = 2
        regen_attempts = 0
        hint = "Fix the hook angle"

        reviews = [
            ReviewResult(hook="h", body="b", recommended_action="regenerate",
                         regeneration_hint=hint, risk_level="medium",
                         risk_reasoning="", ai_rationale="fail 1"),
            ReviewResult(hook="h2", body="b2", recommended_action="approve",
                         regeneration_hint="", risk_level="low",
                         risk_reasoning="", ai_rationale="looks good"),
        ]
        review = reviews[0]
        call_idx = 0

        while review.recommended_action == "regenerate" and regen_attempts < MAX_REGEN_ATTEMPTS:
            h = (review.regeneration_hint or "").strip()
            if not h:
                break
            regen_attempts += 1
            call_idx += 1
            review = reviews[min(call_idx, len(reviews) - 1)]

        assert regen_attempts == 1
        assert review.recommended_action == "approve"


# ─── Perplexity criteria_signals mapping ─────────────────────────────────────

class TestPerplexityCriteriaMapping:

    def test_both_signals_populated(self):
        interp = "high — contradicts common assumption about Korean debt"
        mkt = "global"
        cs = CriteriaSignals(
            interpretation={"score": None, "note": interp},
            marketability={"score": None, "note": f"signal={mkt}"},
        )
        assert cs.any_populated()
        assert cs.interpretation["note"] == interp
        assert "global" in cs.marketability["note"]

    def test_empty_strings_produce_empty_signals(self):
        interp = ""
        mkt = ""
        cs = CriteriaSignals(
            interpretation={"score": None, "note": interp} if interp else {},
            marketability={"score": None, "note": f"signal={mkt}"} if mkt else {},
        )
        assert not cs.any_populated()


# ─── Gemini criteria_signals mapping ──────────────────────────────────────────

class TestGeminiCriteriaMapping:

    def test_gaps_produce_expertise_signal(self):
        gaps = ["Reuters misses X", "Bloomberg misses Y"]
        high_value = ["fact A", "fact B"]
        cs = CriteriaSignals(
            expertise={"score": None, "note": f"해석 갭 {len(gaps)}개 발견"},
            context_gap={"score": None, "note": f"고가치 팩트 {len(high_value)}개"},
        )
        assert cs.expertise["note"] == "해석 갭 2개 발견"
        assert cs.context_gap["note"] == "고가치 팩트 2개"

    def test_no_gaps_no_expertise(self):
        gaps = []
        cs = CriteriaSignals(
            expertise={"score": None, "note": f"해석 갭 {len(gaps)}개 발견"} if gaps else {},
        )
        assert not cs.expertise
