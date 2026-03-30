"""
일일 사용량 제한 서비스
========================
비용 안전을 위해 하루에 생성/전송/게시할 수 있는 횟수를 제한합니다.

기본 제한값:
- AI 초안 생성: 하루 5회
- 텔레그램 승인 카드: 하루 5회
- X 게시: 하루 3회

이 제한값은 월 $30 예산에 맞춰 설정되었습니다.
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.content import Draft, PostLog, ApprovalStatus

logger = logging.getLogger(__name__)

# 기본 일일 제한값
DEFAULT_MAX_DRAFTS_PER_DAY = 5
DEFAULT_MAX_TELEGRAM_PER_DAY = 5
DEFAULT_MAX_POSTS_PER_DAY = 3


class RateLimiter:
    """일일 사용량 제한 관리자"""

    def __init__(
        self,
        db: Session,
        max_drafts: int = DEFAULT_MAX_DRAFTS_PER_DAY,
        max_telegram: int = DEFAULT_MAX_TELEGRAM_PER_DAY,
        max_posts: int = DEFAULT_MAX_POSTS_PER_DAY,
    ):
        self.db = db
        self.max_drafts = max_drafts
        self.max_telegram = max_telegram
        self.max_posts = max_posts

    def _today_start(self) -> datetime:
        """오늘 00:00 UTC를 반환합니다."""
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_today_draft_count(self) -> int:
        """오늘 생성된 초안 수를 반환합니다."""
        start = self._today_start()
        count = (
            self.db.query(Draft)
            .filter(Draft.created_at >= start)
            .count()
        )
        return count

    def get_today_post_count(self) -> int:
        """오늘 게시된 포스트 수를 반환합니다."""
        start = self._today_start()
        count = (
            self.db.query(Draft)
            .filter(
                Draft.published_at >= start,
                Draft.approval_status == ApprovalStatus.PUBLISHED,
            )
            .count()
        )
        return count

    def get_today_telegram_count(self) -> int:
        """오늘 텔레그램으로 전송된 승인 카드 수를 반환합니다."""
        start = self._today_start()
        count = (
            self.db.query(Draft)
            .filter(
                Draft.created_at >= start,
                Draft.telegram_message_id.isnot(None),
            )
            .count()
        )
        return count

    def can_create_draft(self) -> tuple[bool, str]:
        """
        새 초안을 생성할 수 있는지 확인합니다.

        Returns:
            (허용 여부, 사유) 튜플
        """
        count = self.get_today_draft_count()
        if count >= self.max_drafts:
            msg = (
                f"일일 초안 생성 한도 초과: {count}/{self.max_drafts}. "
                f"내일 다시 시도하세요."
            )
            logger.warning(msg)
            return False, msg
        remaining = self.max_drafts - count
        logger.info(f"초안 생성 가능: 오늘 {count}/{self.max_drafts} (남은 횟수: {remaining})")
        return True, f"오늘 남은 초안: {remaining}/{self.max_drafts}"

    def can_send_telegram(self) -> tuple[bool, str]:
        """
        텔레그램 승인 카드를 보낼 수 있는지 확인합니다.

        Returns:
            (허용 여부, 사유) 튜플
        """
        count = self.get_today_telegram_count()
        if count >= self.max_telegram:
            msg = (
                f"일일 텔레그램 전송 한도 초과: {count}/{self.max_telegram}. "
                f"내일 다시 시도하세요."
            )
            logger.warning(msg)
            return False, msg
        remaining = self.max_telegram - count
        return True, f"오늘 남은 텔레그램: {remaining}/{self.max_telegram}"

    def can_publish(self) -> tuple[bool, str]:
        """
        X에 게시할 수 있는지 확인합니다.

        Returns:
            (허용 여부, 사유) 튜플
        """
        count = self.get_today_post_count()
        if count >= self.max_posts:
            msg = (
                f"일일 게시 한도 초과: {count}/{self.max_posts}. "
                f"내일 다시 시도하세요."
            )
            logger.warning(msg)
            return False, msg
        remaining = self.max_posts - count
        return True, f"오늘 남은 게시: {remaining}/{self.max_posts}"

    def get_daily_summary(self) -> dict:
        """오늘의 사용량 요약을 반환합니다."""
        return {
            "drafts": {
                "used": self.get_today_draft_count(),
                "limit": self.max_drafts,
            },
            "telegram": {
                "used": self.get_today_telegram_count(),
                "limit": self.max_telegram,
            },
            "posts": {
                "used": self.get_today_post_count(),
                "limit": self.max_posts,
            },
        }
