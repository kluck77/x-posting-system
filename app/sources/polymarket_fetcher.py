"""Polymarket Gamma API 데이터 수집기.

인증 불필요. 공개 REST API.
매크로·크립토 시장 확률 실시간 수집 → SQLite 저장.

거래 엔드포인트(POST /orders 등) 절대 호출 금지 — 조회만.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"

# 관심 키워드 (매크로·크립토·정책)
FILTER_KEYWORDS = [
    # 크립토
    "bitcoin", "btc", "ethereum", "eth", "solana",
    "etf", "sec", "crypto", "gensler",
    # 매크로
    "fed", "federal reserve", "recession", "inflation",
    "cpi", "interest rate", "treasury", "gdp",
    # 정책
    "trump", "tariff", "sanctions", "trade",
    # 한국
    "korea", "kospi", "won",
]


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


@dataclass
class PolymarketItem:
    question:     str
    slug:         str
    yes_prob:     float
    no_prob:      float
    volume_24h:   float
    liquidity:    float
    end_date:     str
    condition_id: str
    category:     str = ""
    change_24h:   float = 0.0
    fetched_at:   float = field(default_factory=time.time)


def _parse_outcome_prices(raw) -> tuple[float, float]:
    """outcomePrices 파싱. JSON 문자열 또는 리스트 처리."""
    try:
        prices = json.loads(raw) if isinstance(raw, str) else raw
        yes = float(prices[0])
        no = float(prices[1]) if len(prices) > 1 else 1 - yes
        return round(yes, 4), round(no, 4)
    except Exception:
        return 0.5, 0.5


def _categorize(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ["bitcoin", "btc", "ethereum", "eth",
                            "crypto", "etf", "sec", "solana"]):
        return "crypto"
    if any(k in q for k in ["fed", "rate", "recession", "inflation",
                            "cpi", "gdp", "treasury"]):
        return "macro"
    if any(k in q for k in ["trump", "tariff", "election", "trade"]):
        return "policy"
    return "other"


async def fetch_top_markets(limit: int = 50) -> list[PolymarketItem]:
    """Gamma API 에서 volume24hr 상위 시장 수집 + 키워드 필터."""
    params = {
        "active":    "true",
        "closed":    "false",
        "limit":     str(limit),
        "order":     "volume24hr",
        "ascending": "false",
    }
    results: list[PolymarketItem] = []
    try:
        await asyncio.sleep(0.1)  # rate limit
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{BASE_URL}/markets",
                params=params,
                headers={"User-Agent": "sskorea02-bot/1.0"},
            )
            resp.raise_for_status()
            markets = resp.json()
        for m in markets or []:
            question = m.get("question", "") or ""
            q_lower = question.lower()
            if not any(k in q_lower for k in FILTER_KEYWORDS):
                continue
            if not m.get("enableOrderBook", True):
                continue
            yes_p, no_p = _parse_outcome_prices(
                m.get("outcomePrices", "[0.5,0.5]")
            )
            results.append(PolymarketItem(
                question=question,
                slug=m.get("slug", "") or "",
                yes_prob=yes_p,
                no_prob=no_p,
                volume_24h=float(m.get("volume24hr", 0) or 0),
                liquidity=float(m.get("liquidity", 0) or 0),
                end_date=str(m.get("endDate", "") or ""),
                condition_id=str(m.get("conditionId", "") or ""),
                category=_categorize(question),
            ))
        logger.info(f"[Polymarket] 수집 {len(results)}개 시장")
        return results
    except Exception as e:
        logger.warning(f"[Polymarket] 수집 실패: {e}")
        return []


async def fetch_with_retry(limit: int = 50) -> list[PolymarketItem]:
    """Exponential backoff 재시도 3회."""
    for attempt in range(3):
        result = await fetch_top_markets(limit)
        if result:
            return result
        wait = 2 ** attempt
        logger.warning(f"[Polymarket] 재시도 {attempt + 1}/3, {wait}s 대기")
        await asyncio.sleep(wait)
    return []


def save_to_db(
    items: list[PolymarketItem],
    db_path: str | None = None,
) -> None:
    """SQLite 저장. 테이블 없으면 생성. condition_id 기준 REPLACE."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS polymarket_markets (
                condition_id TEXT PRIMARY KEY,
                question TEXT,
                slug TEXT,
                yes_prob REAL,
                no_prob REAL,
                volume_24h REAL,
                liquidity REAL,
                end_date TEXT,
                category TEXT,
                change_24h REAL DEFAULT 0,
                fetched_at REAL
            )
        """)
        for item in items:
            cursor.execute("""
                INSERT OR REPLACE INTO polymarket_markets
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.condition_id, item.question, item.slug,
                item.yes_prob, item.no_prob, item.volume_24h,
                item.liquidity, item.end_date, item.category,
                item.change_24h, item.fetched_at,
            ))
        conn.commit()
        conn.close()
        logger.info(f"[Polymarket] DB 저장 {len(items)}개")
    except Exception as e:
        logger.warning(f"[Polymarket] DB 저장 실패: {e}")


def get_top_by_category(
    category: str = "crypto",
    limit: int = 5,
    db_path: str | None = None,
) -> list[dict]:
    """카테고리별 상위 시장 (1h 이내 fetched). 실패 시 []."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT question, yes_prob, volume_24h, end_date, slug
            FROM polymarket_markets
            WHERE category = ?
              AND fetched_at > ?
            ORDER BY volume_24h DESC
            LIMIT ?
        """, (category, time.time() - 3600, limit))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "question":   r[0],
                "yes_prob":   r[1],
                "yes_pct":    f"{r[1] * 100:.0f}%",
                "volume_24h": r[2],
                "end_date":   r[3],
                "url":        f"https://polymarket.com/event/{r[4]}",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[Polymarket] 조회 실패: {e}")
        return []


def format_for_post(items: list[dict]) -> str:
    """텔레그램 카드용 텍스트 포맷 (상위 3개)."""
    if not items:
        return ""
    lines = ["📊 폴리마켓 현재 확률:"]
    for item in items[:3]:
        q = (item.get("question") or "")[:30]
        lines.append(f"• {q}... → {item.get('yes_pct', '')}")
    return "\n".join(lines)
