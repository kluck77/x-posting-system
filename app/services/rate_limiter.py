"""
일일 사용량 제한 서비스
========================
비용 안전을 위해 하루에 생성/전송/게시할 수 있는 횟수를 제한합니다.

기본 제한값:
- AI 초안 생성: 하루 5회
- 텔레그램 승인 카드: 하루 5회
- X 게시: 하루 3회

레인별 제한 (Lane-based):
- Lane A (BREAKING_NOW): 무제한 — Step 1.7 이전 리턴, AI 파이프라인 미진입
- Lane B (주간 즉시 알림): 무제한 — Step 1.5c에서 처리
- Lane C (Top5 후보 적재): 무제한 — Step 1.5b에서 DB 적재
- Lane D (AI 파이프라인): 제한 적용, 수동/자동 분리
  - 자동수집: max_ai_drafts - manual_reserved 까지
  - 수동입력: max_ai_drafts 전체 사용 가능

이 제한값은 월 $30 예산에 맞춰 설정되었습니다.
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.content import Draft, SourceItem, PostLog, ApprovalStatus

logger = logging.getLogger(__name__)

# 기본 일일 제한값 (기존 호환)
DEFAULT_MAX_DRAFTS_PER_DAY = 5
DEFAULT_MAX_TELEGRAM_PER_DAY = 5
DEFAULT_MAX_POSTS_PER_DAY = 3

# 레인별 AI 파이프라인 제한값
DEFAULT_MAX_AI_DRAFTS_PER_DAY = 20   # AI 파이프라인 총 제한 (Steps 2-6)
DEFAULT_MANUAL_RESERVED = 5           # 수동 입력 보장 슬롯

# KST timezone — 운영자 기준 '오늘' 달력일
KST = timezone(timedelta(hours=9))

# KO-only 드래프트 식별 — 구형 placeholder body 필터.
# orchestrator Step 1.7 조기 리턴 제거(47d2830) 이후 새 Draft 에는
# 이 prefix 가 기록되지 않는다. 기존 DB 레코드 호환을 위해 상수만 유지.
KO_ONLY_BODY_PREFIX = "KO-only pipeline (English draft skipped)"


class RateLimiter:
    """일일 사용량 제한 관리자"""

    def __init__(
        self,
        db: Session,
        max_drafts: int = DEFAULT_MAX_DRAFTS_PER_DAY,
        max_telegram: int = DEFAULT_MAX_TELEGRAM_PER_DAY,
        max_posts: int = DEFAULT_MAX_POSTS_PER_DAY,
        max_ai_drafts: int = DEFAULT_MAX_AI_DRAFTS_PER_DAY,
        manual_reserved: int = DEFAULT_MANUAL_RESERVED,
    ):
        self.db = db
        self.max_drafts = max_drafts
        self.max_telegram = max_telegram
        self.max_posts = max_posts
        self.max_ai_drafts = max_ai_drafts
        self.manual_reserved = manual_reserved

    def _today_start(self) -> datetime:
        """
        '오늘'(KST 달력 기준) 00:00 시각을 naive UTC datetime 으로 반환.

        의도:
        - 운영자는 한국에 있으므로 '오늘' = KST 달력일이다.
          UTC 기준으로 하면 KST 자정~09:00 사이 드래프트가 전부 '어제'
          카운트로 빠져 rate limit 판정이 어긋난다.
        - 반환값은 naive datetime 이다. Draft.created_at 이
          Column(DateTime) (naive) 이고 SQLAlchemy 가 저장 시 aware→naive
          UTC 로 변환해 저장하므로, WHERE 비교도 같은 naive UTC 기준이어야
          aware/naive 혼합으로 인한 경고·예기치 않은 lex 비교 결과를 피할 수 있다.
        """
        now_kst = datetime.now(KST)
        kst_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        return kst_midnight.astimezone(timezone.utc).replace(tzinfo=None)

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

    # ------------------------------------------------------------------
    # Lane-based AI pipeline rate limiting
    # ------------------------------------------------------------------

    def get_today_ai_draft_count(self, source_type: str | None = None) -> int:
        """
        AI 파이프라인을 거친 초안만 카운트합니다 (KO-only 제외).

        KO-only 드래프트(Step 1.7 early return)는 AI API 호출이 없으므로
        비용 기반 제한에서 제외합니다.

        Args:
            source_type: 특정 source_type 만 카운트. None 이면 전체.
        """
        start = self._today_start()
        query = (
            self.db.query(Draft)
            .filter(Draft.created_at >= start)
            .filter(~Draft.body.like(f"{KO_ONLY_BODY_PREFIX}%"))
        )
        if source_type is not None:
            query = query.join(SourceItem).filter(
                SourceItem.source_type == source_type
            )
        return query.count()

    def get_today_auto_ai_draft_count(self) -> int:
        """자동수집(non-manual) AI 드래프트만 카운트합니다."""
        start = self._today_start()
        return (
            self.db.query(Draft)
            .join(SourceItem)
            .filter(Draft.created_at >= start)
            .filter(~Draft.body.like(f"{KO_ONLY_BODY_PREFIX}%"))
            .filter(SourceItem.source_type != "manual")
            .count()
        )

    def can_run_ai_pipeline(
        self, source_type: str = "manual"
    ) -> tuple[bool, str]:
        """
        AI 파이프라인(Steps 2-6) 진입 가능 여부를 확인합니다.

        BREAKING_NOW / KO-only / Top5 적재 / 주간 즉시 알림은
        Step 1.7 이전에 리턴하므로 이 체크를 거치지 않습니다.

        Args:
            source_type: "manual" 이면 전체 한도 사용, 그 외(naver_auto 등)는
                         자동수집 한도(max_ai_drafts - manual_reserved) 적용.

        Returns:
            (허용 여부, 사유) 튜플
        """
        total_ai = self.get_today_ai_draft_count()

        # 자동수집: 수동 보장 슬롯을 제외한 한도 적용
        if source_type != "manual":
            auto_limit = max(self.max_ai_drafts - self.manual_reserved, 0)
            auto_count = self.get_today_auto_ai_draft_count()
            if auto_count >= auto_limit:
                msg = (
                    f"자동수집 AI 파이프라인 한도 초과: {auto_count}/{auto_limit}. "
                    f"수동 입력 {self.manual_reserved}슬롯 예약됨."
                )
                logger.warning(msg)
                return False, msg

        # 전체 AI 파이프라인 한도
        if total_ai >= self.max_ai_drafts:
            msg = (
                f"일일 AI 파이프라인 한도 초과: {total_ai}/{self.max_ai_drafts}. "
                f"내일 다시 시도하세요."
            )
            logger.warning(msg)
            return False, msg

        remaining = self.max_ai_drafts - total_ai
        logger.info(
            f"AI 파이프라인 가능: 오늘 {total_ai}/{self.max_ai_drafts} "
            f"(남은 횟수: {remaining})"
        )
        return True, f"오늘 남은 AI 초안: {remaining}/{self.max_ai_drafts}"

    def get_daily_summary(self) -> dict:
        """오늘의 사용량 요약을 반환합니다."""
        return {
            "drafts": {
                "used": self.get_today_draft_count(),
                "limit": self.max_drafts,
            },
            "ai_pipeline": {
                "used": self.get_today_ai_draft_count(),
                "limit": self.max_ai_drafts,
                "auto_used": self.get_today_auto_ai_draft_count(),
                "auto_limit": max(self.max_ai_drafts - self.manual_reserved, 0),
                "manual_reserved": self.manual_reserved,
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
