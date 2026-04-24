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

# 관심 키워드 — 5 카테고리 (crypto / macro / stocks / politics / economy)
FILTER_KEYWORDS: dict[str, list[str]] = {
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "xrp", "ripple", "bnb", "dogecoin", "doge",
        "etf", "sec", "crypto", "gensler", "coinbase",
        "stablecoin", "defi", "nft", "blockchain",
        "binance", "upbit", "bithumb", "kimchi",
        "halving", "altcoin",
    ],
    "macro": [
        "fed", "federal reserve", "recession", "inflation",
        "cpi", "ppi", "interest rate", "treasury", "gdp",
        "unemployment", "payroll", "nfp", "fomc",
        "dollar", "dxy", "yield curve", "bond",
        "bank of korea", "bok", "won", "krw",
        "oil", "crude", "brent", "wti",
        "gold", "silver", "commodity",
    ],
    "stocks": [
        "nasdaq", "s&p", "sp500", "dow jones",
        "nvidia", "apple", "microsoft", "tesla",
        "samsung", "sk hynix", "tsmc",
        "ipo", "earnings", "stock market",
        "kospi", "kosdaq", "nikkei",
        "hbm", "semiconductor", "chip",
        "mag7", "magnificent",
    ],
    "politics": [
        "trump", "biden", "harris",
        "election", "president", "congress",
        "tariff", "trade war", "sanctions",
        "ukraine", "russia", "china", "taiwan",
        "iran", "hormuz", "middle east",
        "korea president", "yoon", "lee jaemyung",
        "nato", "g7", "g20",
    ],
    "economy": [
        "gdp growth", "economic",
        "housing", "real estate", "mortgage",
        "bankruptcy", "default", "debt ceiling",
        "imf", "world bank", "oecd",
        "supply chain", "inflation rate",
        "consumer confidence", "retail sales",
    ],
}

# 필터용 flat 리스트 (fetch 필터 빠른 매칭)
ALL_KEYWORDS: list[str] = [
    kw for kws in FILTER_KEYWORDS.values() for kw in kws
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
    is_track1:    bool = False   # 거래량 TOP 20 (키워드 무관) — threshold 완화 대상
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


def _categorize_v2(question: str) -> str:
    """5 카테고리 중 점수 최대인 카테고리 반환 (score>0 이어야).

    crypto / macro / stocks / politics / economy / other.
    """
    q = (question or "").lower()
    scores: dict[str, int] = {}
    for cat, keywords in FILTER_KEYWORDS.items():
        scores[cat] = sum(1 for k in keywords if k in q)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


# backward compat alias (기존 호출부 보호)
_categorize = _categorize_v2


def _score_market(item: "PolymarketItem") -> int:
    """폴리마켓 시장 중요도 점수 (0~100).

    volume_24h 기준 base + 카테고리 가중치 + 극단 확률 페널티 + 50% 근처 가점.
    """
    vol = item.volume_24h or 0.0
    if   vol >= 50_000_000: base = 95
    elif vol >= 10_000_000: base = 90
    elif vol >= 1_000_000:  base = 80
    elif vol >= 500_000:    base = 70
    elif vol >= 100_000:    base = 60
    elif vol >= 10_000:     base = 50
    else:                   base = 35

    cat_bonus = {
        "crypto":   10,
        "macro":    10,
        "politics":  8,
        "stocks":    7,
        "economy":   5,
        "other":     0,
    }
    base += cat_bonus.get(item.category or "other", 0)

    yp = item.yes_prob or 0.5
    # 확률 극단(결정 임박) 감점 — 99%/1% 는 이미 결정 수준
    if yp >= 0.99 or yp <= 0.01:
        base -= 20
    # 확률 50% 근처 가점 — 아직 불확실 → 토론 가치 있음
    elif 0.35 <= yp <= 0.65:
        base += 5

    return max(0, min(100, base))


async def fetch_top_markets(limit: int = 100) -> list[PolymarketItem]:
    """Gamma API 에서 volume24hr 상위 시장 수집 — 2트랙 병행.

    트랙 1: 거래량 TOP 20 (키워드 무관, volume ≥ $100K)
    트랙 2: 키워드 매칭 (기존 방식)
    → condition_id 기준 dedup 후 track1 + track2 순서로 반환.

    is_track1 플래그는 threshold 완화 대상 식별용.
    """
    params = {
        "active":    "true",
        "closed":    "false",
        "limit":     str(limit),
        "order":     "volume24hr",
        "ascending": "false",
    }
    try:
        await asyncio.sleep(0.1)  # rate limit
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{BASE_URL}/markets",
                params=params,
                headers={"User-Agent": "sskorea02-bot/1.0"},
            )
            resp.raise_for_status()
            markets = resp.json() or []
    except Exception as e:
        logger.warning(f"[Polymarket] 수집 실패: {e}")
        return []

    track1: list[PolymarketItem] = []  # 거래량 TOP 20
    track2: list[PolymarketItem] = []  # 키워드 매칭
    seen_ids: set[str] = set()

    for i, m in enumerate(markets):
        question = m.get("question", "") or ""
        condition_id = str(m.get("conditionId", "") or "")
        if not m.get("enableOrderBook", True):
            continue
        yes_p, no_p = _parse_outcome_prices(
            m.get("outcomePrices", "[0.5,0.5]")
        )
        volume_24h = float(m.get("volume24hr", 0) or 0)

        # 트랙 1 자격 — API 응답 상위 20개 중 volume ≥ $100K
        is_t1 = (
            i < 20
            and volume_24h >= 100_000
            and condition_id
            and condition_id not in seen_ids
        )

        # 트랙 2 자격 — 키워드 매칭
        q_lower = question.lower()
        is_t2 = (
            any(k in q_lower for k in ALL_KEYWORDS)
            and condition_id
            and condition_id not in seen_ids
        )

        if not (is_t1 or is_t2):
            continue

        item = PolymarketItem(
            question=question,
            slug=m.get("slug", "") or "",
            yes_prob=yes_p,
            no_prob=no_p,
            volume_24h=volume_24h,
            liquidity=float(m.get("liquidity", 0) or 0),
            end_date=str(m.get("endDate", "") or ""),
            condition_id=condition_id,
            category=_categorize_v2(question),
            is_track1=is_t1,
        )
        seen_ids.add(condition_id)
        if is_t1:
            track1.append(item)
        else:
            track2.append(item)

    results = track1 + track2
    logger.info(
        f"[Polymarket] 수집 완료 "
        f"트랙1(TOP20)={len(track1)}개 "
        f"트랙2(키워드)={len(track2)}개 "
        f"합계={len(results)}개"
    )
    return results


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


# polymarket category → IntelCategory 매핑
_POLY_CAT_TO_INTEL = {
    "crypto":   "crypto_stream",
    "macro":    "macro_policy",
    "economy":  "macro_policy",
    "stocks":   "market_company",
    "politics": "us_policy_bills",
    "other":    "asset_context",
}


def upsert_to_intel(items: list[PolymarketItem]) -> int:
    """Polymarket 시장을 intel_items 테이블에 뉴스카드로 적재.

    - source = "polymarket"
    - source_type = "prediction_market"
    - category = _POLY_CAT_TO_INTEL 매핑
    - threshold 분기:
        * 트랙 1 (is_track1=True, 거래량 TOP 20) → 50점 이상 통과
        * 트랙 2 (키워드 매칭)                   → 55점 이상 통과
    - shortlisted = True (score ≥ 55 일 때만)
    - content_hash 기준 dedup.

    반환: 신규 적재 건수 (이미 존재하는 건은 priority_score 만 갱신).
    """
    import hashlib
    from datetime import datetime, timezone
    try:
        from app.db import get_db
        from app.models.intel import IntelItem
    except Exception as e:
        logger.warning(f"[Polymarket] intel 모듈 로드 실패: {e}")
        return 0

    inserted = 0
    updated = 0
    now_utc = datetime.now(timezone.utc)

    db = get_db()
    try:
        for item in items:
            score = _score_market(item)
            # threshold 분기 — track1 은 거래량 보장되어 관대
            threshold = 50 if item.is_track1 else 55
            if score < threshold:
                continue  # 낮은 건 dashboard 노출 안 함

            cond_id = item.condition_id or item.slug or item.question
            content_hash = hashlib.sha256(
                f"polymarket:{cond_id}".encode("utf-8")
            ).hexdigest()

            url = f"https://polymarket.com/event/{item.slug}" if item.slug else None
            yes_pct = round(item.yes_prob * 100)
            no_pct  = round(item.no_prob  * 100)
            title = f"[폴리마켓] {item.question[:120]}"
            summary = (
                f"Yes {yes_pct}% / No {no_pct}% · "
                f"24h 거래량 ${int(item.volume_24h):,} · "
                f"마감 {(item.end_date or '')[:10]}"
            )
            cat_intel = _POLY_CAT_TO_INTEL.get(item.category or "other", "asset_context")
            label = (
                "strong" if score >= 80
                else ("watch" if score >= 65 else "weak")
            )

            existing = (
                db.query(IntelItem)
                .filter(IntelItem.content_hash == content_hash)
                .first()
            )
            if existing is not None:
                # priority_score + 요약(Yes% 변동) 갱신만, 이력 유지
                existing.priority_score = score
                existing.score_label    = label
                existing.summary        = summary
                existing.shortlisted    = True
                updated += 1
                continue

            row = IntelItem(
                source="polymarket",
                source_type="prediction_market",
                title=title,
                summary=summary,
                url=url,
                published_at=now_utc,
                entity=None,
                category=cat_intel,
                content_hash=content_hash,
                raw_payload=None,
                shortlisted=True,
                flagged_reason=None,
                priority_score=score,
                score_label=label,
                why_flagged_human=(
                    f"폴리마켓 {item.category} 시장 · volume=${int(item.volume_24h):,} · "
                    f"yes={yes_pct}%"
                ),
                promotion_status="none",
            )
            try:
                db.add(row)
                db.flush()
                inserted += 1
            except Exception as e:
                db.rollback()
                logger.debug(f"[Polymarket] intel insert skip: {e}")
                continue
        db.commit()
        logger.info(
            f"[Polymarket] intel_items 적재 new={inserted} updated={updated}"
        )
        return inserted
    except Exception as e:
        logger.warning(f"[Polymarket] upsert_to_intel 실패: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass
