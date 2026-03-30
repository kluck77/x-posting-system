"""
소스 수집 서비스
================
콘텐츠 소스(뉴스, 수동 입력 등)를 수집하고 정규화하여 데이터베이스에 저장합니다.
현재는 수동 입력만 지원하며, 추후 RSS/API 커넥터를 추가할 수 있습니다.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import SourceItem, SourceItemCreate

logger = logging.getLogger(__name__)


class SourceService:
    """소스 항목 수집 및 관리 서비스"""

    def __init__(self, db: Session):
        self.db = db

    def is_duplicate_url(self, url: str) -> bool:
        """
        동일한 URL이 이미 등록되어 있는지 확인합니다.
        중복 소스 입력을 방지합니다.

        Args:
            url: 확인할 URL

        Returns:
            True = 이미 존재함, False = 새로운 URL
        """
        if not url or not url.strip():
            return False
        existing = (
            self.db.query(SourceItem)
            .filter(SourceItem.url == url.strip())
            .first()
        )
        if existing:
            logger.warning(f"중복 URL 감지: {url} (기존 source_id={existing.id})")
            return True
        return False

    def ingest_manual(self, data: SourceItemCreate) -> SourceItem:
        """
        수동으로 소스 항목을 입력합니다.

        Args:
            data: 소스 항목 데이터 (제목, URL, 텍스트 등)

        Returns:
            저장된 SourceItem 객체

        Raises:
            ValueError: 동일한 URL이 이미 등록된 경우
        """
        logger.info(f"소스 수집 시작: '{data.title[:50]}...'")

        # URL 중복 체크
        if data.url and self.is_duplicate_url(data.url):
            raise ValueError(f"이미 등록된 URL입니다: {data.url}")

        # 데이터베이스에 저장할 객체 생성
        source_item = SourceItem(
            title=data.title.strip(),
            url=data.url.strip() if data.url else None,
            source_text=data.source_text.strip(),
            source_type=data.source_type,
            language=data.language,
            created_at=datetime.now(timezone.utc),
        )

        self.db.add(source_item)
        self.db.commit()
        self.db.refresh(source_item)

        logger.info(f"소스 수집 완료: id={source_item.id}, title='{source_item.title[:50]}'")
        return source_item

    def get_by_id(self, source_id: int) -> SourceItem | None:
        """ID로 소스 항목을 조회합니다."""
        return self.db.query(SourceItem).filter(SourceItem.id == source_id).first()

    def get_all(self, limit: int = 50) -> list[SourceItem]:
        """모든 소스 항목을 최신순으로 조회합니다."""
        return (
            self.db.query(SourceItem)
            .order_by(SourceItem.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_unprocessed(self) -> list[SourceItem]:
        """아직 초안이 생성되지 않은 소스 항목을 조회합니다."""
        return (
            self.db.query(SourceItem)
            .filter(~SourceItem.drafts.any())
            .order_by(SourceItem.created_at.asc())
            .all()
        )
