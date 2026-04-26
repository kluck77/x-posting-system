"""포스트 성과 자동 기록 — X API 로 발행 후 ER 추적.

snapshot_type 별 측정 시점:
  1h:  발행 1시간 후
  6h:  발행 6시간 후
  24h: 발행 24시간 후 (이후 measure_complete=1)

posted_tweets 테이블은 운영자가 별도 단계에서 수동/스크립트 등록.
이 모듈 자체는 자동 발행 기능 없음. 메트릭 조회만 수행.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


@dataclass
class PostMetrics:
    tweet_id:       str
    impressions:    int = 0
    likes:          int = 0
    replies:        int = 0
    retweets:       int = 0
    bookmarks:      int = 0
    profile_visits: int = 0
    measured_at:    float = 0.0

    @property
    def engagement_rate(self) -> float:
        if self.impressions == 0:
            return 0.0
        total = self.likes + self.replies + self.retweets + self.bookmarks
        return round(total / self.impressions * 100, 2)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posted_tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT UNIQUE,
            draft_id INTEGER,
            posted_at REAL,
            measure_complete INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            snapshot_type TEXT,
            impressions INTEGER,
            likes INTEGER,
            replies INTEGER,
            retweets INTEGER,
            bookmarks INTEGER,
            profile_visits INTEGER,
            engagement_rate REAL,
            measured_at REAL
        )
    """)


async def fetch_tweet_metrics(tweet_id: str) -> PostMetrics | None:
    """X API v2 로 트윗 메트릭 조회. 실패 시 None."""
    bearer = getattr(settings, "x_bearer_token", "") or ""
    if not bearer:
        logger.debug("[Performance] x_bearer_token 없음 — skip")
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.x.com/2/tweets/{tweet_id}",
                params={
                    "tweet.fields": "public_metrics,non_public_metrics",
                },
                headers={"Authorization": f"Bearer {bearer}"},
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", {}) or {}
            metrics = data.get("public_metrics", {}) or {}
            non_public = data.get("non_public_metrics", {}) or {}
            return PostMetrics(
                tweet_id=tweet_id,
                impressions=int(non_public.get("impression_count", 0) or 0),
                likes=int(metrics.get("like_count", 0) or 0),
                replies=int(metrics.get("reply_count", 0) or 0),
                retweets=int(metrics.get("retweet_count", 0) or 0),
                bookmarks=int(metrics.get("bookmark_count", 0) or 0),
                profile_visits=int(non_public.get("user_profile_clicks", 0) or 0),
                measured_at=time.time(),
            )
    except Exception as e:
        logger.warning(f"[Performance] {tweet_id} 메트릭 실패: {e}")
        return None


def save_metrics(metrics: PostMetrics, snapshot_type: str) -> None:
    try:
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        conn.execute("""
            INSERT INTO post_metrics
            (tweet_id, snapshot_type, impressions, likes, replies,
             retweets, bookmarks, profile_visits,
             engagement_rate, measured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.tweet_id, snapshot_type,
            metrics.impressions, metrics.likes, metrics.replies,
            metrics.retweets, metrics.bookmarks, metrics.profile_visits,
            metrics.engagement_rate, metrics.measured_at,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Performance] save_metrics 실패: {e}")


def _has_snapshot(tweet_id: str, snapshot_type: str) -> bool:
    try:
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        cur = conn.execute(
            "SELECT 1 FROM post_metrics WHERE tweet_id=? AND snapshot_type=? LIMIT 1",
            (tweet_id, snapshot_type),
        )
        row = cur.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _mark_complete(tweet_id: str) -> None:
    try:
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        conn.execute(
            "UPDATE posted_tweets SET measure_complete=1 WHERE tweet_id=?",
            (tweet_id,),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Performance] mark_complete 실패: {e}")


async def measure_loop():
    """스케줄러 루프 — posted_tweets 에서 측정 대상 조회 후 처리. 5분 주기."""
    while True:
        try:
            now = time.time()
            try:
                conn = sqlite3.connect(_sqlite_path())
                _ensure_tables(conn)
                cur = conn.execute("""
                    SELECT tweet_id, posted_at
                    FROM posted_tweets
                    WHERE measure_complete = 0
                    ORDER BY posted_at DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
                conn.close()
            except Exception as e:
                logger.warning(f"[Performance] DB 조회 실패: {e}")
                rows = []

            for tweet_id, posted_at in rows:
                age = now - float(posted_at or 0)

                if 3500 <= age <= 3700 and not _has_snapshot(tweet_id, "1h"):
                    m = await fetch_tweet_metrics(tweet_id)
                    if m:
                        save_metrics(m, "1h")
                        logger.info(
                            f"[Performance] {tweet_id} 1h ER={m.engagement_rate}%"
                        )
                elif 21500 <= age <= 21700 and not _has_snapshot(tweet_id, "6h"):
                    m = await fetch_tweet_metrics(tweet_id)
                    if m:
                        save_metrics(m, "6h")
                elif age >= 86400:
                    m = await fetch_tweet_metrics(tweet_id)
                    if m:
                        save_metrics(m, "24h")
                        _mark_complete(tweet_id)
                        logger.info(
                            f"[Performance] {tweet_id} 24h 완료 ER={m.engagement_rate}%"
                        )
        except Exception as e:
            logger.warning(f"[Performance] 루프 오류: {e}")

        await asyncio.sleep(300)  # 5분


def get_today_performance() -> dict:
    """오늘 발행 포스트 성과 요약."""
    try:
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp()
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        cur = conn.execute("""
            SELECT pt.tweet_id, pt.posted_at,
                   pm.impressions, pm.engagement_rate,
                   pm.likes, pm.replies, pm.bookmarks
            FROM posted_tweets pt
            LEFT JOIN post_metrics pm
                   ON pt.tweet_id = pm.tweet_id
                   AND pm.snapshot_type = '1h'
            WHERE pt.posted_at >= ?
            ORDER BY pt.posted_at DESC
        """, (today_start,))
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.warning(f"[Performance] today 조회 실패: {e}")
        rows = []

    total = len(rows)
    avg_er = (
        sum(float(r[3] or 0) for r in rows) / total if total > 0 else 0
    )
    return {
        "total_posts": total,
        "avg_engagement_rate": round(avg_er, 2),
        "posts": [
            {
                "tweet_id":    r[0],
                "posted_at":   r[1],
                "impressions": int(r[2] or 0),
                "er":          float(r[3] or 0),
                "likes":       int(r[4] or 0),
                "replies":     int(r[5] or 0),
                "bookmarks":   int(r[6] or 0),
            }
            for r in rows
        ],
    }
