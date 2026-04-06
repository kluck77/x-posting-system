"""
CTA 카피 블록 관리 서비스
==========================
재사용 가능한 CTA / 랜딩 카피 블록을 관리합니다.

대상 유형:
- newsletter_signup
- lead_magnet
- premium_teaser
- premium_waitlist
- b2b_inquiry

Layer 2 원칙: 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import CtaCopy, Draft

logger = logging.getLogger(__name__)

# CTA 카피 유형
CTA_COPY_TYPES = (
    "newsletter_signup",
    "lead_magnet",
    "premium_teaser",
    "premium_waitlist",
    "b2b_inquiry",
)


class CtaCopyService:
    """CTA 카피 블록 CRUD 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 생성 ──────────────────────────────────────────────────────

    def add_copy(self, cta_type: str, copy_text: str, note: str | None = None) -> CtaCopy | None:
        """새 CTA 카피 블록 추가."""
        if cta_type not in CTA_COPY_TYPES:
            logger.warning(f"[CtaCopy] 유효하지 않은 유형: {cta_type}")
            return None
        if not copy_text or not copy_text.strip():
            logger.warning("[CtaCopy] 빈 카피 텍스트")
            return None
        try:
            copy = CtaCopy(
                cta_type=cta_type,
                copy_text=copy_text[:1000],
                note=note[:500] if note else None,
                is_active=True,
            )
            self.db.add(copy)
            self.db.commit()
            self.db.refresh(copy)
            logger.info(f"[CtaCopy] 추가: #{copy.id} ({cta_type})")
            return copy
        except Exception as e:
            logger.error(f"[CtaCopy] 추가 실패: {e}")
            self.db.rollback()
            return None

    # ── 조회 ──────────────────────────────────────────────────────

    def get_by_id(self, copy_id: int) -> CtaCopy | None:
        """ID로 카피 조회."""
        try:
            return self.db.query(CtaCopy).filter(CtaCopy.id == copy_id).first()
        except Exception:
            return None

    def get_all(self, active_only: bool = False, limit: int = 50) -> list[CtaCopy]:
        """전체 카피 목록."""
        try:
            query = self.db.query(CtaCopy)
            if active_only:
                query = query.filter(CtaCopy.is_active == True)
            return query.order_by(CtaCopy.created_at.desc()).limit(limit).all()
        except Exception as e:
            logger.warning(f"[CtaCopy] 조회 실패: {e}")
            return []

    def get_by_type(self, cta_type: str, active_only: bool = True, limit: int = 20) -> list[CtaCopy]:
        """유형별 카피 목록."""
        try:
            query = self.db.query(CtaCopy).filter(CtaCopy.cta_type == cta_type)
            if active_only:
                query = query.filter(CtaCopy.is_active == True)
            return query.order_by(CtaCopy.created_at.desc()).limit(limit).all()
        except Exception as e:
            logger.warning(f"[CtaCopy] 유형별 조회 실패: {e}")
            return []

    def count_by_type(self) -> dict[str, int]:
        """유형별 카피 수 (활성만)."""
        try:
            copies = self.db.query(CtaCopy).filter(CtaCopy.is_active == True).all()
            counts: dict[str, int] = {}
            for c in copies:
                counts[c.cta_type] = counts.get(c.cta_type, 0) + 1
            return counts
        except Exception:
            return {}

    # ── 수정 ──────────────────────────────────────────────────────

    def edit_copy(self, copy_id: int, new_text: str) -> CtaCopy | None:
        """카피 텍스트 수정."""
        if not new_text or not new_text.strip():
            return None
        try:
            copy = self.get_by_id(copy_id)
            if not copy:
                return None
            copy.copy_text = new_text[:1000]
            copy.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(copy)
            logger.info(f"[CtaCopy] 수정: #{copy_id}")
            return copy
        except Exception as e:
            logger.error(f"[CtaCopy] 수정 실패: {e}")
            self.db.rollback()
            return None

    def set_note(self, copy_id: int, note: str) -> CtaCopy | None:
        """운영자 메모 설정."""
        try:
            copy = self.get_by_id(copy_id)
            if not copy:
                return None
            copy.note = note[:500]
            copy.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(copy)
            logger.info(f"[CtaCopy] 메모: #{copy_id}")
            return copy
        except Exception as e:
            logger.error(f"[CtaCopy] 메모 실패: {e}")
            self.db.rollback()
            return None

    def activate(self, copy_id: int) -> CtaCopy | None:
        """카피 활성화."""
        try:
            copy = self.get_by_id(copy_id)
            if not copy:
                return None
            copy.is_active = True
            copy.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(copy)
            logger.info(f"[CtaCopy] 활성화: #{copy_id}")
            return copy
        except Exception as e:
            logger.error(f"[CtaCopy] 활성화 실패: {e}")
            self.db.rollback()
            return None

    def deactivate(self, copy_id: int) -> CtaCopy | None:
        """카피 비활성화."""
        try:
            copy = self.get_by_id(copy_id)
            if not copy:
                return None
            copy.is_active = False
            copy.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(copy)
            logger.info(f"[CtaCopy] 비활성화: #{copy_id}")
            return copy
        except Exception as e:
            logger.error(f"[CtaCopy] 비활성화 실패: {e}")
            self.db.rollback()
            return None

    # ── 드래프트 연결 ─────────────────────────────────────────────

    def link_to_draft(self, draft_id: int, copy_id: int) -> Draft | None:
        """드래프트에 CTA 카피 블록 연결."""
        try:
            copy = self.get_by_id(copy_id)
            if not copy:
                return None
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if not draft:
                return None
            draft.cta_copy_id = copy_id
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[CtaCopy] 연결: draft #{draft_id} → copy #{copy_id}")
            return draft
        except Exception as e:
            logger.error(f"[CtaCopy] 연결 실패: {e}")
            self.db.rollback()
            return None

    def unlink_from_draft(self, draft_id: int) -> Draft | None:
        """드래프트에서 CTA 카피 연결 해제."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if not draft:
                return None
            draft.cta_copy_id = None
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[CtaCopy] 연결 해제: draft #{draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[CtaCopy] 연결 해제 실패: {e}")
            self.db.rollback()
            return None

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_copies(self, active_only: bool = False) -> list[dict]:
        """카피 라이브러리 구조화 내보내기."""
        try:
            copies = self.get_all(active_only=active_only)
            return [
                {
                    "id": c.id,
                    "cta_type": c.cta_type,
                    "copy_text": c.copy_text,
                    "note": c.note,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in copies
            ]
        except Exception as e:
            logger.warning(f"[CtaCopy] 내보내기 실패: {e}")
            return []

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_summary(self) -> str:
        """CTA 카피 라이브러리 요약."""
        try:
            counts = self.count_by_type()
            total = sum(counts.values())
            all_copies = self.get_all()
            inactive = sum(1 for c in all_copies if not c.is_active)

            if not all_copies:
                return "📋 CTA 카피 라이브러리 비어있음\n\n추가: <code>/cta copy add &lt;type&gt; &lt;text&gt;</code>"

            lines = [
                f"📋 <b>CTA 카피 라이브러리</b>",
                f"총 {len(all_copies)}건 (활성 {total}, 비활성 {inactive})",
                "",
            ]

            type_labels = {
                "newsletter_signup": "📰 Newsletter",
                "lead_magnet": "🎯 Lead Magnet",
                "premium_teaser": "⭐ Premium Teaser",
                "premium_waitlist": "💎 Premium Waitlist",
                "b2b_inquiry": "🏢 B2B Inquiry",
            }

            for ct, label in type_labels.items():
                cnt = counts.get(ct, 0)
                if cnt > 0:
                    lines.append(f"  {label}: {cnt}")

            return "\n".join(lines)
        except Exception as e:
            return f"📋 CTA 카피 요약 실패: {e}"

    def format_copy_detail(self, copy: CtaCopy) -> str:
        """단일 카피 상세 포맷."""
        try:
            status = "✅ 활성" if copy.is_active else "⏸️ 비활성"
            lines = [
                f"📋 <b>CTA 카피 #{copy.id}</b>",
                f"{'─' * 30}",
                "",
                f"📢 유형: {copy.cta_type}",
                f"📊 상태: {status}",
                "",
                f"📝 <b>카피:</b>",
                f"{copy.copy_text}",
            ]
            if copy.note:
                lines.append("")
                lines.append(f"📌 메모: {copy.note}")
            if copy.created_at:
                lines.append(f"🕐 생성: {copy.created_at.strftime('%Y-%m-%d %H:%M')}")
            if copy.updated_at:
                lines.append(f"🔄 수정: {copy.updated_at.strftime('%Y-%m-%d %H:%M')}")
            return "\n".join(lines)
        except Exception as e:
            return f"📋 카피 상세 실패: {e}"
