"""
오케스트레이터 (5-역할 AI 파이프라인)
======================================
전체 워크플로를 조율합니다:

1. 소스 입력 → DB 저장
2. Researcher: 리서치 (Gemini / Mock)
3. DraftWriter: 초안 생성 (ChatGPT / Claude / Mock)
4. FactChecker: 팩트체크 (Perplexity / Mock)
5. Reviewer: 리스크 판단 & 최종 다듬기 (Claude / Mock)
6. 분류 & 위험도 확정
7. 텔레그램 승인 카드 전송
8. 승인 → X 게시
9. 결과 DB 저장 & 텔레그램 확인

별도: TrendHunter (Grok / Mock) — /trends 명령으로 트렌드 탐색
모든 게시는 사람의 승인이 필요합니다.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
    SourceItemCreate,
)
from app.services.source_service import SourceService
from app.services.draft_service import DraftService
from app.services.classifier import (
    classify_category, classify_risk,
    classify_community_risk, build_community_warning,
)
from app.services.prediction_service import predict_publish_time
from app.services.telegram_service import send_approval_card, send_publish_confirmation
from app.services.x_publisher import XPublisher
from app.services.rate_limiter import RateLimiter
from app.services.quality_scorer import (
    score_draft, score_5criteria, format_5criteria_report,
    should_regenerate, REGEN_THRESHOLD,
)
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

    async def ingest_and_generate(self, data: SourceItemCreate) -> Draft:
        """
        소스를 입력받아 전체 AI 파이프라인을 실행합니다.

        Steps:
        1. 소스 DB 저장
        2. Researcher: 배경 리서치
        3. DraftWriter: 초안 생성
        4. FactChecker: 팩트체크 (v1: mock)
        5. Reviewer: 최종 판단 & 다듬기
        6. 분류 & 위험도 확정
        7. 초안 DB 저장
        """
        logger.info(f"=== 파이프라인 시작: '{data.title[:50]}' ===")

        # Step 0: 일일 제한 확인
        can_draft, draft_msg = self.rate_limiter.can_create_draft()
        if not can_draft:
            raise RuntimeError(f"일일 제한 초과: {draft_msg}")

        # Step 1: 소스 저장
        logger.info("[1/6] 소스 DB 저장")
        source_item = self.source_service.ingest_manual(data)

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
                source_type=data.source_type,
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

        # Step 4.5: 5-Criteria 품질 필터 (Reviewer 전 사전 체크)
        criteria_result = score_5criteria(
            draft_result.hook, draft_result.body, data.source_type
        )
        logger.info(
            f"5-Criteria 결과: {criteria_result['total']}/100 [{criteria_result['action']}] "
            f"flags={criteria_result['flags']}"
        )
        if criteria_result["action"] == "reject":
            logger.warning(
                "5-Criteria REJECT — 초안이 품질 기준 미달. "
                "재생성 시도 (최대 1회)."
            )
            try:
                draft_result = await self.ai.draft_writer.generate_draft(
                    title=data.title,
                    source_text=data.source_text + "\n\nIMPROVEMENT REQUIRED: " + " | ".join(criteria_result["flags"]),
                    language=settings.default_language,
                    source_type=data.source_type,
                )
            except Exception as e:
                logger.warning(f"재생성 실패, 원본 사용: {e}")

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

        # 커뮤니티 입력 리스크 강제 적용
        is_community = data.source_type == "community_input"
        community_warning = None
        if is_community:
            logger.info("커뮤니티 입력 감지 — 리스크 재평가 적용")
            risk_level, risk_reasoning = classify_community_risk(
                data.title, data.source_text, category, risk_level, risk_reasoning,
            )
            community_warning = build_community_warning(
                data.title, data.source_text, category, risk_level,
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

        # 커뮤니티 경고 저장
        if community_warning:
            draft.community_warning = community_warning
            self.db.commit()
            logger.info(f"커뮤니티 경고 저장: draft_id={draft.id}")

        # 예측 게시 시간 계산
        try:
            pred_time, pred_reason = predict_publish_time(
                category=draft.category,
                risk_level=draft.risk_level,
                now=datetime.now(timezone.utc),
            )
            draft.predicted_publish_at = pred_time
            draft.prediction_reasoning = pred_reason
            self.db.commit()
            logger.info(f"예측 게시 시간: {pred_time.isoformat()} — {pred_reason}")
        except Exception as e:
            logger.warning(f"예측 게시 시간 계산 실패 (무시): {e}")

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

    async def get_trending_topics(self, topic_area: str = "korea") -> dict:
        """TrendHunter를 사용해 현재 트렌딩 토픽을 탐색합니다."""
        logger.info(f"트렌드 탐색: '{topic_area}'")
        try:
            result = await self.ai.trend_hunter.find_trends(topic_area)
            return {
                "success": True,
                "topics": result.trending_topics,
                "notes": result.relevance_notes,
            }
        except Exception as e:
            logger.error(f"트렌드 탐색 실패: {e}")
            return {"success": False, "error": str(e), "topics": []}

    def close(self):
        if self.db:
            self.db.close()
