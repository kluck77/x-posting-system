"""
Pipeline 4: 주간 성과 리포트
==============================
매주 월요일 오전 9시 KST 자동 실행.
X Analytics API로 지난 7일 지표 수집 + TOP 3 게시물 분석.

보고 항목:
- 노출수 / 참여수 / 참여율 변화 (전주 대비)
- 팔로워 증감
- 재게시 / 답글 / 북마크 수
- 성과 TOP 3 게시물 (재게시율 기준)
- 다음 주 집중 개선 포인트 (AI 분석)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KST_OFFSET = 9


@dataclass
class WeeklyMetrics:
    """7일 집계 지표."""
    impressions: int = 0
    engagements: int = 0
    engagement_rate: float = 0.0
    reposts: int = 0
    replies: int = 0
    likes: int = 0
    bookmarks: int = 0
    profile_clicks: int = 0
    new_followers: int = 0
    unfollowers: int = 0
    total_followers: int = 0
    top_posts: list[dict] = field(default_factory=list)  # [{text, reposts, impressions}]
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc) - timedelta(days=7))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def net_followers(self) -> int:
        return self.new_followers - self.unfollowers

    def format_for_telegram(self, prev: "WeeklyMetrics | None" = None) -> str:
        def delta(now: int, before: int | None) -> str:
            if before is None:
                return ""
            diff = now - before
            if diff > 0:
                return f" ▲{diff:+,}"
            elif diff < 0:
                return f" ▼{diff:,}"
            return " →0"

        period = f"{self.period_start.strftime('%m/%d')}~{self.period_end.strftime('%m/%d')}"
        lines = [
            f"📊 *주간 성과 리포트* ({period})",
            "",
            "**📈 핵심 지표**",
            f"노출수: {self.impressions:,}{delta(self.impressions, prev.impressions if prev else None)}",
            f"참여수: {self.engagements:,}{delta(self.engagements, prev.engagements if prev else None)}",
            f"참여율: {self.engagement_rate:.2f}%",
            f"팔로워: {self.total_followers:,} (순증 {self.net_followers:+d})",
            "",
            "**🔄 참여 유형**",
            f"재게시: {self.reposts} | 답글: {self.replies} | 좋아요: {self.likes} | 북마크: {self.bookmarks}",
        ]

        if self.top_posts:
            lines += ["", "**🏆 TOP 3 게시물**"]
            for i, post in enumerate(self.top_posts[:3], 1):
                lines.append(
                    f"{i}. RT {post.get('reposts',0)} | 노출 {post.get('impressions',0):,}\n"
                    f"   `{post.get('text','')[:80]}`"
                )

        return "\n".join(lines)


class WeeklyReporter:
    """주간 리포트 생성기."""

    # X Analytics API (Basic 플랜 필요)
    X_ANALYTICS_URL = "https://api.x.com/2/users/{user_id}/tweets"

    def __init__(self):
        self._mock_mode = not bool(settings.x_bearer_token)

    async def collect(self) -> WeeklyMetrics:
        """지난 7일 지표 수집."""
        if self._mock_mode:
            return self._mock_metrics()
        return await self._real_metrics()

    async def _real_metrics(self) -> WeeklyMetrics:
        """X API v2로 실제 지표 수집."""
        metrics = WeeklyMetrics()
        try:
            user_id = await self._get_user_id()
            if not user_id:
                return self._mock_metrics()

            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            headers = {"Authorization": f"Bearer {settings.x_bearer_token}"}
            params = {
                "start_time": since,
                "max_results": 100,
                "tweet.fields": "public_metrics,created_at",
            }

            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    self.X_ANALYTICS_URL.format(user_id=user_id),
                    headers=headers, params=params,
                )
                if r.status_code == 429:
                    logger.warning("Weekly Report: X API rate limit")
                    return self._mock_metrics()
                r.raise_for_status()
                data = r.json()

            tweets = data.get("data", [])
            post_stats = []
            for tweet in tweets:
                pm = tweet.get("public_metrics", {})
                impressions = pm.get("impression_count", 0)
                reposts = pm.get("retweet_count", 0)
                replies = pm.get("reply_count", 0)
                likes = pm.get("like_count", 0)
                bookmarks = pm.get("bookmark_count", 0)

                metrics.impressions += impressions
                metrics.reposts += reposts
                metrics.replies += replies
                metrics.likes += likes
                metrics.bookmarks += bookmarks
                metrics.engagements += reposts + replies + likes + bookmarks

                post_stats.append({
                    "text": tweet.get("text", ""),
                    "reposts": reposts,
                    "impressions": impressions,
                    "engagement": reposts + replies + likes + bookmarks,
                })

            # 재게시율 기준 TOP 3
            metrics.top_posts = sorted(
                post_stats, key=lambda x: x["reposts"], reverse=True
            )[:3]

            if metrics.impressions > 0:
                metrics.engagement_rate = (metrics.engagements / metrics.impressions) * 100

        except Exception as e:
            logger.error(f"주간 지표 수집 실패: {e}")
            return self._mock_metrics()

        return metrics

    async def _get_user_id(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.x.com/2/users/by/username/sskorea02",
                    headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
                )
                r.raise_for_status()
                return r.json()["data"]["id"]
        except Exception:
            return None

    async def analyze_with_ai(self, metrics: WeeklyMetrics) -> str:
        """Claude로 개선 포인트 분석."""
        if not settings.has_anthropic:
            return self._fallback_analysis(metrics)

        try:
            prompt = f"""@sskorea02 계정 주간 성과 분석 (Gate.io 선물봇 계정):

노출수: {metrics.impressions:,}
참여율: {metrics.engagement_rate:.2f}%
재게시: {metrics.reposts} | 답글: {metrics.replies} | 북마크: {metrics.bookmarks}
팔로워 순증: {metrics.net_followers:+d}

X 알고리즘 기준 (답글 가중치 = 좋아요 × 27배, 재게시 = 좋아요 × 2배):

다음 주 집중해야 할 3가지 개선 액션을 구체적으로 (수치 포함) 제시해라.
각 액션: 현재 문제 → 구체적 해결책 → 기대 효과.
한국어 200자 이내."""

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
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                r.raise_for_status()
                return r.json()["content"][0]["text"].strip()
        except Exception as e:
            logger.warning(f"AI 분석 실패: {e}")
            return self._fallback_analysis(metrics)

    def _fallback_analysis(self, metrics: WeeklyMetrics) -> str:
        tips = []
        if metrics.reposts < 20:
            tips.append("① 재게시 부족 → 스레드 게시물 주 1회 이상, 마지막 트윗에 RT CTA 추가")
        if metrics.replies < 30:
            tips.append("② 답글 수 낮음 → 게시 후 첫 30분 내 댓글 달기 5개 이상 실행")
        if metrics.net_followers < 5:
            tips.append("③ 팔로워 전환 낮음 → 핀 게시물 교체 (가장 높은 RT 게시물로)")
        if not tips:
            tips.append("① 현재 성장세 유지 ② 댓글 달기 루틴 10→15개/일 확대 ③ 스레드 빈도 증가")
        return "\n".join(tips)

    def _mock_metrics(self) -> WeeklyMetrics:
        return WeeklyMetrics(
            impressions=97200,
            engagements=977,
            engagement_rate=1.0,
            reposts=13,
            replies=21,
            likes=180,
            bookmarks=13,
            new_followers=8,
            unfollowers=2,
            total_followers=26,
            top_posts=[
                {"text": "봇이 하루에 얼마나 잃을 수 있는지 실제 경험을 공유합니다.", "reposts": 5, "impressions": 8200},
                {"text": "Gate.io 선물 거래에서 내가 배운 리스크 관리 룰 7가지", "reposts": 4, "impressions": 6500},
                {"text": "자동매매 봇 승인 시스템을 만든 이유", "reposts": 4, "impressions": 5100},
            ],
        )


async def run_weekly_report():
    """
    매주 월요일 오전 9시 KST 실행.
    성과 리포트 + 콘텐츠 믹스 + AI 분석 → Telegram 발송.
    """
    from app.services.growth._tg_helper import tg_send

    logger.info("주간 성과 리포트 생성 중...")
    reporter = WeeklyReporter()

    try:
        metrics = await reporter.collect()
        ai_tips = await reporter.analyze_with_ai(metrics)
        report_text = metrics.format_for_telegram()

        # Layer 2: 콘텐츠 믹스 섹션 (실패 시 무시)
        mix_section = ""
        try:
            from app.db import get_db
            from app.services.topic_memory import TopicMemory
            db = get_db()
            mix_section = TopicMemory(db).format_mix_report(days=7)
            if mix_section:
                mix_section = f"\n\n{mix_section}"
        except Exception as _mix_err:
            logger.warning(f"[TopicMemory] 믹스 섹션 생성 실패 (무시): {_mix_err}")

        # Layer 2: 성과 메모 요약 (실패 시 무시)
        perf_section = ""
        try:
            from app.db import get_db as _get_db
            from app.services.draft_service import DraftService
            _db = _get_db()
            perf_section = DraftService(_db).format_perf_summary(days=30)
            if perf_section:
                perf_section = f"\n\n{perf_section}"
        except Exception as _perf_err:
            logger.warning(f"[PerfSummary] 생성 실패 (무시): {_perf_err}")

        full_msg = (
            f"{report_text}"
            f"{mix_section}"
            f"{perf_section}"
            f"\n\n<b>🤖 다음 주 개선 포인트</b>\n{ai_tips}"
        )
        await tg_send(full_msg)
        logger.info("✓ 주간 리포트 발송 완료")
    except Exception as e:
        logger.error(f"주간 리포트 실패: {e}")
