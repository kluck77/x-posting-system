"""
tests/test_ko_routing.py
=========================
BREAKING/CANDIDATE 대상 금융 기사에 대한 영어 초안 우회 (Step 1.7) 테스트.
한국어 전용 라인으로 처리된 기사는 영어 초안 + 승인 카드가 생략되어야 한다.
"""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# requests_oauthlib 이 설치되지 않은 환경에서도 테스트 가능하도록 모의 모듈 주입
if "requests_oauthlib" not in sys.modules:
    _mock_oauth = ModuleType("requests_oauthlib")
    _mock_oauth.OAuth1 = MagicMock()  # type: ignore[attr-defined]
    sys.modules["requests_oauthlib"] = _mock_oauth

from app.models.content import (
    ContentCategory,
    RiskLevel,
    SourceItemCreate,
)
from app.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# 헬퍼: ClassificationResult 모의 객체
# ---------------------------------------------------------------------------
def _make_breaking_result(classification: str, topic_domain: str):
    """breaking_classifier.ClassificationResult 모의 객체 생성."""
    result = MagicMock()
    result.classification = classification
    result.topic_domain = topic_domain
    result.matched_keywords = ["기준금리"]
    result.breaking_reason = "테스트"
    result.urgency = "high"
    return result


# ---------------------------------------------------------------------------
# Step 1.7 분기 테스트
# ---------------------------------------------------------------------------
class TestKoRouting:
    """BREAKING/CANDIDATE + 대상 도메인 → 영어 초안 우회 검증."""

    @pytest.mark.asyncio
    async def test_breaking_now_finance_skips_english_draft(self, db_session):
        """BREAKING_NOW + 금융 → 영어 초안 생략, _skip_approval_card=True."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("BREAKING_NOW", "금융")

        with (
            patch("app.services.breaking_classifier.classify_article", return_value=br),
            patch("app.services.breaking_alert_service.send_breaking_alert", new_callable=AsyncMock, return_value=True),
        ):
            data = SourceItemCreate(
                title="한국은행 기준금리 인상 의결",
                url="https://example.com/1",
                source_text="한국은행 금융통화위원회가 기준금리를 인상하기로 의결했다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        # 영어 초안이 아닌 한국어 전용 마커
        assert "[BREAKING_NOW]" in draft.hook
        assert "한국어 전용 라인" in draft.body
        assert draft.category == ContentCategory.ECONOMY
        assert draft._skip_approval_card is True

    @pytest.mark.asyncio
    async def test_candidate_crypto_skips_english_draft(self, db_session):
        """CANDIDATE + 크립토 → 영어 초안 생략."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("CANDIDATE", "크립토")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="비트코인 ETF 현물 승인 추진",
                url="https://example.com/2",
                source_text="SEC가 비트코인 현물 ETF 승인을 추진 중이다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert "[CANDIDATE]" in draft.hook
        assert draft._skip_approval_card is True

    @pytest.mark.asyncio
    async def test_candidate_investment_skips_english_draft(self, db_session):
        """CANDIDATE + 투자 → 영어 초안 생략."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("CANDIDATE", "투자")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="기관 자금 유입 급증",
                url="https://example.com/3",
                source_text="기관 투자자 순매수 자금이 급증하고 있다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert "[CANDIDATE]" in draft.hook
        assert draft._skip_approval_card is True

    @pytest.mark.asyncio
    async def test_candidate_stock_skips_english_draft(self, db_session):
        """CANDIDATE + 주식 → 영어 초안 생략."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("CANDIDATE", "주식")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="코스피 외국인 순매수 전환",
                url="https://example.com/4",
                source_text="외국인 투자자가 코스피에서 순매수로 전환했다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert "[CANDIDATE]" in draft.hook
        assert draft._skip_approval_card is True

    @pytest.mark.asyncio
    async def test_hold_finance_keeps_english_draft(self, db_session):
        """HOLD + 금융 → 기존 영어 초안 파이프라인 유지."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("HOLD", "금융")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="금리 동향 보고서",
                url="https://example.com/5",
                source_text="금리 동향에 대한 보고서입니다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert "[HOLD]" not in draft.hook
        assert not getattr(draft, '_skip_approval_card', False)

    @pytest.mark.asyncio
    async def test_reject_keeps_english_draft(self, db_session):
        """REJECT → 기존 영어 초안 파이프라인 유지."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("REJECT", "none")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="아이돌 열애 보도",
                url="https://example.com/6",
                source_text="아이돌 그룹 멤버의 열애설이 보도되었다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert not getattr(draft, '_skip_approval_card', False)

    @pytest.mark.asyncio
    async def test_candidate_none_domain_keeps_english_draft(self, db_session):
        """CANDIDATE + none 도메인 → 기존 영어 초안 파이프라인 유지."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("CANDIDATE", "none")

        with patch("app.services.breaking_classifier.classify_article", return_value=br):
            data = SourceItemCreate(
                title="일반 사회 뉴스",
                url="https://example.com/7",
                source_text="사회 일반 뉴스 내용입니다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert not getattr(draft, '_skip_approval_card', False)

    @pytest.mark.asyncio
    async def test_no_breaking_result_keeps_english_draft(self, db_session):
        """breaking_result 없음 (분류기 미설치) → 기존 파이프라인 유지."""
        orchestrator = Orchestrator(db=db_session)

        with patch("app.services.breaking_classifier.classify_article", side_effect=ImportError("mock")):
            data = SourceItemCreate(
                title="분류기 없는 기사",
                url="https://example.com/8",
                source_text="분류기가 없는 환경의 기사입니다. " * 5,
                source_type="manual",
                language="ko",
            )
            draft = await orchestrator.ingest_and_generate(data)

        assert not getattr(draft, '_skip_approval_card', False)


# ---------------------------------------------------------------------------
# full_pipeline 승인 카드 분기 테스트
# ---------------------------------------------------------------------------
class TestFullPipelineRouting:
    """full_pipeline() 에서 승인 카드 전송 분기 검증."""

    @pytest.mark.asyncio
    async def test_breaking_now_skips_approval_card(self, db_session):
        """BREAKING_NOW + 금융 → full_pipeline 에서 telegram_sent=False."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("BREAKING_NOW", "금융")

        with (
            patch("app.services.breaking_classifier.classify_article", return_value=br),
            patch("app.services.breaking_alert_service.send_breaking_alert", new_callable=AsyncMock, return_value=True),
            patch.object(orchestrator, "send_for_approval", new_callable=AsyncMock) as mock_send,
        ):
            data = SourceItemCreate(
                title="한국은행 기준금리 인상 의결",
                url="https://example.com/1",
                source_text="한국은행 금융통화위원회가 기준금리를 인상하기로 의결했다. " * 5,
                source_type="manual",
                language="ko",
            )
            result = await orchestrator.full_pipeline(data)

        assert result["success"] is True
        assert result["telegram_sent"] is False
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_hold_sends_approval_card(self, db_session):
        """HOLD → full_pipeline 에서 기존대로 승인 카드 전송."""
        orchestrator = Orchestrator(db=db_session)
        br = _make_breaking_result("HOLD", "금융")

        with (
            patch("app.services.breaking_classifier.classify_article", return_value=br),
            patch.object(orchestrator, "send_for_approval", new_callable=AsyncMock, return_value=True) as mock_send,
        ):
            data = SourceItemCreate(
                title="금리 동향 보고서",
                url="https://example.com/5",
                source_text="금리 동향에 대한 보고서입니다. " * 5,
                source_type="manual",
                language="ko",
            )
            result = await orchestrator.full_pipeline(data)

        assert result["success"] is True
        assert result["telegram_sent"] is True
        mock_send.assert_called_once()
