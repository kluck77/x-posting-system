"""경쟁자 포스트 모니터링.

6개(config.competitor_accounts) 계정의 Nitter RSS 를 수집해
훅 타입 / 명사 키워드 추출 후 SQLite 에 누적.
X API 미사용 — Nitter RSS 만.
kiwipiepy 미설치 시 정규식 fallback.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Nitter 공개 인스턴스 (순차 fallback — 다수 인스턴스 종료 중)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

HOOK_TYPES = {
    "question":  re.compile(r"\?$|입니까\?|인가\?|될까\?"),
    "assertion": re.compile(r"이다\.|임\.|본다\.|한다\.$"),
    "contrast":  re.compile(r"반면|하지만|그러나|오히려"),
    "number":    re.compile(r"^\d|^[₩$€£]|\d+[%조억만]"),
}

# kiwipiepy 모듈 레벨 lazy init (함수마다 재생성 회피)
try:
    from kiwipiepy import Kiwi  # type: ignore
    _KIWI = Kiwi(model_type="cong")
    _KIWI_OK = True
except Exception:
    _KIWI = None
    _KIWI_OK = False


def _sqlite_path() -> str:
    """settings.database_url 에서 sqlite 파일 경로 추출. sqlite 가 아니면 기본값."""
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


@dataclass
class CompetitorPost:
    account:       str
    post_id:       str
    content:       str
    hook_type:     str = ""
    noun_keywords: list[str] = field(default_factory=list)
    is_viral:      bool = False
    fetched_at:    float = 0.0


def _extract_hook_type(text: str) -> str:
    stripped = (text or "").strip()
    for htype, pattern in HOOK_TYPES.items():
        if pattern.search(stripped):
            return htype
    return "other"


def _extract_nouns(text: str) -> list[str]:
    if _KIWI_OK:
        try:
            tokens = _KIWI.tokenize(text)
            return list(dict.fromkeys(
                t.form for t in tokens
                if t.tag in ("NNG", "NNP", "SL") and len(t.form) > 1
            ))[:10]
        except Exception:
            pass
    # fallback: 한글/대문자 연속 2자 이상
    words = re.findall(r"[가-힣A-Z]{2,}", text)
    return list(dict.fromkeys(words))[:10]


async def _fetch_nitter_rss(account: str) -> list[dict]:
    """Nitter RSS 로 계정 최신 포스트 수집. 모든 인스턴스 실패 시 빈 리스트."""
    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/{account}/rss"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    url, headers={"User-Agent": "CryptoMonitor/1.0"}
                )
                if resp.status_code != 200:
                    continue
            root = ET.fromstring(resp.text)
            items = []
            for item in root.findall(".//item")[:10]:
                title    = item.findtext("title", "") or ""
                link     = item.findtext("link", "") or ""
                pub_date = item.findtext("pubDate", "") or ""
                post_id = hashlib.md5(link.encode()).hexdigest()[:12]
                items.append({
                    "post_id":  post_id,
                    "content":  title,
                    "link":     link,
                    "pub_date": pub_date,
                })
            return items
        except Exception as e:
            logger.debug(f"[Competitor] {instance} 실패: {e}")
            continue
    return []


async def collect_all() -> list[CompetitorPost]:
    """모든 경쟁자 계정 수집. 계정 간 2초 딜레이 (rate limit 준수)."""
    accounts = getattr(settings, "competitor_accounts", None) or [
        "ki_young_ju", "Semicon_player", "fdd3001",
        "ogunyo_macro", "Jaemyung_Lee", "unusual_whales",
    ]
    all_posts: list[CompetitorPost] = []
    for account in accounts:
        raw_posts = await _fetch_nitter_rss(account)
        for p in raw_posts:
            all_posts.append(CompetitorPost(
                account=account,
                post_id=p["post_id"],
                content=p["content"],
                hook_type=_extract_hook_type(p["content"]),
                noun_keywords=_extract_nouns(p["content"]),
                fetched_at=time.time(),
            ))
        logger.info(f"[Competitor] @{account}: {len(raw_posts)}개 수집")
        await asyncio.sleep(2.0)
    return all_posts


def save_to_db(posts: list[CompetitorPost], db_path: str | None = None) -> None:
    """SQLite 에 저장 (IGNORE 중복). 테이블 없으면 생성."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS competitor_posts (
                post_id TEXT PRIMARY KEY,
                account TEXT,
                content TEXT,
                hook_type TEXT,
                noun_keywords TEXT,
                is_viral INTEGER DEFAULT 0,
                fetched_at REAL
            )
        """)
        for post in posts:
            cursor.execute("""
                INSERT OR IGNORE INTO competitor_posts
                (post_id, account, content, hook_type,
                 noun_keywords, is_viral, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                post.post_id, post.account, post.content,
                post.hook_type,
                json.dumps(post.noun_keywords, ensure_ascii=False),
                int(post.is_viral), post.fetched_at,
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Competitor] DB 저장 실패: {e}")


def get_pattern_summary(days: int = 30, db_path: str | None = None) -> dict:
    """최근 N일 패턴 요약. 실패 시 {}."""
    path = db_path or _sqlite_path()
    since = time.time() - (days * 86400)
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT hook_type, COUNT(*) as cnt
            FROM competitor_posts
            WHERE fetched_at > ?
            GROUP BY hook_type
            ORDER BY cnt DESC
        """, (since,))
        hook_stats = dict(cursor.fetchall())

        cursor.execute("""
            SELECT noun_keywords FROM competitor_posts
            WHERE fetched_at > ? LIMIT 200
        """, (since,))
        all_nouns: list[str] = []
        for (kw_json,) in cursor.fetchall():
            try:
                all_nouns.extend(json.loads(kw_json))
            except Exception:
                pass

        from collections import Counter
        top_nouns = Counter(all_nouns).most_common(20)
        conn.close()
        return {
            "hook_type_distribution": hook_stats,
            "top_keywords":           top_nouns,
            "days_analyzed":          days,
        }
    except Exception as e:
        logger.warning(f"[Competitor] 패턴 요약 실패: {e}")
        return {}
