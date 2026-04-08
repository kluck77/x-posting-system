"""
엔드투엔드 테스트 (Mock 모드)
==============================
전체 파이프라인이 Mock 모드에서 올바르게 동작하는지 테스트합니다.
"""

import pytest
from app.db import init_db
from app.models.content import (
    SourceItemCreate, ApprovalStatus, ContentCategory,
)
from app.orchestrator import Orchestrator


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_pipeline_mock(self, db_session):
        """전체 파이프라인 (Mock 모드) 테스트"""
        orchestrator = Orchestrator(db=db_session)

        # Phase A 필터 통과를 위해 입력 문자열만 교체 (assertion/구조 무변경)
        data = SourceItemCreate(
            title="Korea demographic decline shapes global semiconductor policy",
            url="https://example.com/test",
            source_text=(
                "Korea's structural demographic decline is reshaping global "
                "semiconductor policy. Samsung and SK hynix face US tariff "
                "pressure while the government proposes policy reform. "
                "This analysis explains why Korea matters for the global "
                "chip supply chain."
            ),
            source_type="manual",
            language="en",
        )

        # 파이프라인 실행
        result = await orchestrator.full_pipeline(data)

        assert result["success"] is True
        assert result["draft_id"] is not None
        assert result["hook"]
        assert result["body"]

    @pytest.mark.asyncio
    async def test_approve_and_publish_mock(self, db_session):
        """승인 → Mock 게시 테스트"""
        orchestrator = Orchestrator(db=db_session)

        # 1. 파이프라인 실행 (Phase A 필터 통과용 입력)
        data = SourceItemCreate(
            title="Samsung chip export to US amid China tariff pressure",
            source_text=(
                "Samsung semiconductor export to the US faces new tariff "
                "pressure from China trade policy. Korea chaebol structure "
                "and AI chip demand shape the outlook. Analysts explain "
                "why this matters for global supply."
            ),
        )
        result = await orchestrator.full_pipeline(data)
        draft_id = result["draft_id"]

        # 2. 승인
        approve_result = await orchestrator.handle_approval(draft_id, "approve")
        assert approve_result["success"] is True
        assert approve_result.get("x_post_id") is not None

        # 3. DB 확인
        draft = orchestrator.draft_service.get_by_id(draft_id)
        assert draft.approval_status == ApprovalStatus.PUBLISHED
        assert draft.x_post_id is not None

    @pytest.mark.asyncio
    async def test_reject_draft(self, db_session):
        """거절 테스트"""
        orchestrator = Orchestrator(db=db_session)

        # Phase A 필터 통과용 입력 (거절 테스트 목적은 유지)
        data = SourceItemCreate(
            title="Korea chaebol reform and structural analysis for global investors",
            source_text=(
                "Korea proposes structural chaebol reform policy amid US "
                "China semiconductor competition. This analysis explains "
                "why Samsung and Hyundai face regulation while global "
                "investors watch the policy outlook."
            ),
        )
        result = await orchestrator.full_pipeline(data)
        draft_id = result["draft_id"]

        reject_result = await orchestrator.handle_approval(draft_id, "reject")
        assert reject_result["success"] is True

        draft = orchestrator.draft_service.get_by_id(draft_id)
        assert draft.approval_status == ApprovalStatus.REJECTED

    @pytest.mark.asyncio
    async def test_defer_draft(self, db_session):
        """보류 테스트"""
        orchestrator = Orchestrator(db=db_session)

        # Phase A 필터 통과용 입력 (보류 테스트 목적은 유지)
        data = SourceItemCreate(
            title="Korea AI chip policy outlook for US China trade",
            source_text=(
                "Korea AI chip policy outlook is shaped by US China trade "
                "tension. Samsung and SK hynix navigate export regulation "
                "while the government proposes structural reform. "
                "Analysis explains why global readers should care."
            ),
        )
        result = await orchestrator.full_pipeline(data)
        draft_id = result["draft_id"]

        defer_result = await orchestrator.handle_approval(draft_id, "defer")
        assert defer_result["success"] is True

        draft = orchestrator.draft_service.get_by_id(draft_id)
        assert draft.approval_status == ApprovalStatus.DEFERRED
