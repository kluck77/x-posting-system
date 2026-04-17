"""
소스 수집 서비스
================
콘텐츠 소스(뉴스, 수동 입력 등)를 수집하고 정규화하여 데이터베이스에 저장합니다.
현재는 수동 입력만 지원하며, 추후 RSS/API 커넥터를 추가할 수 있습니다.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.models.content import SourceItem, SourceItemCreate, Draft

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

    def mark_candidate_discarded(self, source_id: int) -> str:
        """
        Hold 카드 discard 처리.
        source_items.candidate_status 를 'rejected_manual' 로 변경합니다.

        주의:
            서버 측 source_items 테이블에는 candidate_status 컬럼이 존재하지만,
            로컬 ORM 모델(SourceItem)에는 정의되어 있지 않다 (서버 직접 추가).
            모델 변경 시 마이그레이션/init_db ripple 위험이 있어 본 세션에서는
            ORM attribute가 아닌 raw SQL UPDATE 1문장으로만 처리한다.

        Args:
            source_id: source_items.id

        Returns:
            "ok"           1행 갱신 성공
            "not_found"    해당 source_id 없음 (또는 이미 같은 상태)
            "schema_error" candidate_status 컬럼 부재 (로컬 또는 미배포 환경)
            "db_error"     그 외 DB 오류
        """
        try:
            result = self.db.execute(
                text(
                    "UPDATE source_items "
                    "SET candidate_status = :v "
                    "WHERE id = :id"
                ),
                {"v": "rejected_manual", "id": int(source_id)},
            )
            if result.rowcount == 0:
                self.db.rollback()
                logger.warning(
                    f"discard 대상 없음: source_id={source_id} "
                    f"(rowcount=0)"
                )
                return "not_found"
            self.db.commit()
            logger.info(
                f"candidate_status=rejected_manual: source_id={source_id}"
            )
            return "ok"
        except OperationalError as e:
            self.db.rollback()
            msg = str(e).lower()
            if "no such column" in msg or "candidate_status" in msg:
                logger.error(
                    f"candidate_status 컬럼 없음 (스키마 미적용): {e}"
                )
                return "schema_error"
            logger.error(f"discard DB 오류: {e}")
            return "db_error"
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"discard DB 오류: {e}")
            return "db_error"

    def get_for_promote(
        self, source_id: int
    ) -> tuple[SourceItem | None, str]:
        """
        Hold 카드 promote 사전 검증.

        반환:
            (SourceItem | None, tag)
            tag ∈ {"ok", "not_found", "discarded", "already_promoted"}

        판정 규칙:
          - not_found:        source_items.id 존재하지 않음
          - discarded:        candidate_status == 'rejected_manual'
                              (컬럼 부재 로컬 환경에서는 이 판정 자체를 건너뜀)
          - already_promoted: 동일 source_item_id 를 가진 Draft 가 이미 존재
          - ok:               위 3가지에 해당하지 않음

        주의:
            candidate_status 컬럼은 서버 직접 추가 컬럼이라 로컬 ORM 모델/
            init_db 에는 정의되어 있지 않다. 존재하지 않는 환경에서도 본 함수가
            안전 축퇴(fallback) 되도록, raw SQL SELECT 시 OperationalError(
            "no such column") 는 무시하고 나머지 경로로 진행한다.
        """
        src = (
            self.db.query(SourceItem)
            .filter(SourceItem.id == int(source_id))
            .first()
        )
        if src is None:
            return None, "not_found"

        # candidate_status 검사 (스키마 drift 관대)
        try:
            row = self.db.execute(
                text(
                    "SELECT candidate_status FROM source_items "
                    "WHERE id = :id"
                ),
                {"id": int(source_id)},
            ).fetchone()
            if row is not None and row[0] == "rejected_manual":
                return src, "discarded"
        except OperationalError as e:
            msg = str(e).lower()
            if "no such column" in msg or "candidate_status" in msg:
                logger.info(
                    "candidate_status 컬럼 없음 — promote 사전검사에서 "
                    "discarded 판정을 건너뜁니다 (로컬 폴백)."
                )
            else:
                logger.warning(
                    f"candidate_status 조회 DB 오류 (무시): {e}"
                )
        except SQLAlchemyError as e:
            logger.warning(f"candidate_status 조회 실패 (무시): {e}")

        # already_promoted: 동일 source_item_id 의 Draft 존재 여부
        existing = (
            self.db.query(Draft)
            .filter(Draft.source_item_id == int(source_id))
            .first()
        )
        if existing is not None:
            return src, "already_promoted"

        return src, "ok"
