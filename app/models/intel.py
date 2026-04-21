"""
Crypto Intel — 수집 원자료 저장 테이블
======================================
외부 API (Open DART / Congress / Finnhub / CryptoPanic) 에서 받은
정규화 항목을 저장한다.

- content_hash unique index → dedup
- shortlisted / flagged_reason → 룰 기반 필터 결과
- raw_payload → JSON 덤프 (UI 비노출, 디버그/재필터링용)
- promoted_draft_id 컬럼은 Phase 2 에서 추가 예정 (본 Phase 1 미포함)
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

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

    def __repr__(self) -> str:
        return (
            f"<IntelItem(id={self.id}, source={self.source!r}, "
            f"category={self.category!r}, shortlisted={self.shortlisted})>"
        )
