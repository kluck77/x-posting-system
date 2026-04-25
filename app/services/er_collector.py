"""ER 시계열 수집 — X API 로 T+30분 / T+24시간 / T+7일 스냅샷.

가중 ER 공식: like×1 + RT×20 + bookmark×10 + reply×13.5

post_performance.py 와 별도 테이블 (er_history vs post_metrics) 로 공존.
schedule_er_collection 은 운영자가 수동 발행 후 호출 (자동 발행 없음).
benchmark_competitor 는 매일 03:00 KST 백그라운드 갱신.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul") if ZoneInfo else None


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


def calc_weighted_er(
    likes: int, retweets: int, bookmarks: int, replies: int,
) -> float:
    """사용자 정의 가중 ER — like×1 + RT×20 + bookmark×10 + reply×13.5."""
    return (
        (likes or 0) * 1.0
        + (retweets or 0) * 20.0
        + (bookmarks or 0) * 10.0
        + (replies or 0) * 13.5
    )


def _now_kst_iso() -> str:
    return (datetime.now(KST) if KST else datetime.utcnow()).isoformat()


async def fetch_tweet_metrics(tweet_id: str) -> dict | None:
    """X API v2 로 트윗 메트릭 조회. 실패 시 None."""
    bearer = getattr(settings, "x_bearer_token", "") or ""
    if not bearer:
        logger.warning("[ER] X Bearer Token 없음 — skip")
        return None
    base_url = f"https://api.twitter.com/2/tweets/{tweet_id}"
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                base_url,
                params={"tweet.fields": "public_metrics,non_public_metrics"},
                headers=headers,
            )
            if resp.status_code == 403:
                # non_public_metrics 는 OAuth 1.0a 필요 — public 만 재시도
                resp = await client.get(
                    base_url,
                    params={"tweet.fields": "public_metrics"},
                    headers=headers,
                )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", {}) or {}
            pm = data.get("public_metrics", {}) or {}
            npm = data.get("non_public_metrics", {}) or {}
            return {
                "likes":       int(pm.get("like_count", 0) or 0),
                "retweets":    int(pm.get("retweet_count", 0) or 0),
                "replies":     int(pm.get("reply_count", 0) or 0),
                "quotes":      int(pm.get("quote_count", 0) or 0),
                "bookmarks":   int(pm.get("bookmark_count", 0) or 0),
                "impressions": int(
                    pm.get("impression_count")
                    or npm.get("impression_count", 0)
                    or 0
                ),
            }
    except Exception as e:
        logger.warning(f"[ER] 메트릭 조회 실패 {tweet_id}: {e}")
        return None


def save_snapshot(post_id: str, metrics: dict, minutes_since: int) -> None:
    """ER 스냅샷 DB 저장."""
    if not metrics:
        return
    try:
        wer = calc_weighted_er(
            metrics["likes"], metrics["retweets"],
            metrics["bookmarks"], metrics["replies"],
        )
        impr = metrics.get("impressions") or 1
        er_per_impr = round(wer / impr, 6)
        conn = sqlite3.connect(_sqlite_path())
        from app.services.pattern_db import _ensure_tables
        _ensure_tables(conn)
        conn.execute("""
            INSERT INTO er_history
            (post_id, snapshot_at, minutes_since,
             impressions, likes, retweets, replies,
             quotes, bookmarks, weighted_er, er_per_impression)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post_id, _now_kst_iso(), minutes_since,
            metrics["impressions"], metrics["likes"], metrics["retweets"],
            metrics["replies"], metrics["quotes"], metrics["bookmarks"],
            wer, er_per_impr,
        ))
        conn.commit()
        conn.close()
        logger.info(
            f"[ER] {post_id} T+{minutes_since}분 "
            f"weighted_er={wer:.1f} er/impr={er_per_impr:.5f}"
        )
    except Exception as e:
        logger.warning(f"[ER] save_snapshot 실패: {e}")


async def schedule_er_collection(
    post_id: str, posted_at: datetime,
) -> None:
    """발행 후 3 시점 자동 수집 — 30분 / 24시간 / 7일."""
    for minutes in (30, 1440, 10080):
        try:
            target = posted_at + timedelta(minutes=minutes)
            now = datetime.now(KST) if KST else datetime.utcnow()
            wait = (target - now).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
            metrics = await fetch_tweet_metrics(post_id)
            if metrics:
                save_snapshot(post_id, metrics, minutes)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[ER] schedule 단계 실패 ({minutes}분): {e}")


async def benchmark_competitor(handle: str) -> None:
    """경쟁계정 30일 평균 ER 수집."""
    bearer = getattr(settings, "x_bearer_token", "") or ""
    if not bearer:
        logger.debug("[ER] benchmark — bearer 없음 skip")
        return
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            ur = await client.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                params={"user.fields": "public_metrics"},
                headers=headers,
            )
            ur.raise_for_status()
            ud = (ur.json() or {}).get("data", {}) or {}
            user_id = ud.get("id")
            if not user_id:
                logger.warning(f"[ER] @{handle} user_id 미확인")
                return
            followers = int(
                (ud.get("public_metrics") or {}).get("followers_count", 0)
                or 0
            )

            tr = await client.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                params={
                    "max_results": 100,
                    "tweet.fields": "public_metrics,created_at",
                },
                headers=headers,
            )
            tr.raise_for_status()
            tweets = (tr.json() or {}).get("data", []) or []
            if not tweets:
                return

            cutoff = (
                (datetime.now(KST) if KST else datetime.utcnow())
                - timedelta(days=30)
            )
            recent = []
            for t in tweets:
                try:
                    created = datetime.fromisoformat(
                        t["created_at"].replace("Z", "+00:00")
                    )
                    if KST:
                        created = created.astimezone(KST)
                except Exception:
                    continue
                if created < cutoff:
                    continue
                pm = t.get("public_metrics", {}) or {}
                wer = calc_weighted_er(
                    pm.get("like_count", 0), pm.get("retweet_count", 0),
                    pm.get("bookmark_count", 0), pm.get("reply_count", 0),
                )
                recent.append({
                    "likes":     int(pm.get("like_count", 0) or 0),
                    "rt":        int(pm.get("retweet_count", 0) or 0),
                    "replies":   int(pm.get("reply_count", 0) or 0),
                    "bookmarks": int(pm.get("bookmark_count", 0) or 0),
                    "wer":       wer,
                })
            if not recent:
                return

            def avg(k: str) -> float:
                return sum(r[k] for r in recent) / len(recent)

            conn = sqlite3.connect(_sqlite_path())
            from app.services.pattern_db import _ensure_tables
            _ensure_tables(conn)
            conn.execute("""
                INSERT INTO account_benchmarks
                (handle, follower_count, follower_updated,
                 avg_likes_30d, avg_rt_30d, avg_replies_30d,
                 avg_bookmarks_30d, avg_weighted_er)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(handle) DO UPDATE SET
                    follower_count    = excluded.follower_count,
                    follower_updated  = excluded.follower_updated,
                    avg_likes_30d     = excluded.avg_likes_30d,
                    avg_rt_30d        = excluded.avg_rt_30d,
                    avg_replies_30d   = excluded.avg_replies_30d,
                    avg_bookmarks_30d = excluded.avg_bookmarks_30d,
                    avg_weighted_er   = excluded.avg_weighted_er
            """, (
                handle, followers, _now_kst_iso(),
                avg("likes"), avg("rt"),
                avg("replies"), avg("bookmarks"),
                avg("wer"),
            ))
            conn.commit()
            conn.close()
            logger.info(
                f"[ER] 벤치마크 갱신: @{handle} avg_wer={avg('wer'):.1f}"
            )
    except Exception as e:
        logger.warning(f"[ER] 벤치마크 실패 @{handle}: {e}")
