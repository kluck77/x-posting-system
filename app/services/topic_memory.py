"""
토픽 메모리 (Topic Memory)
===========================
기존 drafts.topic_tags 컬럼에서 태그 빈도를 집계합니다.
새 DB 테이블 없음 — 기존 컬럼 재사용.

주요 기능:
- 최근 N일 태그 빈도 집계 (Counter)
- 과다 사용 태그 감지
- 콘텐츠 믹스 Telegram 보고용 요약 문자열 생성

설계:
- 순수 SQLite 읽기 (AI 호출 없음)
- 예외 발생 안 함 — Layer 2 보호
- 빈 DB에서도 정상 동작
"""

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TopicMemory:
    """drafts.topic_tags 기반 경량 토픽 메모리."""

    def __init__(self, db: Session):
        self.db = db

    def get_recent_tags(self, days: int = 30) -> Counter:
        """
        최근 N일 승인/게시된 초안의 태그 빈도 집계.

        Returns:
            Counter({'economy': 8, 'BOK': 5, ...}) — 빈 DB면 Counter()
        """
        try:
            from app.models.content import Draft, ApprovalStatus
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows = (
                self.db.query(Draft.topic_tags)
                .filter(
                    Draft.approval_status.in_([
                        ApprovalStatus.APPROVED,
                        ApprovalStatus.PUBLISHED,
                    ]),
                    Draft.created_at >= cutoff,
                    Draft.topic_tags.isnot(None),
                )
                .all()
            )
            counter: Counter = Counter()
            for (tag_json,) in rows:
                if not tag_json:
                    continue
                try:
                    tags = json.loads(tag_json)
                    if isinstance(tags, list):
                        counter.update(t.strip().lower() for t in tags if t)
                except (json.JSONDecodeError, TypeError):
                    continue
            return counter
        except Exception as e:
            logger.warning(f"[TopicMemory] 태그 집계 실패 (무시): {e}")
            return Counter()

    def get_overused_tags(self, threshold: int = 5, days: int = 30) -> list[str]:
        """
        임계값 초과 태그 목록 (빈도 내림차순).

        Args:
            threshold: 이 횟수 초과 시 과다 사용으로 분류
            days: 검색 기간

        Returns:
            ['economy', 'BOK', ...] — 없으면 빈 리스트
        """
        counter = self.get_recent_tags(days=days)
        return [tag for tag, count in counter.most_common() if count > threshold]

    def format_mix_report(self, days: int = 7) -> str:
        """
        콘텐츠 믹스 요약 문자열 (Telegram 보고용).

        Returns:
            '📌 콘텐츠 믹스 (7일): economy×5, BOK×3, crypto×2'
            태그 없으면 빈 문자열
        """
        counter = self.get_recent_tags(days=days)
        if not counter:
            return ""

        top = counter.most_common(8)
        items = ", ".join(f"{tag}×{count}" for tag, count in top)
        overused = [tag for tag, count in top if count >= 5]

        lines = [f"📌 콘텐츠 믹스 ({days}일): {items}"]
        if overused:
            lines.append(f"  ⚠️ 과다 사용: {', '.join(overused)} — 다양화 권장")

        return "\n".join(lines)
