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

        data = SourceItemCreate(
            title="한국 출산율 세계 최저",
            url="https://example.com/test",
            source_text="한국의 합계출산율이 0.72명으로 세계 최저를 기록했다.",
            source_type="manual",
            language="ko",
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

        # 1. 파이프라인 실행
        data = SourceItemCreate(
            title="테스트 뉴스",
            source_text="테스트용 뉴스 내용입니다.",
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

        data = SourceItemCreate(
            title="거절 테스트",
            source_text="이 초안은 거절될 것입니다.",
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

        data = SourceItemCreate(
            title="보류 테스트",
            source_text="이 초안은 보류될 것입니다.",
        )
        result = await orchestrator.full_pipeline(data)
        draft_id = result["draft_id"]

        defer_result = await orchestrator.handle_approval(draft_id, "defer")
        assert defer_result["success"] is True

        draft = orchestrator.draft_service.get_by_id(draft_id)
        assert draft.approval_status == ApprovalStatus.DEFERRED
