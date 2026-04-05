"""
Pipeline 1: 최적 게시 시간 알림 스케줄러
==========================================
사전에 큐에 넣어둔 게시물을 최적 시간에 운영자에게 알림 → 승인 후 발행합니다.
X Analytics 기반 최적 시간: 화~목 오전 9시~오후 3시 KST.

흐름:
  1. /queue <본문> 명령으로 게시물 큐 등록
  2. 스케줄러가 최적 시간 슬롯에 Telegram 승인 카드 발송
  3. 운영자가 "지금 게시" 버튼 탭 → X API 발행
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
    notified_at: datetime | None = None  # 승인 알림 발송 시각 (중복 방지)
    is_thread_starter: bool = False     # 스레드 첫 게시물 여부
    hashtags: list[str] = field(default_factory=list)  # 최대 2개

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "added_at": self.added_at.isoformat(),
            "post_id": self.post_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "is_thread_starter": self.is_thread_starter,
            "hashtags": self.hashtags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueuedPost":
        p = cls(text=d["text"])
        p.added_at = datetime.fromisoformat(d["added_at"])
        p.post_id = d.get("post_id")
        p.published_at = datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None
        p.notified_at = datetime.fromisoformat(d["notified_at"]) if d.get("notified_at") else None
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

    def remove_pending(self, position: int) -> QueuedPost | None:
        """
        운영자 visible position(1-indexed, list_pending() 기준)으로 대기 게시물 제거.
        /queue remove <n> 에서 n이 여기서의 position.
        발행 완료된 게시물은 카운트하지 않음.
        """
        pending = self.list_pending()
        if not pending or not (1 <= position <= len(pending)):
            return None
        post = pending[position - 1]
        self._queue.remove(post)
        self._save()
        return post

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
        최적 시간 슬롯이고 간격 조건 충족 시 첫 대기 게시물에 승인 알림 발송.
        직접 X API 게시 안 함 — 운영자 승인(Telegram 버튼 탭) 후에만 발행.
        이미 알림을 보낸 게시물은 중복 발송하지 않음.
        """
        if not self._is_optimal_slot_now():
            return None
        if not self._can_publish_now():
            return None

        pending = self.list_pending()
        if not pending:
            return None

        post = pending[0]

        # 이미 승인 알림을 보낸 경우 중복 방지
        if post.notified_at is not None:
            return None

        try:
            await self._send_approval_notification(post)
            post.notified_at = datetime.now(timezone.utc)
            self._save()
            logger.info(f"✓ 게시 승인 요청 전송: {post.text[:40]}...")
            return post
        except Exception as e:
            logger.error(f"게시 승인 알림 전송 실패: {e}")

        return None

    async def _send_approval_notification(self, post: "QueuedPost") -> None:
        """Telegram에 승인 요청 카드 전송 (인라인 버튼 포함)."""
        from app.services.growth._tg_helper import tg_send_with_keyboard

        # post_key = added_at ISO string — 콜백 핸들러에서 게시물 식별에 사용
        post_key = post.added_at.isoformat()
        preview = post.text[:300]
        text = (
            "🕐 <b>게시 슬롯 — 승인 요청</b>\n\n"
            f"<code>{preview}</code>"
        )
        keyboard = [[{"text": "✅ 지금 게시", "callback_data": f"queue_approve:{post_key}"}]]
        await tg_send_with_keyboard(text, keyboard)

    async def approve_queued_post(self, post_key: str) -> "QueuedPost | None":
        """
        운영자 승인 콜백: post_key(added_at ISO)로 게시물을 찾아 X API에 발행.
        발행 성공 시 QueuedPost 반환, 없거나 실패 시 None.
        """
        post = next(
            (p for p in self._queue
             if p.added_at.isoformat() == post_key and p.published_at is None),
            None,
        )
        if not post:
            return None

        try:
            result = await self._publish_to_x(post)
            if result:
                post.published_at = datetime.now(timezone.utc)
                post.post_id = result
                self._last_published = post.published_at
                self._save()
                logger.info(f"✓ 승인 후 발행 완료: {post.text[:40]}...")
                return post
        except Exception as e:
            logger.error(f"승인 후 발행 실패: {e}")

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
    """매 5분 실행. 최적 슬롯이면 승인 알림 발송 (자동 발행 없음)."""
    queue = get_post_queue()
    post = await queue.try_publish_next()

    if post:
        logger.info(f"[PostQueue] 승인 요청 전송됨: {post.text[:40]}...")
