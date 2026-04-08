"""
오케스트레이터 (5-역할 AI 파이프라인)
======================================
전체 워크플로를 조율합니다:

1. 소스 입력 → DB 저장
2. Researcher: 리서치 (v1: mock)
3. DraftWriter: 초안 생성 (ChatGPT / Claude / mock)
4. Reviewer: 리스크 판단 & 최종 다듬기 (Claude / mock)
5. 분류 & 위험도 확정
6. 텔레그램 승인 카드 전송
7. 승인 → X 게시
8. 결과 DB 저장 & 텔레그램 확인

모든 게시는 사람의 승인이 필요합니다 (v1 기본값).
"""

import logging
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
    CandidateStatus, SourceItemCreate,
)
from app.services.source_service import SourceService
from app.services.draft_service import DraftService
from app.services.classifier import classify_category, classify_risk
from app.services.candidate_filter import (
    apply_result_to_source, evaluate_source_item,
)
from app.services.telegram_service import (
    send_approval_card, send_hold_card, send_publish_confirmation,
)
from app.services.x_publisher import XPublisher
from app.services.rate_limiter import RateLimiter
from app.providers.ai_provider import AITeam, create_ai_team
from app.providers.base import DraftResult, ResearchResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    5-역할 AI 파이프라인 오케스트레이터.

    파이프라인 흐름:
    [Source] → [Researcher] → [DraftWriter] → [Reviewer] → [분류/위험도]
            → [DB 저장] → [텔레그램 승인카드] → [승인] → [X 게시]
    """

    def __init__(self, db: Session | None = None):
        self.db = db or get_db()
        self.source_service = SourceService(self.db)
        self.draft_service = DraftService(self.db)
        self.x_publisher = XPublisher(self.db)
        self.rate_limiter = RateLimiter(self.db)
        self.ai: AITeam = create_ai_team()

    async def ingest_and_generate(self, data: SourceItemCreate) -> Draft | None:
        """
        소스를 입력받아 전체 AI 파이프라인을 실행합니다.

        Steps:
        1. 소스 DB 저장
        1.5. Phase A 후보 선별 (hard gate)
        2. Researcher: 배경 리서치
        3. DraftWriter: 초안 생성
        4. FactChecker: 팩트체크 (v1: mock)
        5. Reviewer: 최종 판단 & 다듬기
        6. 분류 & 위험도 확정
        7. 초안 DB 저장

        Returns:
            Draft  — passed 경로 (기존 동작)
            None   — rejected_l1 / rejected_score / hold 로 차단된 경우
        """
        logger.info(f"=== 파이프라인 시작: '{data.title[:50]}' ===")

        # Step 0: 일일 제한 확인
        can_draft, draft_msg = self.rate_limiter.can_create_draft()
        if not can_draft:
            raise RuntimeError(f"일일 제한 초과: {draft_msg}")

        # Step 1: 소스 저장
        logger.info("[1/6] 소스 DB 저장")
        source_item = self.source_service.ingest_manual(data)

        # Step 1.5: Phase A 후보 선별 (heuristic only, hard gate)
        cand_result = evaluate_source_item(source_item)
        apply_result_to_source(source_item, cand_result)
        self.db.commit()
        self.db.refresh(source_item)
        logger.info(
            f"[1.5/6] candidate_filter: status={cand_result.status.value}, "
            f"score={cand_result.score}"
        )

        if cand_result.status in (
            CandidateStatus.REJECTED_L1,
            CandidateStatus.REJECTED_SCORE,
        ):
            logger.info(
                f"Phase A reject → 초안 생성 차단: source_id={source_item.id}, "
                f"status={cand_result.status.value}"
            )
            return None

        if cand_result.status == CandidateStatus.HOLD:
            logger.info(
                f"Phase A hold → 텔레그램 후보 보류: source_id={source_item.id}, "
                f"score={cand_result.score}"
            )
            try:
                await send_hold_card(source_item)
            except Exception as e:
                logger.warning(f"Hold 카드 전송 실패 (무시): {e}")
            return None

        # 여기까지 왔으면 CandidateStatus.PASSED — 기존 draft 생성 경로 유지

        # Step 2: Researcher — 배경 리서치
        logger.info("[2/6] Researcher: 리서치")
        try:
            research = await self.ai.researcher.research(
                query=data.title, context=data.source_text[:1000],
            )
        except Exception as e:
            logger.warning(f"리서치 실패, 빈 결과 사용: {e}")
            research = ResearchResult(
                summary=data.source_text[:500],
                sources=[data.url] if data.url else [],
            )

        # Step 3: DraftWriter — 초안 생성
        logger.info("[3/6] DraftWriter: 초안 생성")
        try:
            draft_result = await self.ai.draft_writer.generate_draft(
                title=data.title,
                source_text=data.source_text,
                language=settings.default_language,
            )
        except Exception as e:
            logger.warning(f"DraftWriter 실패, 기본 초안 사용: {e}")
            draft_result = DraftResult(
                hook=f"🇰🇷 {data.title[:80]}",
                body=f"Korea update: {data.title[:200]}",
                category_suggestion="society",
            )

        # Step 4: FactChecker — 팩트체크
        logger.info("[4/6] FactChecker: 검증")
        try:
            factcheck = await self.ai.fact_checker.check_facts(
                claim=draft_result.body, context=data.source_text[:500],
            )
        except Exception as e:
            logger.warning(f"FactChecker 실패: {e}")
            factcheck = None

        # Step 5: Reviewer — 리스크 판단 & 최종 다듬기
        logger.info("[5/6] Reviewer: 최종 판단")
        try:
            review = await self.ai.reviewer.review_and_refine(
                title=data.title,
                source_text=data.source_text,
                draft=draft_result,
                research=research,
                factcheck=factcheck,
            )
        except Exception as e:
            logger.warning(f"Reviewer 실패, DraftWriter 결과 직접 사용: {e}")
            from app.providers.base import ReviewResult
            review = ReviewResult(
                hook=draft_result.hook,
                body=draft_result.body,
                thread_continuation=draft_result.thread_continuation,
                category=draft_result.category_suggestion,
                risk_level="medium",
                risk_reasoning=f"Reviewer 실패, 안전하게 medium 설정: {e}",
                ai_rationale="Fallback: reviewer unavailable.",
            )

        # Step 6: 분류 & 위험도 확정
        logger.info("[6/6] 분류 & 위험도 확정")
        try:
            category = ContentCategory(review.category)
        except ValueError:
            category = classify_category(data.title, data.source_text)

        try:
            risk_level = RiskLevel(review.risk_level)
            risk_reasoning = review.risk_reasoning
        except ValueError:
            risk_level, risk_reasoning = classify_risk(
                data.title, data.source_text, category,
            )

        # 중복 체크
        if self.draft_service.is_duplicate_text(review.body):
            logger.warning("중복 텍스트 감지!")

        # 초안 저장
        draft = self.draft_service.create_draft(
            source_item=source_item,
            hook=review.hook,
            body=review.body,
            category=category,
            risk_level=risk_level,
            risk_reasoning=risk_reasoning,
            ai_rationale=review.ai_rationale,
            thread_continuation=review.thread_continuation,
        )

        logger.info(
            f"=== 파이프라인 완료: draft_id={draft.id}, "
            f"category={category.value}, risk={risk_level.value} ==="
        )
        return draft

    async def send_for_approval(self, draft_id: int) -> bool:
        """초안을 텔레그램으로 보내서 승인을 요청합니다."""
        # 일일 텔레그램 전송 제한 확인
        can_send, send_msg = self.rate_limiter.can_send_telegram()
        if not can_send:
            logger.warning(f"텔레그램 전송 제한: {send_msg}")
            return False

        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            logger.error(f"초안 없음: draft_id={draft_id}")
            return False

        source_url = draft.source_item.url if draft.source_item else None
        message_id = await send_approval_card(draft, source_url)

        if message_id:
            self.draft_service.set_telegram_message_id(draft_id, message_id)
            return True
        elif not settings.has_telegram_config:
            logger.info(f"[Mock 텔레그램] 카드 전송됨 (Mock): draft_id={draft_id}")
            return True
        else:
            logger.error(f"텔레그램 전송 실패: draft_id={draft_id}")
            return False

    async def handle_approval(self, draft_id: int, action: str) -> dict:
        """텔레그램 승인/거절 액션을 처리합니다."""
        logger.info(f"승인 처리: draft_id={draft_id}, action={action}")

        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"초안 없음: {draft_id}"}

        if action == "approve":
            return await self._handle_approve(draft)
        elif action == "reject":
            self.draft_service.update_status(draft_id, ApprovalStatus.REJECTED)
            return {"success": True, "message": "거절됨"}
        elif action == "defer":
            self.draft_service.update_status(draft_id, ApprovalStatus.DEFERRED)
            return {"success": True, "message": "보류됨"}
        elif action == "regenerate":
            self.draft_service.update_status(draft_id, ApprovalStatus.REGENERATE)
            return await self._handle_regenerate(draft)
        else:
            return {"success": False, "error": f"알 수 없는 액션: {action}"}

    async def _handle_approve(self, draft: Draft) -> dict:
        """승인 → X에 게시"""
        # 일일 게시 제한 확인
        can_post, post_msg = self.rate_limiter.can_publish()
        if not can_post:
            return {"success": False, "error": f"일일 게시 한도 초과: {post_msg}"}

        self.draft_service.update_status(draft.id, ApprovalStatus.APPROVED)
        result = await self.x_publisher.publish(draft)

        if result.success:
            self.draft_service.mark_published(draft.id, result.post_id, result.post_url)
            updated = self.draft_service.get_by_id(draft.id)
            await send_publish_confirmation(updated)
            return {
                "success": True,
                "message": "X에 게시 완료!",
                "x_post_id": result.post_id,
                "x_post_url": result.post_url,
            }
        else:
            self.draft_service.mark_failed(draft.id, result.error_message or "Unknown")
            return {"success": False, "error": f"X 게시 실패: {result.error_message}"}

    async def _handle_regenerate(self, draft: Draft) -> dict:
        """재생성 → 같은 소스로 다시 파이프라인 실행"""
        source = draft.source_item
        if not source:
            return {"success": False, "error": "원본 소스 없음"}

        try:
            new_data = SourceItemCreate(
                title=source.title, url=source.url,
                source_text=source.source_text,
                source_type=source.source_type, language=source.language,
            )
            new_draft = await self.ingest_and_generate(new_data)
            if new_draft is None:
                return {
                    "success": False,
                    "filtered": True,
                    "error": "재생성 차단 (candidate_filter)",
                }
            await self.send_for_approval(new_draft.id)
            return {
                "success": True,
                "message": f"재생성 완료! 새 draft ID: {new_draft.id}",
                "new_draft_id": new_draft.id,
            }
        except Exception as e:
            logger.error(f"재생성 실패: {e}")
            return {"success": False, "error": str(e)}

    async def retry_failed(self, draft_id: int) -> dict:
        """실패한 게시를 재시도합니다."""
        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"초안 없음: {draft_id}"}
        if draft.approval_status != ApprovalStatus.FAILED:
            return {"success": False, "error": "실패 상태가 아닌 초안"}

        self.draft_service.update_status(draft_id, ApprovalStatus.APPROVED)
        draft.x_post_id = None
        return await self._handle_approve(draft)

    async def full_pipeline(self, data: SourceItemCreate) -> dict:
        """전체 파이프라인: 소스 입력 → AI 생성 → 텔레그램 승인카드 전송"""
        try:
            draft = await self.ingest_and_generate(data)
            if draft is None:
                # Phase A pre-filter 에서 차단된 경우 (rejected / hold)
                # 여기서는 draft 가 없음 → success=False, 이유만 돌려줌
                return {
                    "success": False,
                    "draft_id": None,
                    "filtered": True,
                    "error": "candidate_filter blocked draft creation",
                }
            sent = await self.send_for_approval(draft.id)
            return {
                "success": True,
                "draft_id": draft.id,
                "category": draft.category.value,
                "risk_level": draft.risk_level.value,
                "telegram_sent": sent,
                "hook": draft.hook,
                "body": draft.body,
                "message": "초안 생성 완료! 텔레그램에서 승인해주세요.",
            }
        except Exception as e:
            logger.error(f"파이프라인 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def close(self):
        if self.db:
            self.db.close()
