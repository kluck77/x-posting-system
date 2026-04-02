"""
콘텐츠 데이터 모델
==================
데이터베이스 테이블 구조와 Pydantic 스키마를 정의합니다.

테이블 설명:
- source_items: 수집된 원본 소스 항목
- drafts: AI가 생성한 포스트 초안
- post_logs: X에 게시된 포스트 기록
"""

import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Enum, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship
from pydantic import BaseModel, Field

# SQLAlchemy 모델의 기본 클래스
Base = declarative_base()


# =============================================================================
# 열거형 (Enum) 정의
# =============================================================================

class ContentCategory(str, enum.Enum):
    """콘텐츠 카테고리 - 포스트의 주제 분류"""
    POLITICS = "politics"
    POLICY = "policy"
    ECONOMY = "economy"
    SOCIETY = "society"
    KPOP_CULTURE = "kpop_culture"
    EVERGREEN = "evergreen"
    CRYPTO = "crypto"         # 크립토/디파이 (AI 출력과 일치)
    COMMUNITY = "community"   # 한국 커뮤니티 반응 포스트


class RiskLevel(str, enum.Enum):
    """위험 수준 - 콘텐츠의 민감도"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(str, enum.Enum):
    """승인 상태 - 포스트의 현재 상태"""
    PENDING = "pending"           # 검토 대기 중
    APPROVED = "approved"         # 승인됨 (게시 예정)
    REJECTED = "rejected"         # 거절됨
    DEFERRED = "deferred"         # 나중에 검토
    REGENERATE = "regenerate"     # 재생성 요청
    PUBLISHED = "published"       # X에 게시 완료
    FAILED = "failed"             # 게시 실패


# =============================================================================
# SQLAlchemy 모델 (데이터베이스 테이블)
# =============================================================================

class SourceItem(Base):
    """
    수집된 원본 소스 항목 테이블.
    뉴스, RSS, 수동 입력 등에서 가져온 원본 콘텐츠를 저장합니다.
    """
    __tablename__ = "source_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, comment="소스 제목")
    url = Column(String(2000), nullable=True, comment="소스 URL")
    source_text = Column(Text, nullable=False, comment="원본 텍스트 내용")
    source_type = Column(String(50), default="manual", comment="소스 유형 (manual, rss, api 등)")
    language = Column(String(10), default="ko", comment="원본 언어")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="생성 시간"
    )

    # 이 소스에서 만들어진 초안들 (1:N 관계)
    drafts = relationship("Draft", back_populates="source_item")

    def __repr__(self):
        return f"<SourceItem(id={self.id}, title='{self.title[:30]}...')>"


class Draft(Base):
    """
    AI가 생성한 포스트 초안 테이블.
    하나의 소스에서 여러 초안이 생성될 수 있습니다 (재생성 포함).
    """
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_item_id = Column(Integer, ForeignKey("source_items.id"), nullable=False)

    # 생성된 콘텐츠
    hook = Column(String(500), nullable=False, comment="훅/제목 텍스트")
    body = Column(Text, nullable=False, comment="본문 텍스트 (X 포스트용)")
    thread_continuation = Column(Text, nullable=True, comment="스레드 연속 텍스트 (선택)")

    # 분류 및 위험도
    category = Column(Enum(ContentCategory), nullable=False, comment="콘텐츠 카테고리")
    risk_level = Column(Enum(RiskLevel), nullable=False, comment="위험 수준")
    risk_reasoning = Column(Text, nullable=True, comment="위험도 판단 근거")
    ai_rationale = Column(Text, nullable=True, comment="AI의 추천 이유")

    # 승인 상태
    approval_status = Column(
        Enum(ApprovalStatus), default=ApprovalStatus.PENDING,
        nullable=False, comment="승인 상태"
    )

    # 텔레그램 연동
    telegram_message_id = Column(Integer, nullable=True, comment="텔레그램 메시지 ID")

    # X 게시 결과
    x_post_id = Column(String(100), nullable=True, comment="X 포스트 ID")
    x_post_url = Column(String(500), nullable=True, comment="X 포스트 URL")

    # 버전 관리 (재생성 시 version 증가)
    version = Column(Integer, default=1, comment="초안 버전 번호")

    # 에러 기록
    error_message = Column(Text, nullable=True, comment="마지막 에러 메시지")
    retry_count = Column(Integer, default=0, comment="재시도 횟수")

    # 타임스탬프
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="생성 시간"
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), comment="수정 시간"
    )
    published_at = Column(DateTime, nullable=True, comment="게시 시간")

    # 커뮤니티 입력 경고
    community_warning = Column(Text, nullable=True, comment="커뮤니티 기반 입력 경고 및 검증 필요 항목")

    # 예측 게시 시간
    predicted_publish_at = Column(DateTime, nullable=True, comment="예측 최적 게시 시간 (UTC)")
    prediction_reasoning = Column(Text, nullable=True, comment="예측 근거")

    # 댓글(reply) 대상 트윗 ID
    reply_to_tweet_id = Column(String(50), nullable=True, comment="답글 대상 트윗 ID (있으면 reply로 게시)")

    # 관계
    source_item = relationship("SourceItem", back_populates="drafts")

    def __repr__(self):
        return f"<Draft(id={self.id}, status={self.approval_status}, risk={self.risk_level})>"

    @property
    def full_text(self) -> str:
        """훅 + 본문을 합친 전체 포스트 텍스트"""
        return f"{self.hook}\n\n{self.body}"

    @property
    def text_length(self) -> int:
        """전체 포스트 텍스트의 글자 수"""
        return len(self.full_text)


class PostLog(Base):
    """
    게시 시도 로그 테이블.
    성공/실패 모든 시도를 기록합니다.
    """
    __tablename__ = "post_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("drafts.id"), nullable=False)
    action = Column(String(50), nullable=False, comment="동작 (publish, retry, fail)")
    success = Column(Boolean, default=False, comment="성공 여부")
    x_post_id = Column(String(100), nullable=True, comment="X 포스트 ID")
    error_message = Column(Text, nullable=True, comment="에러 메시지")
    request_payload = Column(Text, nullable=True, comment="API 요청 내용 (디버깅용)")
    response_payload = Column(Text, nullable=True, comment="API 응답 내용 (디버깅용)")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="기록 시간"
    )

    def __repr__(self):
        return f"<PostLog(id={self.id}, draft_id={self.draft_id}, success={self.success})>"


# =============================================================================
# Pydantic 스키마 (API 요청/응답용)
# =============================================================================

class SourceItemCreate(BaseModel):
    """소스 항목 생성 요청 스키마"""
    title: str = Field(..., min_length=1, max_length=500, description="소스 제목")
    url: Optional[str] = Field(None, max_length=2000, description="소스 URL")
    source_text: str = Field(..., min_length=1, description="원본 텍스트")
    source_type: str = Field("manual", description="소스 유형")
    language: str = Field("ko", description="원본 언어")


class DraftResponse(BaseModel):
    """초안 응답 스키마"""
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
    community_warning: Optional[str] = None
    predicted_publish_at: Optional[datetime] = None
    prediction_reasoning: Optional[str] = None

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    """헬스체크 응답"""
    status: str = "ok"
    mock_mode: bool = False
    telegram_configured: bool = False
    x_configured: bool = False
    database_ok: bool = False
