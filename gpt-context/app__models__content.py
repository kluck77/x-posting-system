# app/models/content.py
"""
콘텐츠 데이터 모델
==================
데이터베이스 테이블 구조와 Pydantic 스키마를 정의합니다.
"""

import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Enum, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship
from pydantic import BaseModel, Field

Base = declarative_base()


class ContentCategory(str, enum.Enum):
    POLITICS = "politics"
    POLICY = "policy"
    ECONOMY = "economy"
    SOCIETY = "society"
    KPOP_CULTURE = "kpop_culture"
    EVERGREEN = "evergreen"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REGENERATE = "regenerate"
    PUBLISHED = "published"
    FAILED = "failed"


class SourceItem(Base):
    __tablename__ = "source_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=True)
    source_text = Column(Text, nullable=False)
    source_type = Column(String(50), default="manual")
    language = Column(String(10), default="ko")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    drafts = relationship("Draft", back_populates="source_item")


class Draft(Base):
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_item_id = Column(Integer, ForeignKey("source_items.id"), nullable=False)
    hook = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    thread_continuation = Column(Text, nullable=True)
    category = Column(Enum(ContentCategory), nullable=False)
    risk_level = Column(Enum(RiskLevel), nullable=False)
    risk_reasoning = Column(Text, nullable=True)
    ai_rationale = Column(Text, nullable=True)
    approval_status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False)
    telegram_message_id = Column(Integer, nullable=True)
    x_post_id = Column(String(100), nullable=True)
    x_post_url = Column(String(500), nullable=True)
    version = Column(Integer, default=1)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    published_at = Column(DateTime, nullable=True)
    # [TODO] predicted_publish_at = Column(DateTime, nullable=True)
    # [TODO] prediction_reasoning = Column(Text, nullable=True)
    source_item = relationship("SourceItem", back_populates="drafts")

    @property
    def full_text(self) -> str:
        return f"{self.hook}\n\n{self.body}"

    @property
    def text_length(self) -> int:
        return len(self.full_text)


class PostLog(Base):
    __tablename__ = "post_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("drafts.id"), nullable=False)
    action = Column(String(50), nullable=False)
    success = Column(Boolean, default=False)
    x_post_id = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    request_payload = Column(Text, nullable=True)
    response_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DraftResponse(BaseModel):
    id: int
    source_item_id: int
    hook: str
    body: str
    thread_continuation: Optional[str] = None
    category: ContentCategory
    risk_level: RiskLevel
    risk_reasoning: Optional[str] = None
    ai_rationale: Optional[str] = None
    approval_status: ApprovalStatus
    telegram_message_id: Optional[int] = None
    x_post_id: Optional[str] = None
    x_post_url: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime
    # [TODO] predicted_publish_at: Optional[datetime] = None
    # [TODO] prediction_reasoning: Optional[str] = None

    class Config:
        from_attributes = True
