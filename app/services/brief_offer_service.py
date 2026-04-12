"""
Premium Korea Brief 오퍼 준비 서비스
=====================================
프리미엄 후보(premium_candidate)를 실제 브리프 오퍼로 전환하기 위한
경량 메타데이터 관리 레이어.

기존 premium_candidate_service 파이프라인 위에 얹는 구조:
- brief_type, brief_price_tier, brief_summary_note 관리
- premium_status 확장 (drafted, ready 추가)
- 오퍼 준비 상태 조회·내보내기

Layer 2 원칙: 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import Draft

logger = logging.getLogger(__name__)

# 브리프 상태 (기존 premium + drafted/ready 추가)
BRIEF_STATUSES = (
    "new", "reviewing", "shortlisted", "drafted",
    "ready", "postponed", "rejected", "promoted",
)

# 브리프 유형
BRIEF_TYPES = (
    "weekly_brief",
    "policy_brief",
    "market_brief",
    "issue_brief",
    "explainer_pack",
    "special_report",
)

# 대상 독자
BRIEF_TARGET_READERS = (
    "global_readers",
    "expats",
    "investors",
    "journalists",
    "policy_watchers",
    "researchers",
)

# 가격 티어
BRIEF_PRICE_TIERS = ("low", "mid", "premium")


class BriefOfferService:
    """Premium Korea Brief 오퍼 준비 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 조회 ──────────────────────────────────────────────────────

    def _base_query(self):
        return (
            self.db.query(Draft)
            .filter(
                Draft.business_tags.isnot(None),
                Draft.business_tags.contains("premium_candidate"),
            )
        )

    def get_briefs(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[Draft]:
        """프리미엄 후보(브리프) 목록 조회."""
        try:
            query = self._base_query()
            if status:
                query = query.filter(Draft.premium_status == status)
            return (
                query
                .order_by(Draft.monetization_score.desc().nullslast())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[Brief] 조회 실패: {e}")
            return []

    def get_brief_by_id(self, draft_id: int) -> Draft | None:
        """ID로 프리미엄 후보 조회."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if draft and draft.business_tags and "premium_candidate" in draft.business_tags:
                return draft
            return None
        except Exception:
            return None

    def count_by_status(self) -> dict[str, int]:
        """상태별 브리프 수."""
        try:
            candidates = self._base_query().all()
            counts: dict[str, int] = {}
            for d in candidates:
                s = d.premium_status or "new"
                counts[s] = counts.get(s, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"[Brief] 카운트 실패: {e}")
            return {}

    # ── 메타데이터 설정 ──────────────────────────────────────────

    def set_status(self, draft_id: int, new_status: str) -> Draft | None:
        """브리프 상태 변경."""
        if new_status not in BRIEF_STATUSES:
            logger.warning(f"[Brief] 유효하지 않은 상태: {new_status}")
            return None
        try:
            draft = self.get_brief_by_id(draft_id)
            if not draft:
                return None
            draft.premium_status = new_status
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[Brief] 상태 변경: #{draft_id} → {new_status}")
            return draft
        except Exception as e:
            logger.error(f"[Brief] 상태 변경 실패: {e}")
            self.db.rollback()
            return None

    def set_brief_type(self, draft_id: int, brief_type: str) -> Draft | None:
        """브리프 유형 설정."""
        try:
            draft = self.get_brief_by_id(draft_id)
            if not draft:
                return None
            draft.brief_type = brief_type[:50]
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[Brief] 유형 설정: #{draft_id} → {brief_type}")
            return draft
        except Exception as e:
            logger.error(f"[Brief] 유형 설정 실패: {e}")
            self.db.rollback()
            return None

    def set_target_reader(self, draft_id: int, reader: str) -> Draft | None:
        """대상 독자 설정."""
        try:
            draft = self.get_brief_by_id(draft_id)
            if not draft:
                return None
            draft.target_reader_type = reader[:100]
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[Brief] 독자 설정: #{draft_id} → {reader}")
            return draft
        except Exception as e:
            logger.error(f"[Brief] 독자 설정 실패: {e}")
            self.db.rollback()
            return None

    def set_price_tier(self, draft_id: int, tier: str) -> Draft | None:
        """가격 티어 설정."""
        if tier not in BRIEF_PRICE_TIERS:
            logger.warning(f"[Brief] 유효하지 않은 티어: {tier}")
            return None
        try:
            draft = self.get_brief_by_id(draft_id)
            if not draft:
                return None
            draft.brief_price_tier = tier
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[Brief] 티어 설정: #{draft_id} → {tier}")
            return draft
        except Exception as e:
            logger.error(f"[Brief] 티어 설정 실패: {e}")
            self.db.rollback()
            return None

    def set_summary_note(self, draft_id: int, note: str) -> Draft | None:
        """브리프 요약/피치 메모 저장."""
        try:
            draft = self.get_brief_by_id(draft_id)
            if not draft:
                return None
            draft.brief_summary_note = note[:500]
            draft.premium_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[Brief] 메모 저장: #{draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[Brief] 메모 저장 실패: {e}")
            self.db.rollback()
            return None

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_briefs(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """브리프 후보를 딕셔너리 리스트로 내보내기."""
        try:
            briefs = self.get_briefs(status=status, limit=limit)
            result = []
            for d in briefs:
                try:
                    tags = json.loads(d.business_tags) if d.business_tags else []
                except (json.JSONDecodeError, TypeError):
                    tags = []

                result.append({
                    "draft_id": d.id,
                    "hook": d.hook or "",
                    "body": (d.body or "")[:300],
                    "category": d.category.value if d.category else "",
                    "risk_level": d.risk_level.value if d.risk_level else "",
                    "monetization_score": d.monetization_score,
                    "premium_status": d.premium_status or "new",
                    "brief_type": d.brief_type,
                    "brief_price_tier": d.brief_price_tier,
                    "brief_summary_note": d.brief_summary_note,
                    "target_reader_type": d.target_reader_type,
                    "premium_reason": d.premium_reason,
                    "premium_note": d.premium_note,
                    "business_tags": tags,
                    "source_title": (
                        d.source_item.title if d.source_item else None
                    ),
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "premium_updated_at": (
                        d.premium_updated_at.isoformat() if d.premium_updated_at else None
                    ),
                })
            return result
        except Exception as e:
            logger.warning(f"[Brief] 내보내기 실패: {e}")
            return []

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_summary(self) -> str:
        """브리프 오퍼 현황 요약 텔레그램 메시지."""
        try:
            counts = self.count_by_status()
            total = sum(counts.values())

            if total == 0:
                return "📋 Premium Brief 후보 없음"

            status_labels = {
                "new": "🆕 신규",
                "reviewing": "🔍 검토중",
                "shortlisted": "⭐ 후보선정",
                "drafted": "📝 초안작성",
                "ready": "✅ 발행준비",
                "postponed": "⏸️ 보류",
                "rejected": "❌ 제외",
                "promoted": "🚀 발행완료",
            }

            lines = [
                f"📋 <b>Premium Korea Brief 오퍼</b>",
                f"총 {total}건",
                "",
            ]
            for s, label in status_labels.items():
                count = counts.get(s, 0)
                if count > 0:
                    lines.append(f"  {label}: {count}")

            # 브리프 유형 분포
            type_counts: dict[str, int] = {}
            try:
                briefs = self._base_query().filter(Draft.brief_type.isnot(None)).all()
                for d in briefs:
                    bt = d.brief_type
                    type_counts[bt] = type_counts.get(bt, 0) + 1
            except Exception:
                pass

            if type_counts:
                lines.append("")
                lines.append("<b>브리프 유형:</b>")
                for bt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
                    lines.append(f"  📄 {bt}: {cnt}")

            # 티어 분포
            tier_counts: dict[str, int] = {}
            try:
                tiered = self._base_query().filter(Draft.brief_price_tier.isnot(None)).all()
                for d in tiered:
                    t = d.brief_price_tier
                    tier_counts[t] = tier_counts.get(t, 0) + 1
            except Exception:
                pass

            if tier_counts:
                lines.append("")
                lines.append("<b>가격 티어:</b>")
                tier_labels = {"low": "💚 Low", "mid": "💛 Mid", "premium": "💎 Premium"}
                for t in ("low", "mid", "premium"):
                    cnt = tier_counts.get(t, 0)
                    if cnt > 0:
                        lines.append(f"  {tier_labels[t]}: {cnt}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[Brief] 요약 생성 실패: {e}")
            return "📋 Brief 요약 생성 실패"

    def format_brief_detail(self, draft: Draft) -> str:
        """단일 브리프 상세 텔레그램 메시지."""
        try:
            status_label = {
                "new": "🆕 신규",
                "reviewing": "🔍 검토중",
                "shortlisted": "⭐ 후보선정",
                "drafted": "📝 초안작성",
                "ready": "✅ 발행준비",
                "postponed": "⏸️ 보류",
                "rejected": "❌ 제외",
                "promoted": "🚀 발행완료",
            }.get(draft.premium_status or "new", "🆕 신규")

            tier_label = {
                "low": "💚 Low", "mid": "💛 Mid", "premium": "💎 Premium",
            }.get(draft.brief_price_tier or "", "—")

            lines = [
                f"📋 <b>Brief #{draft.id}</b>",
                f"{'─' * 30}",
                "",
                f"🎯 <b>Hook:</b> {(draft.hook or '')[:120]}",
                f"📊 상태: {status_label}",
            ]

            if draft.brief_type:
                lines.append(f"📄 유형: {draft.brief_type}")
            if draft.target_reader_type:
                lines.append(f"👥 대상: {draft.target_reader_type}")
            if draft.brief_price_tier:
                lines.append(f"💰 티어: {tier_label}")
            if draft.monetization_score:
                lines.append(f"📈 수익화 점수: {draft.monetization_score}")
            if draft.brief_summary_note:
                lines.append(f"📝 요약: {draft.brief_summary_note}")
            if draft.premium_reason:
                lines.append(f"💡 플래그 사유: {draft.premium_reason[:200]}")
            if draft.premium_note:
                lines.append(f"🗒️ 운영자 메모: {draft.premium_note}")

            if draft.b2b_candidate:
                lines.append(f"🏢 B2B 연계: {draft.b2b_target_audience or '—'}")

            lines.append("")
            if draft.category:
                lines.append(f"📂 카테고리: {draft.category.value}")
            if draft.risk_level:
                lines.append(f"⚠️ 위험도: {draft.risk_level.value}")

            if draft.source_item:
                lines.append(f"🔗 소스: {draft.source_item.title[:60]}")

            if draft.premium_updated_at:
                lines.append(
                    f"🕐 수정: {draft.premium_updated_at.strftime('%Y-%m-%d %H:%M')}"
                )

            return "\n".join(lines)
        except Exception as e:
            return f"📋 Brief 상세 표시 실패: {e}"
