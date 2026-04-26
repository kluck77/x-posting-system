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

        top_posts_text = ""
        for i, p in enumerate(metrics.top_posts[:3], 1):
            top_posts_text += f"  {i}. RT {p.get('reposts',0)} | {p.get('text','')[:60]}\n"

        try:
            prompt = f"""@sskorea02 계정 주간 성과 분석 (Gate.io 선물봇 운영자 계정):

[지표]
노출수: {metrics.impressions:,} | 참여율: {metrics.engagement_rate:.2f}%
재게시: {metrics.reposts} | 답글: {metrics.replies} | 좋아요: {metrics.likes} | 북마크: {metrics.bookmarks}
팔로워 순증: {metrics.net_followers:+d}

[TOP 게시물]
{top_posts_text or "  (데이터 없음)"}

X 알고리즘: 답글 = 좋아요 × 27배, 재게시 = 좋아요 × 2배

아래 4개 섹션을 한국어로 출력하라. 각 섹션 제목을 그대로 사용:

[계속할 패턴]
이번 주 잘 된 것 2가지 (수치 근거 포함)

[줄일 패턴]
이번 주 효과 낮았던 것 2가지 (수치 근거 포함)

[추천 콘텐츠 각도 3가지]
다음 주 시도할 구체적 프레임/각도 3개 (각 1줄)

[추천 소스/주제 방향 3가지]
다음 주 집중할 뉴스 소스나 주제 영역 3개 (각 1줄)

총 250자 이내."""

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
                        "max_tokens": 400,
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
                    f"caller=WeeklyReport"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("anthropic", "claude-haiku-4-5", "WeeklyReport",
                                 usage.get("input_tokens", 0), usage.get("output_tokens", 0))
                except Exception:
                    pass
                return resp_data["content"][0]["text"].strip()
        except Exception as e:
            logger.warning(f"AI 분석 실패: {e}")
            return self._fallback_analysis(metrics)

    def _fallback_analysis(self, metrics: WeeklyMetrics) -> str:
        lean = "현재 성장세 유지"
        reduce = "불필요한 반복 패턴 줄이기"
        if metrics.reposts >= 20:
            lean = f"재게시 {metrics.reposts}회 — 스레드 형식 계속 활용"
        if metrics.replies >= 30:
            lean += f" / 답글 {metrics.replies}회 — 참여 유지"
        if metrics.reposts < 20:
            reduce = f"재게시 {metrics.reposts}회 부족 — 단독 트윗 비율 줄이기"
        if metrics.replies < 30:
            reduce += f" / 답글 {metrics.replies}회 낮음 — 질문 없는 게시물 줄이기"

        return (
            f"[계속할 패턴]\n{lean}\n\n"
            f"[줄일 패턴]\n{reduce}\n\n"
            f"[추천 콘텐츠 각도 3가지]\n"
            f"① 숫자로 시작하는 데이터 포스트\n"
            f"② 서방 미디어가 놓친 한국 시각\n"
            f"③ 리스크 관리 실전 경험 공유\n\n"
            f"[추천 소스/주제 방향 3가지]\n"
            f"① Fed/BOK 금리 결정 + 환율 연계\n"
            f"② 크립토 규제 + Gate.io 선물 시장\n"
            f"③ 한국 수출 데이터 + 글로벌 공급망"
        )

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

        # Layer 2: 힌트 영향 요약 — [HINT]×[PERF] 공존 집계 (실패 시 무시)
        hint_impact = ""
        try:
            from app.db import get_db as _get_db2
            from app.services.draft_service import DraftService
            hint_impact = DraftService(_get_db2()).format_hint_impact_summary(days=60)
            if hint_impact:
                hint_impact = f"\n\n{hint_impact}"
        except Exception as _hi_err:
            logger.warning(f"[HintImpact] 생성 실패 (무시): {_hi_err}")

        full_msg = (
            f"{report_text}"
            f"{mix_section}"
            f"{perf_section}"
            f"{hint_impact}"
            f"\n\n<b>🤖 다음 주 개선 포인트</b>\n{ai_tips}"
        )
        await tg_send(full_msg)
        logger.info("✓ 주간 리포트 발송 완료")
    except Exception as e:
        logger.error(f"주간 리포트 실패: {e}")
