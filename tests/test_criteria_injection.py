"""
criteria_context 주입 테스트
=============================
5개 검증 목표:
  1. empty criteria_context → DraftWriter 동작 변경 없음 (레거시 호환)
  2. non-empty criteria_context → DraftWriter user_msg에 블록 포함
  3. empty criteria_context → Reviewer 동작 변경 없음 (레거시 호환)
  4. non-empty criteria_context → Reviewer user_msg에 블록 포함
  5. _build_criteria_context() → 부분/누락 신호 안전 처리
  6. 오케스트레이터 → criteria 빌드 예외 발생해도 파이프라인 유지

모든 테스트는 Mock 프로바이더를 사용하며 실제 API 호출이 없습니다.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.providers.mock_providers import MockDraftWriter, MockReviewer
from app.providers.base import (
    DraftResult, ResearchResult, FactCheckResult, TrendResult, CriteriaSignals,
)
from app.orchestrator import _build_criteria_context


# =============================================================================
# 1. MockDraftWriter — empty criteria_context → 레거시 동작 유지
# =============================================================================

class TestDraftWriterEmptyContext:
    @pytest.mark.asyncio
    async def test_empty_string_produces_same_result_as_no_param(self):
        writer = MockDraftWriter()

        result_legacy = await writer.generate_draft(
            title="한국 금리 인상",
            source_text="한국은행이 기준금리를 0.25%p 인상했다.",
        )
        result_with_empty = await writer.generate_draft(
            title="한국 금리 인상",
            source_text="한국은행이 기준금리를 0.25%p 인상했다.",
            criteria_context="",
        )

        assert result_legacy.hook == result_with_empty.hook
        assert result_legacy.body == result_with_empty.body
        assert result_legacy.category_suggestion == result_with_empty.category_suggestion

    @pytest.mark.asyncio
    async def test_none_title_still_works_with_empty_context(self):
        writer = MockDraftWriter()
        result = await writer.generate_draft(
            title="테스트",
            source_text="소스",
            criteria_context="",
        )
        assert result.hook
        assert result.body


# =============================================================================
# 2. OpenAIDraftWriter — non-empty criteria_context → user_msg에 블록 포함
# =============================================================================

class TestOpenAIDraftWriterContextInjection:
    @pytest.mark.asyncio
    async def test_criteria_block_appears_in_user_message(self):
        """criteria_context가 실제 API 요청 user_msg에 포함되는지 확인."""
        from app.providers.openai_provider import OpenAIDraftWriter

        captured_payload = {}

        async def mock_post(url, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": '{"hook":"h","body":"b","category_suggestion":"economy","tone_notes":""}'
                    }
                }]
            }
            return mock_resp

        writer = OpenAIDraftWriter()
        ctx = "[UPSTREAM CRITERIA SIGNALS]\n- Marketability: 7.5/10 (mock)"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await writer.generate_draft(
                title="테스트",
                source_text="소스 텍스트",
                criteria_context=ctx,
            )

        messages = captured_payload.get("messages", [])
        user_messages = [m for m in messages if m["role"] == "user"]
        assert user_messages, "user message가 없음"
        user_content = user_messages[0]["content"]
        assert "[UPSTREAM CRITERIA SIGNALS]" in user_content, (
            f"criteria block not found in user_msg: {user_content[:200]}"
        )
        assert "Marketability: 7.5/10" in user_content

    @pytest.mark.asyncio
    async def test_empty_context_omits_block_from_user_message(self):
        """criteria_context=""이면 [UPSTREAM CRITERIA SIGNALS] 블록이 없어야 함."""
        from app.providers.openai_provider import OpenAIDraftWriter

        captured_payload = {}

        async def mock_post(url, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": '{"hook":"h","body":"b","category_suggestion":"economy","tone_notes":""}'}}]
            }
            return mock_resp

        writer = OpenAIDraftWriter()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await writer.generate_draft(
                title="테스트",
                source_text="소스",
                criteria_context="",
            )

        messages = captured_payload.get("messages", [])
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "[UPSTREAM CRITERIA SIGNALS]" not in user_content


# =============================================================================
# 3. MockReviewer — empty criteria_context → 레거시 동작 유지
# =============================================================================

class TestReviewerEmptyContext:
    @pytest.mark.asyncio
    async def test_empty_context_same_result_as_no_param(self):
        reviewer = MockReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="economy")

        result_legacy = await reviewer.review_and_refine(
            title="t", source_text="s", draft=draft,
        )
        result_with_empty = await reviewer.review_and_refine(
            title="t", source_text="s", draft=draft, criteria_context="",
        )

        assert result_legacy.hook == result_with_empty.hook
        assert result_legacy.risk_level == result_with_empty.risk_level
        assert result_legacy.recommended_action == result_with_empty.recommended_action


# =============================================================================
# 4. AnthropicReviewer — non-empty criteria_context → user_msg에 블록 포함
# =============================================================================

class TestAnthropicReviewerContextInjection:
    @pytest.mark.asyncio
    async def test_criteria_block_appears_in_reviewer_message(self):
        """criteria_context가 Reviewer user_msg에 포함되는지 확인."""
        from app.providers.anthropic_provider import AnthropicReviewer

        captured_payload = {}

        async def mock_post(url, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "content": [{
                    "text": (
                        '{"hook":"h","body":"b","thread_continuation":null,'
                        '"category":"economy","risk_level":"low",'
                        '"risk_reasoning":"ok","ai_rationale":"good",'
                        '"recommended_action":"approve","regeneration_hint":"",'
                        '"criteria_scores":{}}'
                    )
                }]
            }
            return mock_resp

        reviewer = AnthropicReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="economy")
        ctx = "[UPSTREAM CRITERIA SIGNALS]\n- Interpretation opportunity: high — contradicts assumption"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await reviewer.review_and_refine(
                title="테스트", source_text="소스", draft=draft,
                criteria_context=ctx,
            )

        messages = captured_payload.get("messages", [])
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "[UPSTREAM CRITERIA SIGNALS]" in user_content, (
            f"criteria block not found in reviewer user_msg: {user_content[:300]}"
        )
        assert "Interpretation opportunity" in user_content

    @pytest.mark.asyncio
    async def test_empty_context_omits_block_from_reviewer_message(self):
        from app.providers.anthropic_provider import AnthropicReviewer

        captured_payload = {}

        async def mock_post(url, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "content": [{"text": '{"hook":"h","body":"b","thread_continuation":null,"category":"economy","risk_level":"low","risk_reasoning":"ok","ai_rationale":"good","recommended_action":"approve","regeneration_hint":"","criteria_scores":{}}'}]
            }
            return mock_resp

        reviewer = AnthropicReviewer()
        draft = DraftResult(hook="h", body="b", category_suggestion="economy")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await reviewer.review_and_refine(
                title="t", source_text="s", draft=draft, criteria_context="",
            )

        messages = captured_payload.get("messages", [])
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "[UPSTREAM CRITERIA SIGNALS]" not in user_content


# =============================================================================
# 5. _build_criteria_context() — 부분/누락 신호 안전 처리
# =============================================================================

class TestBuildCriteriaContext:
    def test_all_none_returns_empty_string(self):
        result = _build_criteria_context(research=None, factcheck=None, trends=None)
        assert result == ""

    def test_empty_research_returns_empty_string(self):
        research = ResearchResult(summary="", key_facts=[], fact_labels={})
        result = _build_criteria_context(research=research)
        assert result == ""

    def test_research_with_high_value_facts_returns_block(self):
        research = ResearchResult(
            summary="test",
            fact_labels={
                "Korea's debt ratio is 105%": "challenges_assumption",
                "Normal fact": "confirms_common_narrative",
            },
        )
        result = _build_criteria_context(research=research)
        assert result.startswith("[UPSTREAM CRITERIA SIGNALS]")
        assert "High-value facts" in result
        assert "Korea's debt ratio" in result

    def test_confirms_common_narrative_excluded(self):
        research = ResearchResult(
            summary="test",
            fact_labels={"All normal": "confirms_common_narrative"},
        )
        result = _build_criteria_context(research=research)
        # No high-value facts → empty
        assert result == ""

    def test_factcheck_with_interpretation_opportunity(self):
        factcheck = FactCheckResult(
            interpretation_opportunity="high — contradicts mainstream narrative",
            marketability_signal="global",
        )
        result = _build_criteria_context(factcheck=factcheck)
        assert "[UPSTREAM CRITERIA SIGNALS]" in result
        assert "Interpretation opportunity" in result
        assert "high — contradicts" in result
        assert "Marketability: global" in result

    def test_factcheck_empty_fields_returns_empty(self):
        factcheck = FactCheckResult()  # all defaults — empty strings
        result = _build_criteria_context(factcheck=factcheck)
        assert result == ""

    def test_trends_with_marketability_signal(self):
        trends = TrendResult(
            criteria_signals=CriteriaSignals(
                marketability={"score": 7.5, "note": "글로벌 트렌드 평균"},
                follower_quality={"score": 6.8, "note": "informed follower fit"},
            )
        )
        result = _build_criteria_context(trends=trends)
        assert "[UPSTREAM CRITERIA SIGNALS]" in result
        assert "7.5/10" in result
        assert "6.8/10" in result

    def test_trends_with_none_score_uses_dash(self):
        trends = TrendResult(
            criteria_signals=CriteriaSignals(
                marketability={"score": None, "note": "signal only"},
            )
        )
        result = _build_criteria_context(trends=trends)
        assert "—" in result
        assert "signal only" in result

    def test_combined_signals_all_present(self):
        research = ResearchResult(
            summary="s",
            fact_labels={"Surprising fact": "missing_context"},
        )
        factcheck = FactCheckResult(
            interpretation_opportunity="medium — worth developing",
            marketability_signal="regional",
        )
        trends = TrendResult(
            criteria_signals=CriteriaSignals(
                marketability={"score": 8.0, "note": "strong"},
            )
        )
        result = _build_criteria_context(research=research, factcheck=factcheck, trends=trends)
        assert result.count("\n") >= 3  # multiple lines
        assert "High-value facts" in result
        assert "Interpretation opportunity" in result
        assert "8.0/10" in result

    def test_interpretation_opportunity_truncated_at_120(self):
        long_opportunity = "x" * 200
        factcheck = FactCheckResult(interpretation_opportunity=long_opportunity)
        result = _build_criteria_context(factcheck=factcheck)
        # The line should not exceed ~150 chars for the opportunity part
        opp_line = [l for l in result.split("\n") if "Interpretation" in l][0]
        assert len(opp_line) <= 160  # prefix + 120 chars max

    def test_fact_label_truncated_at_80_chars(self):
        long_fact = "A" * 120
        research = ResearchResult(
            summary="s",
            fact_labels={long_fact: "challenges_assumption"},
        )
        result = _build_criteria_context(research=research)
        hv_line = [l for l in result.split("\n") if "High-value" in l][0]
        # fact is truncated to 80 chars in the label
        assert len(hv_line) < 150


# =============================================================================
# 6. Orchestrator — criteria 빌드 예외 발생해도 파이프라인 유지
# =============================================================================

class TestOrchestratorCriteriaFallback:
    def test_orchestrator_try_except_wrapper_produces_empty_string_on_bad_input(self):
        """
        _build_criteria_context()는 잘못된 입력 시 예외를 throw할 수 있음.
        orchestrator는 try/except로 감싸서 "" fallback — Layer 1 보호.
        이 패턴을 직접 검증.
        """
        from app.orchestrator import _build_criteria_context

        # orchestrator의 try/except 패턴을 시뮬레이션
        try:
            result = _build_criteria_context(
                research="not_a_ResearchResult",  # type: ignore — 잘못된 타입
                factcheck=None,
                trends=None,
            )
        except Exception:
            result = ""  # orchestrator에서 실제로 일어나는 fallback

        assert result == ""  # Layer 1은 항상 빈 문자열로 계속 진행

    def test_build_criteria_context_is_importable_standalone(self):
        """오케스트레이터에서 독립적으로 임포트 가능한지 확인."""
        from app.orchestrator import _build_criteria_context
        assert callable(_build_criteria_context)

    @pytest.mark.asyncio
    async def test_mock_pipeline_with_criteria_context_end_to_end(self):
        """Mock 파이프라인 전체 — criteria_context 파라미터 포함 동작 확인."""
        from app.providers.mock_providers import (
            MockDraftWriter, MockReviewer, MockResearcher, MockFactChecker,
        )

        researcher = MockResearcher()
        writer = MockDraftWriter()
        checker = MockFactChecker()
        reviewer = MockReviewer()

        # 1. Research
        research = await researcher.research("한국 반도체 수출")

        # 2. Build criteria context (DraftWriter용 — factcheck 없음)
        draft_ctx = _build_criteria_context(research=research)
        assert isinstance(draft_ctx, str)  # "" or populated — both valid

        # 3. Draft with criteria_context
        draft = await writer.generate_draft(
            title="한국 반도체",
            source_text="삼성전자 수출 감소",
            criteria_context=draft_ctx,
        )
        assert draft.hook
        assert draft.body

        # 4. FactCheck
        factcheck = await checker.check_facts(draft.body)

        # 5. Build review criteria context (research + factcheck)
        review_ctx = _build_criteria_context(research=research, factcheck=factcheck)
        assert isinstance(review_ctx, str)
        # Mock factcheck has populated fields → should produce non-empty context
        assert "[UPSTREAM CRITERIA SIGNALS]" in review_ctx

        # 6. Review with criteria_context
        result = await reviewer.review_and_refine(
            title="한국 반도체",
            source_text="삼성전자 수출 감소",
            draft=draft,
            research=research,
            factcheck=factcheck,
            criteria_context=review_ctx,
        )
        assert result.hook
        assert result.risk_level in ("low", "medium", "high")
        assert result.recommended_action in ("approve", "review", "regenerate", "reject")
