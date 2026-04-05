"""
Pipeline 3: 내 게시물 답글 모니터 + 자동 재답글 초안
=====================================================
내 게시물에 달린 답글을 30분 이내 탐지하고 재답글 초안 생성.

알고리즘 근거:
  작성자가 답글에 재답글 = +75점 (좋아요의 150배)
  → 게시 후 60분 이내 모든 답글에 응답하는 것이 단일 최고 레버리지

흐름:
  1. X API로 내 최근 게시물 답글 폴링
  2. 미처리 답글 탐지
  3. Claude로 재답글 초안 생성
  4. Telegram으로 승인 요청
  5. 승인 후 자동 게시
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

X_MENTIONS_URL = "https://api.x.com/2/users/{user_id}/mentions"
X_TWEET_URL = "https://api.x.com/2/tweets"

# 내 계정 ID (X에서 확인 필요)
MY_USERNAME = "sskorea02"


@dataclass
class IncomingReply:
    """내 게시물에 달린 답글."""
    reply_id: str
    reply_text: str
    author_username: str
    author_followers: int
    parent_tweet_id: str    # 내 원래 게시물 ID
    parent_tweet_text: str
    created_at: datetime
    is_processed: bool = False
    my_reply_draft: str = ""
    my_reply_id: str | None = None  # 재답글 후 채워짐

    def format_for_telegram(self) -> str:
        age = int((datetime.now(timezone.utc) - self.created_at).total_seconds() / 60)
        return (
            f"💬 *새 답글 발견!* ({age}분 전)\n\n"
            f"👤 @{self.author_username} ({self.author_followers:,} 팔로워)\n\n"
            f"📄 내 원문:\n`{self.parent_tweet_text[:100]}`\n\n"
            f"📩 답글:\n`{self.reply_text}`\n\n"
            f"✍️ 재답글 초안:\n`{self.my_reply_draft}`\n\n"
            f"🔗 https://x.com/{self.author_username}/status/{self.reply_id}"
        )


class ReplyMonitor:
    """
    내 게시물 답글 모니터.
    폴링 방식 (X API Webhooks는 Enterprise 전용이므로).
    """

    PROCESSED_FILE = "data/processed_replies.json"

    def __init__(self):
        self._my_user_id: str | None = None
        self._processed_ids: set[str] = self._load_processed()
        self._mock_mode = not bool(settings.x_bearer_token)

    def _load_processed(self) -> set[str]:
        try:
            import os
            os.makedirs("data", exist_ok=True)
            with open(self.PROCESSED_FILE, "r") as f:
                return set(json.load(f))
        except FileNotFoundError:
            return set()
        except Exception:
            return set()

    def _save_processed(self):
        try:
            with open(self.PROCESSED_FILE, "w") as f:
                json.dump(list(self._processed_ids), f)
        except Exception as e:
            logger.warning(f"처리 목록 저장 실패: {e}")

    async def _get_my_user_id(self) -> str | None:
        """내 계정 user_id 조회 (캐시)."""
        if self._my_user_id:
            return self._my_user_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.x.com/2/users/by/username/{MY_USERNAME}",
                    headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
                )
                r.raise_for_status()
                self._my_user_id = r.json()["data"]["id"]
                return self._my_user_id
        except Exception as e:
            logger.warning(f"user_id 조회 실패: {e}")
            return None

    async def poll_new_replies(self) -> list[IncomingReply]:
        """30분 이내 미처리 답글 탐지."""
        if self._mock_mode:
            return self._mock_replies()

        user_id = await self._get_my_user_id()
        if not user_id:
            return []

        since = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        headers = {"Authorization": f"Bearer {settings.x_bearer_token}"}
        params = {
            "start_time": since,
            "max_results": 20,
            "tweet.fields": "public_metrics,created_at,author_id,in_reply_to_user_id,referenced_tweets",
            "user.fields": "public_metrics,username",
            "expansions": "author_id,referenced_tweets.id",
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    X_MENTIONS_URL.format(user_id=user_id),
                    headers=headers, params=params,
                )
                if r.status_code == 429:
                    logger.warning("Reply Monitor: X API rate limit")
                    return []
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.error(f"답글 폴링 실패: {e}")
            return []

        return self._parse_mentions(data)

    def _parse_mentions(self, data: dict) -> list[IncomingReply]:
        """멘션 데이터 파싱."""
        replies = []
        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        ref_tweets = {t["id"]: t for t in data.get("includes", {}).get("tweets", [])}

        for tweet in tweets:
            reply_id = tweet["id"]
            if reply_id in self._processed_ids:
                continue

            # 내 게시물에 대한 답글인지 확인
            refs = tweet.get("referenced_tweets", [])
            parent_id = None
            for ref in refs:
                if ref.get("type") == "replied_to":
                    parent_id = ref["id"]
                    break

            if not parent_id:
                continue

            parent_tweet = ref_tweets.get(parent_id, {})
            parent_text = parent_tweet.get("text", "")

            author_id = tweet.get("author_id", "")
            user = users.get(author_id, {})
            username = user.get("username", "unknown")
            followers = user.get("public_metrics", {}).get("followers_count", 0)

            created_at = datetime.fromisoformat(
                tweet.get("created_at", "").replace("Z", "+00:00")
            )

            reply = IncomingReply(
                reply_id=reply_id,
                reply_text=tweet.get("text", ""),
                author_username=username,
                author_followers=followers,
                parent_tweet_id=parent_id,
                parent_tweet_text=parent_text,
                created_at=created_at,
            )
            replies.append(reply)

        return replies

    def mark_processed(self, reply_id: str):
        """답글을 처리 완료로 표시."""
        self._processed_ids.add(reply_id)
        self._save_processed()

    async def post_reply(self, reply_id: str, text: str) -> str | None:
        """재답글 게시. tweet_id 반환."""
        if self._mock_mode:
            logger.info(f"[Mock] 재답글: {text[:60]}")
            return f"mock_reply_{int(datetime.now(timezone.utc).timestamp())}"

        from requests_oauthlib import OAuth1
        auth = OAuth1(
            client_key=settings.x_api_key,
            client_secret=settings.x_api_secret,
            resource_owner_key=settings.x_access_token,
            resource_owner_secret=settings.x_access_token_secret,
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    X_TWEET_URL,
                    auth=auth,
                    json={"text": text, "reply": {"in_reply_to_tweet_id": reply_id}},
                )
                if r.status_code == 429:
                    logger.warning("[ReplyMonitor] post_reply X API rate limit (429) — 스킵")
                    return None
                r.raise_for_status()
                return r.json().get("data", {}).get("id")
        except Exception as e:
            logger.error(f"[ReplyMonitor] post_reply 실패: {e}")
            return None

    def _mock_replies(self) -> list[IncomingReply]:
        return [
            IncomingReply(
                reply_id="mock_reply_001",
                reply_text="저도 Gate.io 봇 돌리는데 청산 당한 경험 있어요ㅠ 어떻게 리스크 관리 하세요?",
                author_username="trader_kr_99",
                author_followers=1200,
                parent_tweet_id="mock_parent_001",
                parent_tweet_text="봇이 하루에 얼마나 잃을 수 있는지 실제 경험을 공유합니다.",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            )
        ]


async def generate_rereply_draft(reply: IncomingReply) -> str:
    """Claude로 재답글 초안 생성."""
    if not settings.has_anthropic:
        return f"@{reply.author_username} 좋은 질문이에요! 제 경험상 {reply.reply_text[:30]}... 에 대해서는 포지션 크기 제한이 핵심이었습니다. 더 자세히 공유해드릴게요."

    try:
        prompt = f"""너는 X 계정 @sskorea02야. Gate.io 선물 자동매매 봇 1인 운영자.

내 원문: "{reply.parent_tweet_text[:150]}"
상대방 답글 (@{reply.author_username}): "{reply.reply_text}"

조건:
- 진짜 경험에서 나온 답변처럼 자연스럽게
- 120자 이내 한국어
- 상대방 답글 내용에 직접 응답
- 대화를 이어갈 수 있는 열린 질문 하나 포함 (알고리즘 +75 효과)
- @멘션 없음, 링크 없음

재답글만 출력:"""

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 180,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"재답글 초안 생성 실패: {e}")
        return f"맞아요, 저도 같은 경험을 했습니다. 구체적으로 어떤 상황이었나요? 제 해결책을 공유해드릴게요."


async def run_reply_monitor():
    """
    매 5분 실행.
    새 답글 발견 시 Claude 초안 생성 → Telegram 승인 요청.
    """
    from app.services.growth._tg_helper import tg_send

    monitor = ReplyMonitor()
    new_replies = await monitor.poll_new_replies()

    for reply in new_replies:
        try:
            draft = await generate_rereply_draft(reply)
            reply.my_reply_draft = draft
            msg = reply.format_for_telegram()
            await tg_send(msg)
            monitor.mark_processed(reply.reply_id)
        except Exception as e:
            logger.error(f"답글 처리 실패 {reply.reply_id}: {e}")
