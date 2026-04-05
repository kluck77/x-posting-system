"""
콘텐츠 요청 모델
================
다양한 입력 유형을 하나의 내부 표현으로 정규화합니다.

지원 입력:
  news_link      — 뉴스 기사 URL
  x_post         — X 포스트 링크
  screenshot_ref — 스크린샷 경로 또는 설명
  observation    — 개인 관찰 / 일상 메모
  account_example — 계정 예시 (레퍼런스)
  raw_text       — 원문 붙여넣기
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


SOURCE_TYPE_MAP: dict[str, str] = {
    "news_link":      "manual",
    "x_post":         "manual",
    "screenshot_ref": "manual",
    "observation":    "community_input",
    "account_example":"manual",
    "raw_text":       "manual",
}


class ContentRequest(BaseModel):
    """유연한 다중 입력 파서 — 모든 입력을 하나의 요청 객체로 정규화."""

    # 소스
    source_url: Optional[str] = Field(None, description="뉴스/X 링크")
    source_type: Literal[
        "news_link", "x_post", "screenshot_ref",
        "observation", "account_example", "raw_text",
    ] = Field("news_link", description="소스 유형")

    # 콘텐츠
    raw_text: Optional[str] = Field(None, description="원문 붙여넣기")
    note: Optional[str] = Field(None, description="사용자 메모 / 각도 힌트 (최대 500자)")

    @field_validator("note")
    @classmethod
    def note_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("note는 500자를 초과할 수 없습니다")
        return v
    image_path: Optional[str] = Field(None, description="스크린샷 경로 또는 설명 (Phase 1 — 텍스트로만 처리)")
    image_extracted_text: Optional[str] = Field(None, description="스크린샷 OCR 텍스트 (있으면 직접 사용)")

    # 프레이밍 힌트
    target_framing: Optional[str] = Field(None, description="국제 독자 관련성 힌트")

    language: str = Field("english", description="출력 언어")

    # ── 정규화 메서드 ──────────────────────────────────────────────────────────

    def to_source_text(self) -> str:
        """모든 입력을 하나의 텍스트 블록으로 정규화."""
        parts: list[str] = []

        if self.raw_text:
            parts.append(self.raw_text)

        if self.image_extracted_text:
            parts.append(f"[Screenshot text]: {self.image_extracted_text}")
        elif self.image_path:
            parts.append(f"[Image reference]: {self.image_path}")

        if self.note:
            parts.append(f"[User note]: {self.note}")

        if self.target_framing:
            parts.append(f"[International framing hint]: {self.target_framing}")

        return "\n\n".join(parts) if parts else ""

    def to_title(self) -> str:
        """사람이 읽기 좋은 요약 제목 생성."""
        if self.note:
            return self.note[:120]
        if self.raw_text:
            return self.raw_text[:120]
        if self.source_url:
            return self.source_url[:120]
        return f"Content request ({self.source_type})"

    def to_source_item_create(self):
        """기존 파이프라인 호환 — SourceItemCreate로 변환."""
        from app.models.content import SourceItemCreate

        return SourceItemCreate(
            title=self.to_title(),
            url=self.source_url or "",
            source_text=self.to_source_text() or self.to_title(),
            source_type=SOURCE_TYPE_MAP.get(self.source_type, "manual"),
            language=self.language,
        )

    def has_content(self) -> bool:
        """최소한 하나의 입력 필드가 채워져 있는지 확인."""
        return bool(
            self.source_url or self.raw_text or
            self.image_extracted_text or self.image_path or self.note
        )
