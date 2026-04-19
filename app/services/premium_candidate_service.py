"""
프리미엄 Korea Brief 후보 관리 서비스 (Phase 3)
=================================================
premium_candidate로 태그된 드래프트를 수집, 랭킹, 상태 관리, 메모, 내보내기합니다.

상태 흐름: new → reviewing → shortlisted / postponed / rejected → promoted
Layer 2 원칙: 이 서비스 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.content import Draft, ApprovalStatus

logger = logging.getLogger(__name__)

# 프리미엄 후보 상태 (유효 값)
# skipped: Pulse top-pick 카드에서 "건너뛰기" 로 운영자가 직접 치운 상태.
#          top_pick 후보 풀에서 빠지고, /premium list / 전체보기 에는 여전히 남음.
PREMIUM_STATUSES = (
    "new", "reviewing", "shortlisted", "postponed", "rejected", "promoted", "skipped",
)

# 대상 독자 유형 (제안값)
TARGET_READER_TYPES = (
    "expat_workers",       # 한국 거주 외국인 근로자
    "foreign_investors",   # 해외 투자자
    "korea_watchers",      # 한국 관심 일반 독자
    "policy_researchers",  # 정책 연구자
    "business_operators",  # 한국 진출 기업 관계자
    "media_journalists",   # 해외 언론/미디어
    "students_academics",  # 유학생/학자
    "general_curious",     # 일반 호기심 독자
)


class PremiumCandidateService:
    """프리미엄 Korea Brief 후보 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 수집 (Collection) ──────────────────────────────────────────────

    def get_candidates(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[Draft]:
        """
        프리미엄 후보 목록 조회.

        Args:
            status: 특정 상태 필터 (None이면 전체)
            limit: 최대 반환 수

        Returns:
            monetization_score 내림차순 정렬된 Draft 목록
        """
        try:
            query = (
                self.db.query(Draft)
                .filter(
                    Draft.business_tags.isnot(None),
                    Draft.business_tags.contains("premium_candidate"),
                )
            )
            if status:
                query = query.filter(Draft.premium_status == status)
            return (
                query
                .order_by(Draft.monetization_score.desc().nullslast())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 후보 조회 실패: {e}")
            return []

    def get_candidate_by_id(self, draft_id: int) -> Draft | None:
        """특정 드래프트 조회 (premium_candidate 태그 확인)."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if draft and draft.business_tags and "premium_candidate" in draft.business_tags:
                return draft
            return None
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 조회 실패: {e}")
            return None

    def count_by_status(self) -> dict[str, int]:
        """상태별 후보 수 카운트."""
        try:
            candidates = (
                self.db.query(Draft)
                .filter(
                    Draft.business_tags.isnot(None),
                    Draft.business_tags.contains("premium_candidate"),
                )
                .all()
            )
            counts: dict[str, int] = {}
            for d in candidates:
                status = d.premium_status or "new"
                counts[status] = counts.get(status, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 카운트 실패: {e}")
            return {}

    # ── 상태 관리 (Status) ─────────────────────────────────────────────

    def update_status(self, draft_id: int, new_status: str) -> Draft | None:
        """
        프리미엄 후보 상태 변경.

        Args:
            draft_id: 드래프트 ID
            new_status: 새 상태 (new/reviewing/shortlisted/postponed/rejected/promoted)

        Returns:
            업데이트된 Draft 또는 None
        """
        if new_status not in PREMIUM_STATUSES:
            logger.warning(f"[PremiumCandidate] 유효하지 않은 상태: {new_status}")
            return None

        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None

            draft.premium_status = new_status
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[PremiumCandidate] draft_id={draft_id} → {new_status}")
            return draft
        except Exception as e:
            logger.error(f"[PremiumCandidate] 상태 변경 실패: {e}")
            self.db.rollback()
            return None

    # ── 메모 관리 (Note) ───────────────────────────────────────────────

    def set_note(self, draft_id: int, note: str) -> Draft | None:
        """
        프리미엄 후보에 운영자 메모 저장 (덮어쓰기).

        Args:
            draft_id: 드래프트 ID
            note: 운영자 메모 (최대 500자)
        """
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None

            draft.premium_note = note[:500]
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[PremiumCandidate] 메모 저장: draft_id={draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[PremiumCandidate] 메모 저장 실패: {e}")
            self.db.rollback()
            return None

    # ── 대상 독자 설정 ─────────────────────────────────────────────────

    def set_target_reader(self, draft_id: int, reader_type: str) -> Draft | None:
        """대상 독자 유형 설정."""
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None

            draft.target_reader_type = reader_type[:100]
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            return draft
        except Exception as e:
            logger.error(f"[PremiumCandidate] 독자 설정 실패: {e}")
            self.db.rollback()
            return None

    # ── 자동 초기화 ────────────────────────────────────────────────────

    def init_new_candidates(self) -> int:
        """
        premium_candidate 태그가 있지만 premium_status가 없는 드래프트에
        'new' 상태를 자동 설정합니다.

        Returns:
            초기화된 후보 수
        """
        try:
            candidates = (
                self.db.query(Draft)
                .filter(
                    Draft.business_tags.isnot(None),
                    Draft.business_tags.contains("premium_candidate"),
                    Draft.premium_status.is_(None),
                )
                .all()
            )
            count = 0
            now = datetime.now(timezone.utc)
            for d in candidates:
                d.premium_status = "new"
                d.premium_updated_at = now
                count += 1
            if count:
                self.db.commit()
                logger.info(f"[PremiumCandidate] {count}개 후보 'new' 상태 초기화")
            return count
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 자동 초기화 실패: {e}")
            self.db.rollback()
            return 0

    # ── 내보내기 (Export) ──────────────────────────────────────────────

    def export_candidates(
        self,
        status: str | None = None,
        days: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        프리미엄 후보를 구조화된 딕셔너리로 내보내기.

        Args:
            status: 상태 필터 (None이면 전체)
            days: 최근 N일 필터 (None이면 전체)
            limit: 최대 수

        Returns:
            후보 정보 딕셔너리 목록 (브리프 작성/리포트용)
        """
        try:
            query = (
                self.db.query(Draft)
                .filter(
                    Draft.business_tags.isnot(None),
                    Draft.business_tags.contains("premium_candidate"),
                )
            )
            if status:
                query = query.filter(Draft.premium_status == status)
            if days:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                query = query.filter(Draft.created_at >= cutoff)

            candidates = (
                query
                .order_by(Draft.monetization_score.desc().nullslast())
                .limit(limit)
                .all()
            )

            result = []
            for d in candidates:
                # business_tags 파싱
                biz_tags = []
                try:
                    biz_tags = json.loads(d.business_tags) if d.business_tags else []
                except Exception:
                    pass

                result.append({
                    "draft_id": d.id,
                    "hook": d.hook,
                    "body": d.body,
                    "category": d.category.value if d.category else None,
                    "risk_level": d.risk_level.value if d.risk_level else None,
                    "approval_status": d.approval_status.value if d.approval_status else None,
                    "monetization_score": d.monetization_score,
                    "premium_reason": d.premium_reason,
                    "premium_status": d.premium_status or "new",
                    "premium_note": d.premium_note,
                    "target_reader_type": d.target_reader_type,
                    "cta_type": d.cta_type,
                    "asset_goal": d.asset_goal,
                    "business_tags": biz_tags,
                    "b2b_candidate": d.b2b_candidate,
                    "b2b_target_audience": d.b2b_target_audience,
                    "b2b_use_case": d.b2b_use_case,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "premium_updated_at": d.premium_updated_at.isoformat() if d.premium_updated_at else None,
                    "source_title": d.source_item.title if d.source_item else None,
                    "source_url": d.source_item.url if d.source_item else None,
                })

            return result
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 내보내기 실패: {e}")
            return []

    # ── 요약 리포트 ────────────────────────────────────────────────────

    def format_summary(self) -> str:
        """프리미엄 후보 전체 요약 (텔레그램 출력용)."""
        try:
            counts = self.count_by_status()
            total = sum(counts.values())

            if total == 0:
                return "⭐ 프리미엄 Korea Brief 후보: 없음"

            lines = [
                f"⭐ <b>프리미엄 Korea Brief 후보</b> ({total}건)",
                "",
            ]

            status_labels = {
                "new": "🆕 신규",
                "reviewing": "👀 검토 중",
                "shortlisted": "📋 후보 확정",
                "postponed": "⏸️ 보류",
                "rejected": "❌ 제외",
                "promoted": "🚀 브리프 발행",
            }

            for status_key, label in status_labels.items():
                count = counts.get(status_key, 0)
                if count > 0:
                    lines.append(f"  {label}: {count}")

            # 상위 3개 후보 미리보기
            top = self.get_candidates(limit=3)
            if top:
                lines.append("")
                lines.append("📊 <b>상위 후보</b>:")
                for d in top:
                    score = d.monetization_score or 0
                    status = d.premium_status or "new"
                    hook_preview = (d.hook or "")[:40]
                    lines.append(
                        f"  • ID {d.id} [{status}] 💰{score} — {hook_preview}…"
                    )

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[PremiumCandidate] 요약 생성 실패: {e}")
            return "⭐ 프리미엄 요약 생성 실패"

    def format_candidate_detail(self, draft: Draft) -> str:
        """단일 프리미엄 후보 상세 정보 (텔레그램 출력용)."""
        try:
            lines = [
                f"⭐ <b>프리미엄 후보 #{draft.id}</b>",
                f"{'─' * 30}",
                f"",
                f"🎯 <b>Hook:</b> {draft.hook}",
                f"📝 <b>Body:</b> {draft.body[:200]}{'…' if len(draft.body or '') > 200 else ''}",
                f"",
                f"📂 카테고리: {draft.category.value if draft.category else '—'}",
                f"⚡ 리스크: {draft.risk_level.value if draft.risk_level else '—'}",
                f"💰 수익화 점수: {draft.monetization_score or 0}/100",
                f"📊 상태: {draft.premium_status or 'new'}",
            ]

            if draft.premium_reason:
                lines.append(f"💡 플래그 사유: {draft.premium_reason}")
            if draft.premium_note:
                lines.append(f"📝 운영자 메모: {draft.premium_note}")
            if draft.target_reader_type:
                lines.append(f"👤 대상 독자: {draft.target_reader_type}")
            if draft.cta_type:
                lines.append(f"📢 CTA: {draft.cta_type}")
            if draft.asset_goal:
                lines.append(f"🎯 자산 목표: {draft.asset_goal}")
            if draft.b2b_candidate:
                lines.append(f"🏢 B2B: {draft.b2b_target_audience or '—'} / {draft.b2b_use_case or '—'}")

            if draft.source_item:
                lines.append(f"")
                lines.append(f"🔗 소스: {draft.source_item.title[:60]}")
                if draft.source_item.url:
                    lines.append(f"   {draft.source_item.url}")

            lines.append(f"")
            lines.append(f"{'─' * 30}")
            lines.append(f"명령어:")
            lines.append(f"  /premium status {draft.id} reviewing")
            lines.append(f"  /premium note {draft.id} 메모 내용")
            lines.append(f"  /premium reader {draft.id} foreign_investors")

            return "\n".join(lines)
        except Exception as e:
            return f"⭐ 후보 상세 표시 실패: {e}"
