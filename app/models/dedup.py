"""
Dedup / Candidate Pool 영속화 테이블
====================================
BREAKING dedup 상태와 Top5 CANDIDATE 풀을 프로세스 재시작 후에도 유지.

- BreakingDedupEntry : issue_key + sent_at → 6h 윈도우 dedup (§8)
- CandidatePoolEntry : CANDIDATE 기사 → 05:00 브리핑 선정 풀
- BreakingSentKey    : BREAKING_NOW 전송분 → Top5 제외 키
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.models.content import Base


class BreakingDedupEntry(Base):
    """BREAKING_NOW 전송 기록 (dedup 윈도우 판별용)."""

    __tablename__ = "breaking_dedup_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_key = Column(String(128), nullable=False, index=True)
    sent_at = Column(Float, nullable=False, comment="Unix epoch seconds")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<BreakingDedupEntry(issue_key='{self.issue_key}', sent_at={self.sent_at})>"


class CandidatePoolEntry(Base):
    """야간 CANDIDATE 기사 (Top5 선정 풀)."""

    __tablename__ = "candidate_pool_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    body = Column(Text, nullable=True)
    url = Column(String(2000), nullable=True)
    topic_domain = Column(String(50), nullable=False)
    matched_keywords_json = Column(String(500), nullable=False, comment="JSON list")
    breaking_reason = Column(String(500), nullable=True)
    urgency = Column(String(20), nullable=True)
    collected_at = Column(DateTime, nullable=False, comment="UTC")
    cycle_date = Column(String(10), nullable=False, index=True, comment="YYYY-MM-DD KST briefing date")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<CandidatePoolEntry(id={self.id}, title='{self.title[:30]}...')>"


class BreakingSentKey(Base):
    """BREAKING_NOW 전송 성공 기사 키 (Top5 제외용)."""

    __tablename__ = "breaking_sent_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_key = Column(String(128), nullable=False, index=True)
    cycle_date = Column(String(10), nullable=False, index=True, comment="YYYY-MM-DD KST briefing date")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<BreakingSentKey(issue_key='{self.issue_key}')>"
