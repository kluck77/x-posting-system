"""
이메일/리드자석 메타데이터 서비스 (Phase 7)
=============================================
콘텐츠의 이메일 성장 의도(CTA, 리드 자산, 이메일 버킷/목표)를
관리하고 조회합니다.

Layer 2 원칙: 이 서비스 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import Draft

logger = logging.getLogger(__name__)

# CTA 유형 (기존 business_classifier와 일치 + premium_teaser 추가)
CTA_TYPES = (
    "follow",
    "reply",
    "newsletter_signup",
    "lead_magnet",
    "premium_waitlist",
    "premium_teaser",
    "b2b_inquiry",
)

# 리드 자산 유형
LEAD_ASSET_TYPES = (
    "pdf",
    "checklist",
    "timeline",
    "starter_pack",
    "weekly_brief",
    "issue_tracker",
)

# 이메일 버킷
EMAIL_BUCKETS = (
    "weekly_free",
    "onboarding",
    "lead_nurture",
    "premium_teaser",
    "premium_conversion",
    "b2b_nurture",
)

# 이메일 목표
EMAIL_GOALS = (
    "signup",
    "nurture",
    "convert",
    "tease",
    "retain",
)


class EmailLeadService:
    """이메일/리드자석 메타데이터 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── CTA 관리 ──────────────────────────────────────────────────

    def set_cta(self, draft_id: int, cta_type: str) -> Draft | None:
        """CTA 유형 설정."""
        if cta_type not in CTA_TYPES:
            logger.warning(f"[EmailLead] 유효하지 않은 cta_type: {cta_type}")
            return None
        return self._update_field(draft_id, "cta_type", cta_type)

    # ── 리드 자산 관리 ────────────────────────────────────────────

    def set_lead_asset(
        self, draft_id: int,
        name: str | None = None,
        asset_type: str | None = None,
        note: str | None = None,
    ) -> Draft | None:
        """리드 자산 메타데이터 설정."""
        try:
            draft = self._get_draft(draft_id)
            if not draft:
                return None
            if name is not None:
                draft.lead_asset_name = name[:200]
            if asset_type is not None:
                if asset_type not in LEAD_ASSET_TYPES:
                    logger.warning(f"[EmailLead] 유효하지 않은 lead_asset_type: {asset_type}")
                    return None
                draft.lead_asset_type = asset_type
            if note is not None:
                draft.lead_asset_note = note[:500]
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[EmailLead] 리드 자산 설정: #{draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[EmailLead] 리드 자산 설정 실패: {e}")
            self.db.rollback()
            return None

    # ── 이메일 버킷/목표 관리 ─────────────────────────────────────

    def set_email_bucket(self, draft_id: int, bucket: str) -> Draft | None:
        """이메일 버킷 설정."""
        if bucket not in EMAIL_BUCKETS:
            logger.warning(f"[EmailLead] 유효하지 않은 email_bucket: {bucket}")
            return None
        return self._update_field(draft_id, "email_bucket", bucket)

    def set_email_goal(self, draft_id: int, goal: str) -> Draft | None:
        """이메일 목표 설정."""
        if goal not in EMAIL_GOALS:
            logger.warning(f"[EmailLead] 유효하지 않은 email_goal: {goal}")
            return None
        return self._update_field(draft_id, "email_goal", goal)

    # ── 조회 ──────────────────────────────────────────────────────

    def get_by_cta(self, cta_type: str, limit: int = 20) -> list[Draft]:
        """CTA 유형별 드래프트 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(Draft.cta_type == cta_type)
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[EmailLead] CTA 조회 실패: {e}")
            return []

    def get_by_email_bucket(self, bucket: str, limit: int = 20) -> list[Draft]:
        """이메일 버킷별 드래프트 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(Draft.email_bucket == bucket)
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[EmailLead] 버킷 조회 실패: {e}")
            return []

    def get_lead_magnet_candidates(self, limit: int = 20) -> list[Draft]:
        """리드자석 관련 드래프트 조회 (lead_asset_name 있거나 cta=lead_magnet)."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    (Draft.lead_asset_name != None) |
                    (Draft.cta_type == "lead_magnet") |
                    (Draft.asset_goal == "lead_magnet_push")
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[EmailLead] 리드자석 조회 실패: {e}")
            return []

    def get_newsletter_candidates(self, limit: int = 20) -> list[Draft]:
        """뉴스레터 관련 드래프트 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    (Draft.cta_type == "newsletter_signup") |
                    (Draft.asset_goal == "newsletter_push") |
                    (Draft.email_bucket == "weekly_free")
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[EmailLead] 뉴스레터 조회 실패: {e}")
            return []

    def get_premium_teaser_candidates(self, limit: int = 20) -> list[Draft]:
        """프리미엄 티저 드래프트 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    (Draft.cta_type.in_(["premium_waitlist", "premium_teaser"])) |
                    (Draft.asset_goal == "premium_teaser") |
                    (Draft.email_bucket.in_(["premium_teaser", "premium_conversion"]))
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[EmailLead] 프리미엄 티저 조회 실패: {e}")
            return []

    # ── 그룹핑 ────────────────────────────────────────────────────

    def group_by_cta(self) -> dict[str, int]:
        """CTA 유형별 분포."""
        try:
            drafts = self.db.query(Draft).filter(
                Draft.cta_type != None, Draft.cta_type != ""
            ).all()
            groups = {}
            for d in drafts:
                groups[d.cta_type] = groups.get(d.cta_type, 0) + 1
            return groups
        except Exception:
            return {}

    def group_by_email_bucket(self) -> dict[str, int]:
        """이메일 버킷별 분포."""
        try:
            drafts = self.db.query(Draft).filter(
                Draft.email_bucket != None, Draft.email_bucket != ""
            ).all()
            groups = {}
            for d in drafts:
                groups[d.email_bucket] = groups.get(d.email_bucket, 0) + 1
            return groups
        except Exception:
            return {}

    def group_by_asset_type(self) -> dict[str, int]:
        """리드 자산 유형별 분포."""
        try:
            drafts = self.db.query(Draft).filter(
                Draft.lead_asset_type != None, Draft.lead_asset_type != ""
            ).all()
            groups = {}
            for d in drafts:
                groups[d.lead_asset_type] = groups.get(d.lead_asset_type, 0) + 1
            return groups
        except Exception:
            return {}

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_email_items(
        self,
        cta_filter: str | None = None,
        bucket_filter: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """이메일/리드 관련 항목 내보내기."""
        try:
            query = self.db.query(Draft).filter(
                (Draft.cta_type != None) |
                (Draft.email_bucket != None) |
                (Draft.lead_asset_name != None)
            )
            if cta_filter:
                query = query.filter(Draft.cta_type == cta_filter)
            if bucket_filter:
                query = query.filter(Draft.email_bucket == bucket_filter)

            drafts = query.order_by(Draft.created_at.desc()).limit(limit).all()
            return [
                {
                    "draft_id": d.id,
                    "hook": (d.hook or "")[:100],
                    "category": d.category.value if d.category else "",
                    "cta_type": d.cta_type,
                    "asset_goal": d.asset_goal,
                    "lead_asset_name": d.lead_asset_name,
                    "lead_asset_type": d.lead_asset_type,
                    "lead_asset_note": d.lead_asset_note,
                    "email_bucket": d.email_bucket,
                    "email_goal": d.email_goal,
                    "monetization_score": d.monetization_score,
                }
                for d in drafts
            ]
        except Exception as e:
            logger.warning(f"[EmailLead] 내보내기 실패: {e}")
            return []

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_summary(self) -> str:
        """이메일/리드 요약 텔레그램 메시지."""
        try:
            by_cta = self.group_by_cta()
            by_bucket = self.group_by_email_bucket()
            by_asset = self.group_by_asset_type()

            if not by_cta and not by_bucket and not by_asset:
                return "📧 이메일/리드 메타데이터 없음"

            lines = ["📧 <b>이메일/리드 현황</b>\n"]

            if by_cta:
                lines.append("<b>CTA 분포:</b>")
                for cta, cnt in sorted(by_cta.items(), key=lambda x: -x[1]):
                    lines.append(f"  📢 {cta}: {cnt}")
                lines.append("")

            if by_bucket:
                lines.append("<b>이메일 버킷:</b>")
                for bkt, cnt in sorted(by_bucket.items(), key=lambda x: -x[1]):
                    lines.append(f"  📬 {bkt}: {cnt}")
                lines.append("")

            if by_asset:
                lines.append("<b>리드 자산 유형:</b>")
                for at, cnt in sorted(by_asset.items(), key=lambda x: -x[1]):
                    lines.append(f"  📄 {at}: {cnt}")

            return "\n".join(lines)
        except Exception as e:
            return f"📧 이메일/리드 요약 생성 실패: {e}"

    def format_draft_detail(self, draft: Draft) -> str:
        """단일 드래프트 이메일/리드 상세."""
        try:
            lines = [
                f"📧 <b>이메일/리드 #{draft.id}</b>",
                f"{'─' * 30}",
                "",
                f"🎯 <b>Hook:</b> {(draft.hook or '')[:80]}",
            ]

            if draft.cta_type:
                lines.append(f"📢 CTA: {draft.cta_type}")
            if draft.asset_goal:
                lines.append(f"🎯 자산 목표: {draft.asset_goal}")

            lines.append("")

            if draft.lead_asset_name:
                lines.append(f"📄 리드 자산: {draft.lead_asset_name}")
            if draft.lead_asset_type:
                lines.append(f"📦 자산 유형: {draft.lead_asset_type}")
            if draft.lead_asset_note:
                lines.append(f"📝 자산 메모: {draft.lead_asset_note}")

            if draft.email_bucket:
                lines.append(f"📬 이메일 버킷: {draft.email_bucket}")
            if draft.email_goal:
                lines.append(f"🎯 이메일 목표: {draft.email_goal}")

            if draft.monetization_score:
                lines.append(f"💰 수익화 점수: {draft.monetization_score}")

            return "\n".join(lines)
        except Exception as e:
            return f"📧 상세 표시 실패: {e}"

    # ── 내부 헬퍼 ─────────────────────────────────────────────────

    def _get_draft(self, draft_id: int) -> Draft | None:
        """드래프트 조회."""
        try:
            return self.db.query(Draft).filter(Draft.id == draft_id).first()
        except Exception:
            return None

    def _update_field(self, draft_id: int, field: str, value: str) -> Draft | None:
        """단일 필드 업데이트."""
        try:
            draft = self._get_draft(draft_id)
            if not draft:
                return None
            setattr(draft, field, value)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[EmailLead] {field}={value}: #{draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[EmailLead] {field} 설정 실패: {e}")
            self.db.rollback()
            return None
