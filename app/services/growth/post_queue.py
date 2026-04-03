"""
Pipeline 1: 최적 게시 시간 자동 스케줄러
==========================================
사전에 큐에 넣어둔 게시물을 최적 시간에 자동 발행합니다.
X Analytics 기반 최적 시간: 화~목 오전 9시~오후 3시 KST.

흐름:
  1. /queue <본문> 명령으로 게시물 큐 등록
  2. 스케줄러가 최적 시간 슬롯에 자동 발행
  3. Telegram으로 "발행됨 + 본문" 알림 발송
  4. 연속 게시 방지: 최소 30분 간격 enforced
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# KST = UTC+9
KST_OFFSET = 9

# 최적 게시 슬롯 (KST 시간, 분)
OPTIMAL_SLOTS_KST = [
    (9, 0),   # 오전 9시
    (10, 30), # 오전 10시 30분
    (12, 0),  # 낮 12시
    (13, 30), # 오후 1시 30분
    (15, 0),  # 오후 3시
    (19, 0),  # 저녁 7시 (보조)
    (21, 0),  # 밤 9시 (보조)
]

# 연속 게시 최소 간격 (분)
MIN_INTERVAL_MINUTES = 30


@dataclass
class QueuedPost:
    """큐에 등록된 게시물."""
    text: str
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    post_id: str | None = None          # 발행 후 X tweet ID
    published_at: datetime | None = None
    is_thread_starter: bool = False     # 스레드 첫 게시물 여부
    hashtags: list[str] = field(default_factory=list)  # 최대 2개

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "added_at": self.added_at.isoformat(),
            "post_id": self.post_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "is_thread_starter": self.is_thread_starter,
            "hashtags": self.hashtags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueuedPost":
        p = cls(text=d["text"])
        p.added_at = datetime.fromisoformat(d["added_at"])
        p.post_id = d.get("post_id")
        p.published_at = datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None
        p.is_thread_starter = d.get("is_thread_starter", False)
        p.hashtags = d.get("hashtags", [])
        return p


class PostQueue:
    """
    게시물 큐 관리자.
    인메모리 + JSON 파일 영속화.
    """

    QUEUE_FILE = "data/post_queue.json"

    def __init__(self):
        self._queue: list[QueuedPost] = []
        self._last_published: datetime | None = None
        self._load()

    def _load(self):
        """JSON 파일에서 큐 로드."""
        try:
            import os
            os.makedirs("data", exist_ok=True)
            with open(self.QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._queue = [QueuedPost.from_dict(d) for d in data.get("queue", [])]
                last = data.get("last_published")
                self._last_published = datetime.fromisoformat(last) if last else None
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"큐 파일 로드 실패: {e}")

    def _save(self):
        """큐를 JSON 파일에 저장."""
        try:
            import os
            os.makedirs("data", exist_ok=True)
            with open(self.QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "queue": [p.to_dict() for p in self._queue],
                    "last_published": self._last_published.isoformat() if self._last_published else None,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"큐 파일 저장 실패: {e}")

    def add(self, text: str, hashtags: list[str] | None = None) -> QueuedPost:
        """게시물을 큐에 추가. 해시태그 최대 2개 enforced."""
        tags = (hashtags or [])[:2]
        post = QueuedPost(text=text, hashtags=tags)
        self._queue.append(post)
        self._save()
        logger.info(f"큐 추가: {text[:40]}... (총 {len(self._queue)}개)")
        return post

    def remove(self, index: int) -> QueuedPost | None:
        """인덱스로 게시물 제거."""
        if 0 <= index < len(self._queue):
            post = self._queue.pop(index)
            self._save()
            return post
        return None

    def list_pending(self) -> list[QueuedPost]:
        """미발행 게시물 목록."""
        return [p for p in self._queue if p.published_at is None]

    def list_all(self) -> list[QueuedPost]:
        return self._queue.copy()

    def count_pending(self) -> int:
        return len(self.list_pending())

    def _is_optimal_slot_now(self) -> bool:
        """지금이 최적 게시 슬롯인지 확인 (±15분 허용)."""
        now_kst = datetime.now(timezone.utc) + timedelta(hours=KST_OFFSET)
        for h, m in OPTIMAL_SLOTS_KST:
            slot = now_kst.replace(hour=h, minute=m, second=0, microsecond=0)
            diff = abs((now_kst - slot).total_seconds())
            if diff <= 15 * 60:  # ±15분
                return True
        return False

    def _can_publish_now(self) -> bool:
        """연속 게시 방지: 마지막 게시로부터 MIN_INTERVAL_MINUTES 경과 확인."""
        if self._last_published is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_published).total_seconds() / 60
        return elapsed >= MIN_INTERVAL_MINUTES

    async def try_publish_next(self) -> QueuedPost | None:
        """
        최적 시간 슬롯이고 간격 조건 충족 시 다음 게시물 발행.
        실제 X API 게시는 x_publisher 에서 담당.
        """
        if not self._is_optimal_slot_now():
            return None
        if not self._can_publish_now():
            return None

        pending = self.list_pending()
        if not pending:
            return None

        post = pending[0]

        # X API 게시
        try:
            result = await self._publish_to_x(post)
            if result:
                post.published_at = datetime.now(timezone.utc)
                post.post_id = result
                self._last_published = post.published_at
                self._save()
                logger.info(f"✓ 자동 발행 완료: {post.text[:40]}...")
                return post
        except Exception as e:
            logger.error(f"자동 발행 실패: {e}")

        return None

    async def _publish_to_x(self, post: QueuedPost) -> str | None:
        """X API v2로 트윗 발행. 성공 시 tweet_id 반환."""
        from app.config import settings
        if not settings.has_x_credentials:
            logger.info(f"[Mock] 발행: {post.text[:60]}")
            return f"mock_{int(datetime.now(timezone.utc).timestamp())}"

        from requests_oauthlib import OAuth1
        import httpx

        text = post.text
        # 해시태그 본문 뒤에 추가 (최대 2개)
        if post.hashtags:
            text += " " + " ".join(f"#{t.lstrip('#')}" for t in post.hashtags)

        auth = OAuth1(
            client_key=settings.x_api_key,
            client_secret=settings.x_api_secret,
            resource_owner_key=settings.x_access_token,
            resource_owner_secret=settings.x_access_token_secret,
        )
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.x.com/2/tweets",
                auth=auth,
                json={"text": text},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("data", {}).get("id")


# 싱글턴
_queue_instance: PostQueue | None = None


def get_post_queue() -> PostQueue:
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = PostQueue()
    return _queue_instance


async def run_queue_scheduler():
    """매 5분 실행. 최적 슬롯이면 큐에서 발행."""
    from app.config import settings
    from app.services.telegram_service import send_telegram_message

    queue = get_post_queue()
    post = await queue.try_publish_next()

    if post:
        # Telegram 알림
        msg = (
            "✅ *게시물 자동 발행됨*\n\n"
            f"`{post.text[:200]}`\n\n"
            f"🔗 https://x.com/sskorea02/status/{post.post_id}\n"
            f"📋 큐 잔여: {queue.count_pending()}개"
        )
        try:
            await send_telegram_message(msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Telegram 알림 실패: {e}")
