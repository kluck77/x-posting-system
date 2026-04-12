"""
뉴스레터 / 리드자석 운영 루틴 서비스
======================================
기존 EmailLeadService 위에 얹는 운영 레이어.
뉴스레터 기획, 리드자석 기획, 버킷별 후보 리뷰, 내보내기를 지원합니다.

이 서비스는 데이터를 '읽기 전용'으로 조회·포맷·내보냅니다.
쓰기(set_*)는 기존 EmailLeadService를 통해 수행합니다.

Layer 2 원칙: 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import Draft

logger = logging.getLogger(__name__)

# 뉴스레터 관련 버킷
NEWSLETTER_BUCKETS = ("weekly_free", "onboarding", "lead_nurture", "premium_teaser")


class NewsletterRoutineService:
    """뉴스레터 / 리드자석 운영 루틴 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 뉴스레터 후보 조회 ────────────────────────────────────────

    def get_by_bucket(self, bucket: str, limit: int = 20) -> list[Draft]:
        """특정 이메일 버킷의 후보 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(Draft.email_bucket == bucket)
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[Newsletter] 버킷 조회 실패: {e}")
            return []

    def get_weekly_free(self, limit: int = 20) -> list[Draft]:
        """weekly_free 버킷 후보."""
        return self.get_by_bucket("weekly_free", limit)

    def get_onboarding(self, limit: int = 20) -> list[Draft]:
        """onboarding 버킷 후보."""
        return self.get_by_bucket("onboarding", limit)

    def get_lead_nurture(self, limit: int = 20) -> list[Draft]:
        """lead_nurture 버킷 후보."""
        return self.get_by_bucket("lead_nurture", limit)

    def get_premium_teaser(self, limit: int = 20) -> list[Draft]:
        """premium_teaser 버킷 후보."""
        return self.get_by_bucket("premium_teaser", limit)

    def get_all_newsletter_candidates(self, limit: int = 20) -> list[Draft]:
        """뉴스레터 의도가 있는 모든 후보 (newsletter_signup CTA 또는 newsletter_push 또는 주요 버킷)."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    (Draft.cta_type == "newsletter_signup") |
                    (Draft.asset_goal == "newsletter_push") |
                    (Draft.email_bucket.in_(NEWSLETTER_BUCKETS))
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[Newsletter] 전체 후보 조회 실패: {e}")
            return []

    def get_lead_magnet_candidates(self, limit: int = 20) -> list[Draft]:
        """리드자석 관련 후보 (lead_asset_name 있거나 cta=lead_magnet)."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    (Draft.lead_asset_name.isnot(None)) |
                    (Draft.cta_type == "lead_magnet") |
                    (Draft.asset_goal == "lead_magnet_push")
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[Newsletter] 리드자석 조회 실패: {e}")
            return []

    def get_draft_by_id(self, draft_id: int) -> Draft | None:
        """ID로 드래프트 조회."""
        try:
            return self.db.query(Draft).filter(Draft.id == draft_id).first()
        except Exception:
            return None

    # ── 카운트/그룹 ──────────────────────────────────────────────

    def count_by_bucket(self) -> dict[str, int]:
        """뉴스레터 관련 버킷별 후보 수."""
        try:
            drafts = (
                self.db.query(Draft)
                .filter(Draft.email_bucket.in_(NEWSLETTER_BUCKETS))
                .all()
            )
            counts: dict[str, int] = {}
            for d in drafts:
                b = d.email_bucket
                counts[b] = counts.get(b, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"[Newsletter] 카운트 실패: {e}")
            return {}

    def count_lead_assets(self) -> dict[str, int]:
        """리드 자산 유형별 수."""
        try:
            drafts = (
                self.db.query(Draft)
                .filter(
                    Draft.lead_asset_type.isnot(None),
                    Draft.lead_asset_type != "",
                )
                .all()
            )
            counts: dict[str, int] = {}
            for d in drafts:
                t = d.lead_asset_type
                counts[t] = counts.get(t, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"[Newsletter] 리드자산 카운트 실패: {e}")
            return {}

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_newsletter(
        self,
        bucket: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """뉴스레터 후보 구조화 내보내기."""
        try:
            if bucket:
                drafts = self.get_by_bucket(bucket, limit)
            else:
                drafts = self.get_all_newsletter_candidates(limit)
            return [self._to_dict(d) for d in drafts]
        except Exception as e:
            logger.warning(f"[Newsletter] 내보내기 실패: {e}")
            return []

    def export_lead_magnets(self, limit: int = 20) -> list[dict]:
        """리드자석 후보 구조화 내보내기."""
        try:
            drafts = self.get_lead_magnet_candidates(limit)
            return [self._to_dict(d) for d in drafts]
        except Exception as e:
            logger.warning(f"[Newsletter] 리드자석 내보내기 실패: {e}")
            return []

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_newsletter_summary(self) -> str:
        """뉴스레터 운영 현황 요약."""
        try:
            bucket_counts = self.count_by_bucket()
            total = sum(bucket_counts.values())
            lead_counts = self.count_lead_assets()
            lead_total = sum(lead_counts.values())

            if total == 0 and lead_total == 0:
                return "📰 뉴스레터/리드 후보 없음"

            bucket_labels = {
                "weekly_free": "📰 Weekly Free",
                "onboarding": "👋 Onboarding",
                "lead_nurture": "🎯 Lead Nurture",
                "premium_teaser": "⭐ Premium Teaser",
            }

            lines = [
                "📰 <b>뉴스레터 운영 현황</b>",
                "",
            ]

            if total > 0:
                lines.append(f"<b>이메일 버킷</b> (총 {total}건):")
                for bkt in NEWSLETTER_BUCKETS:
                    cnt = bucket_counts.get(bkt, 0)
                    if cnt > 0:
                        label = bucket_labels.get(bkt, bkt)
                        lines.append(f"  {label}: {cnt}")
                lines.append("")

            if lead_total > 0:
                lines.append(f"<b>리드 자산</b> (총 {lead_total}건):")
                for at, cnt in sorted(lead_counts.items(), key=lambda x: -x[1]):
                    lines.append(f"  📄 {at}: {cnt}")
                lines.append("")

            # 최근 후보 미리보기
            recent = self.get_all_newsletter_candidates(limit=3)
            if recent:
                lines.append("<b>최근 후보:</b>")
                for d in recent:
                    bucket = d.email_bucket or "—"
                    goal = d.email_goal or "—"
                    lines.append(
                        f"  • ID {d.id} [{bucket}] 🎯{goal}\n"
                        f"    {(d.hook or '')[:45]}…"
                    )

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[Newsletter] 요약 생성 실패: {e}")
            return "📰 뉴스레터 요약 생성 실패"

    def format_newsletter_detail(self, draft: Draft) -> str:
        """뉴스레터/리드 후보 상세 포맷."""
        try:
            lines = [
                f"📰 <b>뉴스레터/리드 #{draft.id}</b>",
                f"{'─' * 30}",
                "",
                f"🎯 <b>Hook:</b> {(draft.hook or '')[:120]}",
                f"📝 <b>Body:</b> {(draft.body or '')[:200]}{'…' if len(draft.body or '') > 200 else ''}",
                "",
            ]

            if draft.email_bucket:
                lines.append(f"📬 버킷: {draft.email_bucket}")
            if draft.email_goal:
                lines.append(f"🎯 목표: {draft.email_goal}")
            if draft.cta_type:
                lines.append(f"📢 CTA: {draft.cta_type}")
            if draft.asset_goal:
                lines.append(f"🏷️ 자산 목표: {draft.asset_goal}")

            if draft.lead_asset_name or draft.lead_asset_type:
                lines.append("")
                lines.append("<b>리드 자산:</b>")
                if draft.lead_asset_name:
                    lines.append(f"  📄 이름: {draft.lead_asset_name}")
                if draft.lead_asset_type:
                    lines.append(f"  📦 유형: {draft.lead_asset_type}")
                if draft.lead_asset_note:
                    lines.append(f"  📝 메모: {draft.lead_asset_note}")

            lines.append("")
            if draft.category:
                lines.append(f"📂 카테고리: {draft.category.value}")
            if draft.monetization_score:
                lines.append(f"💰 수익화 점수: {draft.monetization_score}")

            if draft.source_item:
                lines.append(f"🔗 소스: {draft.source_item.title[:60]}")

            return "\n".join(lines)
        except Exception as e:
            return f"📰 상세 표시 실패: {e}"

    def format_lead_detail(self, draft: Draft) -> str:
        """리드자석 후보 상세 포맷 (자산 정보 강조)."""
        try:
            lines = [
                f"📄 <b>리드자석 #{draft.id}</b>",
                f"{'─' * 30}",
                "",
                f"🎯 <b>Hook:</b> {(draft.hook or '')[:120]}",
                "",
            ]

            # 리드 자산 섹션 (강조)
            lines.append("<b>리드 자산 정보:</b>")
            lines.append(f"  📄 이름: {draft.lead_asset_name or '미설정'}")
            lines.append(f"  📦 유형: {draft.lead_asset_type or '미설정'}")
            lines.append(f"  📝 메모: {draft.lead_asset_note or '미설정'}")
            lines.append("")

            if draft.cta_type:
                lines.append(f"📢 CTA: {draft.cta_type}")
            if draft.asset_goal:
                lines.append(f"🏷️ 자산 목표: {draft.asset_goal}")
            if draft.email_bucket:
                lines.append(f"📬 버킷: {draft.email_bucket}")
            if draft.email_goal:
                lines.append(f"🎯 목표: {draft.email_goal}")

            if draft.monetization_score:
                lines.append(f"💰 수익화 점수: {draft.monetization_score}")
            if draft.category:
                lines.append(f"📂 카테고리: {draft.category.value}")

            if draft.source_item:
                lines.append(f"🔗 소스: {draft.source_item.title[:60]}")

            return "\n".join(lines)
        except Exception as e:
            return f"📄 리드자석 상세 실패: {e}"

    # ── 내부 ──────────────────────────────────────────────────────

    def _to_dict(self, d: Draft) -> dict:
        """드래프트를 내보내기용 딕셔너리로 변환."""
        return {
            "draft_id": d.id,
            "hook": (d.hook or "")[:200],
            "body": (d.body or "")[:300],
            "category": d.category.value if d.category else "",
            "cta_type": d.cta_type,
            "asset_goal": d.asset_goal,
            "lead_asset_name": d.lead_asset_name,
            "lead_asset_type": d.lead_asset_type,
            "lead_asset_note": d.lead_asset_note,
            "email_bucket": d.email_bucket,
            "email_goal": d.email_goal,
            "monetization_score": d.monetization_score,
            "source_title": d.source_item.title if d.source_item else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
