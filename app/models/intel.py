"""
Crypto Intel — 수집 원자료 저장 테이블
======================================
외부 API (Open DART / Congress / Finnhub / CryptoPanic) 에서 받은
정규화 항목을 저장한다.

- content_hash unique index → dedup
- shortlisted / flagged_reason → 룰 기반 필터 결과 (Phase 1)
- raw_payload → JSON 덤프 (UI 비노출, 디버그/재필터링용)
- priority_score / score_label / why_flagged_human (Phase 2)
- promoted_draft_id / promoted_at / promotion_status (Phase 2)
    → 기존 Orchestrator 합류 상태. 중복 전송 방지.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
)

from app.models.content import Base


class IntelItem(Base):
    __tablename__ = "intel_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False, index=True)
    source_type = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    url = Column(String(2000), nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    entity = Column(String(300), nullable=True)
    category = Column(String(50), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    raw_payload = Column(Text, nullable=True)
    shortlisted = Column(Boolean, nullable=False, default=False, index=True)
    flagged_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Phase 2 — 운영자 UX (점수 / 라벨 / 사람용 이유)
    priority_score = Column(Integer, nullable=False, default=0, index=True)
    score_label = Column(String(20), nullable=False, default="noise")
    why_flagged_human = Column(Text, nullable=True)

    # Phase 2 — Telegram promote 상태
    promoted_draft_id = Column(
        Integer, ForeignKey("drafts.id"), nullable=True,
    )
    promoted_at = Column(DateTime, nullable=True)
    promotion_status = Column(
        String(20), nullable=False, default="none", index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<IntelItem(id={self.id}, source={self.source!r}, "
            f"score={self.priority_score}, label={self.score_label!r}, "
            f"promo={self.promotion_status!r})>"
        )
