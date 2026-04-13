"""
Pipeline 2: 댓글 달기 좋은 게시물 탐지
=========================================
X API v2 검색으로 30분 이내 크립토/Gate.io/선물 관련 게시물 탐지.

선정 기준:
- 게시 후 30분 이내 (알고리즘 부스트 창)
- 좋아요 10~100개 (너무 크면 묻힘, 너무 작으면 노출 없음)
- Gate.io / 선물 / 자동매매 / AI 트레이딩 키워드 포함
- 논란성/대형 계정 제외

댓글 유형 (CMD-04 기반):
A. 데이터 추가형
B. 반론형 (정중한 다른 관점)
C. 경험 공유형
D. 질문 유발형
E. 인용 확장형
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# X API v2 검색 엔드포인트
X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

# 탐지 키워드 (OR 조건)
HUNT_KEYWORDS = [
    "Gate.io 선물",
    "선물봇",
    "자동매매 봇",
    "AI 트레이딩",
    "선물거래 리스크",
    "크립토 봇",
    "코인 자동매매",
    "비트코인 선물",
    "트레이딩 봇",
    "퀀트 트레이딩",
]

# 좋아요 수 필터
MIN_LIKES = 10
MAX_LIKES = 200

# 팔로워 필터 (너무 크면 댓글이 묻힘)
MAX_AUTHOR_FOLLOWERS = 50_000


@dataclass
class CommentTarget:
    """댓글 달기 좋은 게시물."""
    tweet_id: str
    tweet_url: str
    text: str
    author_username: str
    author_followers: int
    like_count: int
    reply_count: int
    created_at: datetime
    matched_keyword: str
    suggested_reply_type: str   # A/B/C/D/E
    reply_draft: str = ""       # AI 생성 초안

    @property
    def age_minutes(self) -> float:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() / 60

    def format_for_telegram(self) -> str:
        age = int(self.age_minutes)
        return (
            f"🎯 *댓글 기회 발견*\n\n"
            f"⏱ {age}분 전 게시 | ❤️ {self.like_count} | 💬 {self.reply_count}\n"
            f"👤 @{self.author_username} ({self.author_followers:,} 팔로워)\n"
            f"🔑 키워드: {self.matched_keyword}\n\n"
            f"📄 원문:\n`{self.text[:200]}`\n\n"
            f"📝 추천 댓글 유형: {self.suggested_reply_type}\n\n"
            f"💬 초안:\n`{self.reply_draft}`\n\n"
            f"🔗 {self.tweet_url}"
        )


class CommentHunter:
    """X API v2 기반 댓글 타겟 탐지기."""

    def __init__(self):
        self._bearer_token = settings.x_bearer_token
        self._mock_mode = not bool(self._bearer_token)

    async def hunt(self, max_results: int = 10) -> list[CommentTarget]:
        """
        키워드 기반으로 댓글 달기 좋은 게시물 탐지.
        X API 없으면 Mock 데이터 반환.
        """
        if self._mock_mode:
            return self._mock_results()

        targets: list[CommentTarget] = []
        seen_ids: set[str] = set()

        for keyword in HUNT_KEYWORDS[:5]:  # Rate limit 고려, 상위 5개만
            try:
                results = await self._search(keyword)
                for t in results:
                    if t.tweet_id not in seen_ids:
                        seen_ids.add(t.tweet_id)
                        targets.append(t)
            except Exception as e:
                logger.warning(f"키워드 '{keyword}' 검색 실패: {e}")

        # 점수 기반 정렬: 빠른 성장 + 높은 좋아요
        targets.sort(key=lambda t: (t.like_count / max(t.age_minutes, 1)), reverse=True)
        return targets[:max_results]

    async def _search(self, keyword: str) -> list[CommentTarget]:
        """X API v2 검색 실행."""
        # 30분 이내 게시물만
        since = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        query = f"{keyword} lang:ko -is:retweet -is:reply"

        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        params = {
            "query": query,
            "start_time": since,
            "max_results": 10,
            "tweet.fields": "public_metrics,created_at,author_id",
            "user.fields": "public_metrics,username",
            "expansions": "author_id",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(X_SEARCH_URL, headers=headers, params=params)
            if r.status_code == 429:
                logger.warning("X API rate limit 도달")
                return []
            r.raise_for_status()
            data = r.json()

        return self._parse_results(data, keyword)

    def _parse_results(self, data: dict, keyword: str) -> list[CommentTarget]:
        """API 응답 파싱 + 필터링."""
        targets = []
        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        for tweet in tweets:
            metrics = tweet.get("public_metrics", {})
            likes = metrics.get("like_count", 0)
            replies = metrics.get("reply_count", 0)
            author_id = tweet.get("author_id", "")
            user = users.get(author_id, {})
            followers = user.get("public_metrics", {}).get("followers_count", 0)
            username = user.get("username", "unknown")

            # 필터
            if not (MIN_LIKES <= likes <= MAX_LIKES):
                continue
            if followers > MAX_AUTHOR_FOLLOWERS:
                continue

            created_at = datetime.fromisoformat(
                tweet.get("created_at", "").replace("Z", "+00:00")
            )
            tweet_id = tweet["id"]

            target = CommentTarget(
                tweet_id=tweet_id,
                tweet_url=f"https://x.com/{username}/status/{tweet_id}",
                text=tweet.get("text", ""),
                author_username=username,
                author_followers=followers,
                like_count=likes,
                reply_count=replies,
                created_at=created_at,
                matched_keyword=keyword,
                suggested_reply_type=self._suggest_reply_type(tweet.get("text", "")),
            )
            targets.append(target)

        return targets

    def _suggest_reply_type(self, text: str) -> str:
        """게시물 내용 기반 추천 댓글 유형 선택."""
        text_lower = text.lower()
        if "%" in text or any(c.isdigit() for c in text):
            return "A. 데이터 추가형"
        if "?" in text or "어떻게" in text or "왜" in text:
            return "D. 질문 유발형"
        if "실패" in text or "손실" in text or "잃었" in text:
            return "C. 경험 공유형"
        if "최고" in text or "무조건" in text or "항상" in text:
            return "B. 반론형"
        return "E. 인용 확장형"

    def _mock_results(self) -> list[CommentTarget]:
        """X API 없을 때 Mock 데이터."""
        return [
            CommentTarget(
                tweet_id="mock_001",
                tweet_url="https://x.com/mock_user/status/mock_001",
                text="Gate.io 선물 거래로 이번 달 수익률 15% 달성했습니다. 자동매매 봇이 핵심이었어요.",
                author_username="crypto_kr_mock",
                author_followers=3200,
                like_count=47,
                reply_count=8,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=18),
                matched_keyword="Gate.io 선물",
                suggested_reply_type="A. 데이터 추가형",
                reply_draft="저도 비슷한 경험이 있는데요, 수익률 유지를 위해 어떤 리스크 관리 룰을 쓰시나요? 저는 단일 포지션 자산의 2% 초과 금지 룰을 봇에 넣었더니 낙폭이 크게 줄었습니다.",
            ),
            CommentTarget(
                tweet_id="mock_002",
                tweet_url="https://x.com/mock_user2/status/mock_002",
                text="자동매매 봇 항상 수익 낼 수 있다고 믿으시나요? 시장이 답입니다.",
                author_username="quant_kr_mock",
                author_followers=5100,
                like_count=82,
                reply_count=14,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=25),
                matched_keyword="자동매매 봇",
                suggested_reply_type="B. 반론형",
                reply_draft="동의합니다. 봇은 '시스템적으로 규칙을 지키는 것'이 장점이지, 수익 보장이 아니죠. 저는 도쿄 VPS에서 6개월 운영해봤는데 횡보장에서 오히려 수수료 손실이 컸습니다. 어떤 시장 조건에서 가장 힘드셨나요?",
            ),
        ]


async def generate_reply_draft(target: CommentTarget) -> str:
    """
    Claude API로 댓글 초안 생성.
    계정 정체성: Gate.io 선물봇 1인 운영자.
    """
    from app.config import settings

    if not settings.has_anthropic:
        return _fallback_reply_draft(target)

    try:
        import httpx
        prompt = f"""너는 X(트위터) 계정 @sskorea02 야. Gate.io 선물 자동매매 봇을 도쿄 VPS에서 1인 운영 중인 실제 트레이더다.

상대방 게시물:
"{target.text}"

댓글 유형: {target.suggested_reply_type}

조건:
- 실제 봇 운영 경험에서 나온 것처럼 자연스럽게
- 140자 이내 한국어
- 단순 공감 금지 — 데이터/경험/질문 중 하나 반드시 포함
- 링크, 해시태그 없음
- CTA 없음 (댓글이 RT되려면 독립적 가치가 있어야 함)

댓글만 출력:"""

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            resp_data = r.json()
            usage = resp_data.get("usage", {})
            logger.info(
                f"[API-COST] anthropic claude-haiku-4-5 "
                f"in={usage.get('input_tokens', '?')} "
                f"out={usage.get('output_tokens', '?')} "
                f"caller=CommentHunter"
            )
            return resp_data["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"Claude 댓글 초안 생성 실패: {e}")
        return _fallback_reply_draft(target)


def _fallback_reply_draft(target: CommentTarget) -> str:
    """Claude 없을 때 유형별 기본 템플릿."""
    templates = {
        "A. 데이터 추가형": "저도 비슷한 경험이 있는데요, 구체적으로 어떤 조건에서 그 수치가 나왔나요? 제 봇 데이터와 비교해보고 싶습니다.",
        "B. 반론형": "좋은 포인트인데, 반대로 생각하면 어떨까요? 제 운영 경험상 예외가 있었습니다.",
        "C. 경험 공유형": "비슷한 상황을 겪었습니다. 도쿄 VPS 봇 운영 중 같은 문제가 있었는데 이렇게 해결했어요.",
        "D. 질문 유발형": "흥미로운 접근이네요. 혹시 이 방식에서 가장 어려웠던 부분은 뭐였나요?",
        "E. 인용 확장형": "이 관점을 확장하면, 자동매매 봇 맥락에서는 더 중요한 요소가 하나 있습니다.",
    }
    reply_type = target.suggested_reply_type
    for key, template in templates.items():
        if key in reply_type:
            return template
    return templates["E. 인용 확장형"]
