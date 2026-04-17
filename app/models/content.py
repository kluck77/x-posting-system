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

class CandidateStatus(str, enum.Enum):
    PASSED = "passed"
    HOLD = "hold"
    REJECTED_SCORE = "rejected_score"
    REJECTED_L1 = "rejected_l1"


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

    # Mock 생성 판별
    generated_in_mock = Column(Boolean, default=False, comment="Mock 모드에서 생성된 초안 여부")

    # ── Phase 4: 성과 로깅 기반 필드 ────────────────────────────────────────
    content_type = Column(
        String(50), nullable=True,
        comment="입력 소스 유형 (news_link/x_post/observation/screenshot_ref/raw_text)"
    )
    topic_tags = Column(
        String(500), nullable=True,
        comment="주제 태그 JSON 배열 — 예: '[\"economy\",\"BOK\",\"rates\"]'"
    )
    output_format = Column(
        String(20), nullable=True, default="single",
        comment="출력 형식: single | pack"
    )
    manual_notes = Column(
        Text, nullable=True,
        comment="사용자 수동 메모 (선택)"
    )

    # ── Phase 5: 비즈니스 분류 + 수익화 메타데이터 ──────────────────────────
    business_tags = Column(
        String(500), nullable=True,
        comment="비즈니스 태그 JSON 배열 — 예: '[\"growth\",\"newsletter\",\"premium_candidate\"]'"
    )
    cta_type = Column(
        String(50), nullable=True,
        comment="CTA 유형: follow/reply/newsletter_signup/lead_magnet/premium_waitlist/b2b_inquiry"
    )
    monetization_score = Column(
        Integer, nullable=True,
        comment="수익화 잠재력 점수 (0-100)"
    )
    asset_goal = Column(
        String(50), nullable=True,
        comment="자산 목표: x_only/newsletter_push/lead_magnet_push/premium_teaser/b2b_asset"
    )
    premium_reason = Column(
        Text, nullable=True,
        comment="프리미엄 브리프 후보 사유"
    )
    b2b_candidate = Column(
        Boolean, nullable=True, default=False,
        comment="B2B 리서치/리포트 후보 여부"
    )
    b2b_target_audience = Column(
        String(200), nullable=True,
        comment="B2B 대상 독자층 (예: foreign_investors, policy_makers, supply_chain)"
    )
    b2b_use_case = Column(
        String(200), nullable=True,
        comment="B2B 활용 사례 (예: market_entry, regulation_monitor, risk_assessment)"
    )
    b2b_note = Column(
        Text, nullable=True,
        comment="B2B 후보에 대한 운영자 상업/리서치 메모"
    )
    b2b_status = Column(
        String(20), nullable=True,
        comment="B2B 후보 상태: new/reviewing/shortlisted/postponed/rejected/promoted"
    )
    b2b_updated_at = Column(
        DateTime, nullable=True,
        comment="B2B 상태 마지막 변경 시간"
    )

    # ── Phase 7: 이메일/리드자석 메타데이터 ─────────────────────────────────
    lead_asset_name = Column(
        String(200), nullable=True,
        comment="리드 자산 이름 (예: Korea Labor Law 2025 Checklist)"
    )
    lead_asset_type = Column(
        String(50), nullable=True,
        comment="리드 자산 유형: pdf/checklist/timeline/starter_pack/weekly_brief/issue_tracker"
    )
    lead_asset_note = Column(
        Text, nullable=True,
        comment="리드 자산 운영자 메모"
    )
    email_bucket = Column(
        String(50), nullable=True,
        comment="이메일 버킷: weekly_free/onboarding/lead_nurture/premium_teaser/premium_conversion/b2b_nurture"
    )
    email_goal = Column(
        String(50), nullable=True,
        comment="이메일 목표: signup/nurture/convert/tease/retain"
    )

    # ── Brief Offer 메타데이터 (프리미엄 후보 → 오퍼 준비) ───────────────────
    brief_type = Column(
        String(50), nullable=True,
        comment="브리프 유형: weekly_brief/policy_brief/market_brief/issue_brief/explainer_pack/special_report"
    )
    brief_price_tier = Column(
        String(20), nullable=True,
        comment="가격 티어: low/mid/premium"
    )
    brief_summary_note = Column(
        Text, nullable=True,
        comment="브리프 오퍼 요약/피치 메모 (운영자 작성)"
    )

    # ── Phase 5-3: 프리미엄 후보 파이프라인 ─────────────────────────────────
    premium_status = Column(
        String(20), nullable=True,
        comment="프리미엄 후보 상태: new/reviewing/shortlisted/postponed/rejected/promoted"
    )
    premium_note = Column(
        Text, nullable=True,
        comment="프리미엄 후보에 대한 운영자 판단 메모"
    )
    premium_updated_at = Column(
        DateTime, nullable=True,
        comment="프리미엄 상태 마지막 변경 시간"
    )
    target_reader_type = Column(
        String(100), nullable=True,
        comment="대상 독자 유형 (예: expat_workers, foreign_investors, korea_watchers)"
    )

    # ── CTA 카피 연결 ────────────────────────────────────────────────────────
    cta_copy_id = Column(
        Integer, nullable=True,
        comment="연결된 CTA 카피 블록 ID (cta_copies.id 참조, FK 없음)"
    )

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


class CtaCopy(Base):
    """
    재사용 가능한 CTA / 랜딩 카피 블록 테이블.
    뉴스레터 가입, 리드자석, 프리미엄 티저 등에 쓰이는 짧은 카피를 관리합니다.
    """
    __tablename__ = "cta_copies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cta_type = Column(
        String(50), nullable=False,
        comment="CTA 유형: newsletter_signup/lead_magnet/premium_teaser/premium_waitlist/b2b_inquiry"
    )
    copy_text = Column(
        Text, nullable=False,
        comment="CTA 카피 본문 (짧은 재사용 블록)"
    )
    note = Column(
        Text, nullable=True,
        comment="운영자 메모 (용도, 컨텍스트 등)"
    )
    is_active = Column(
        Boolean, default=True, nullable=False,
        comment="활성 여부 (True=사용중, False=비활성)"
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="생성 시간"
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), comment="수정 시간"
    )

    def __repr__(self):
        return f"<CtaCopy(id={self.id}, type={self.cta_type}, active={self.is_active})>"


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
