"""
Naver 뉴스 검색 API
===================
Naver Open API를 사용해 키워드별 최신 뉴스를 검색합니다.
무료 한도: 일 25,000회

API 등록: https://developers.naver.com/apps/#/register
필요 권한: 뉴스 검색

설정:
  NAVER_CLIENT_ID=...
  NAVER_CLIENT_SECRET=...
"""

import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from app.config import settings
from app.services.rss_fetcher import RssArticle
from app.services.naver_usage import record_call

logger = logging.getLogger(__name__)

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"

# SEO 스팸 도메인 차단 — 가습기·맛집·레시피 블로그가 "코인 가상화폐" 검색에
# 키워드 스터핑으로 잡혀 들어오는 사례 다수. 정식 뉴스 도메인만 받는다.
_BLOCKED_URL_PATTERNS: tuple[str, ...] = (
    "blog.naver.com", "m.blog.naver.com",
    "cafe.naver.com", "m.cafe.naver.com",
    "post.naver.com",
    ".tistory.com", "brunch.co.kr",
    # coindeskkorea.com 은 과거 정식 크립토 매체였으나 2026 기준 SEO 팜으로 변질.
    # Naver "코인 가상화폐" 검색에서도 이 도메인이 잡히면 안 되므로 차단.
    "coindeskkorea.com",
)


def _is_blocked_url(url: str) -> bool:
    if not url:
        return True
    u = url.lower()
    return any(p in u for p in _BLOCKED_URL_PATTERNS)

# 탐지 키워드 — 한국 경제/정치/정책/크립토 속보 핵심어
SEARCH_KEYWORDS: list[dict] = [
    {"keyword": "환율 달러",   "category": "economy"},
    {"keyword": "금리 한국은행", "category": "economy"},
    {"keyword": "코인 가상화폐", "category": "crypto"},
    {"keyword": "국회 법안",    "category": "politics"},
    {"keyword": "대통령 경제",  "category": "policy"},
]


# ─── 라이브 상태 트래킹 ───────────────────────────────────────────────────────
# 대시보드에서 "네이버 지금 돌고 있나?" 실시간 확인용.
# 순수 관측만 — search 로직 자체는 건드리지 않는다.
_live_lock = threading.Lock()
_live_state: dict = {
    "last_cycle_at": None,      # ISO UTC string (Z suffix)
    "last_cycle_items": 0,
    "last_cycle_ms": 0,
    "cycles_total": 0,
    "items_total": 0,
    "cycle_history": deque(maxlen=120),  # (epoch_ts, items) — 최근 2시간치
    "per_keyword": {
        # keyword: {hits_total, last_hit_at, last_fetch_at, last_fetch_items, hit_history: deque}
    },
    "recent_items": deque(maxlen=30),    # {title, keyword, category, url, fetched_at}
}


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_keyword_fetch(keyword: str, items: list["RssArticle"]) -> None:
    """search_keyword() 성공 시 호출. 키워드별 적중 기록 + 최근 아이템 링버퍼."""
    now_iso = _now_iso_utc()
    now_ts = time.time()
    with _live_lock:
        per = _live_state["per_keyword"].setdefault(keyword, {
            "hits_total": 0,
            "last_hit_at": None,
            "last_fetch_at": None,
            "last_fetch_items": 0,
            "hit_history": deque(maxlen=120),  # (epoch_ts, items)
        })
        per["last_fetch_at"] = now_iso
        per["last_fetch_items"] = len(items)
        per["hit_history"].append((now_ts, len(items)))
        if items:
            per["hits_total"] += len(items)
            per["last_hit_at"] = now_iso
            # 최근 아이템 스트림에 추가 (키워드 상관없이 전역 타임라인)
            for a in items[:3]:  # 키워드당 최대 3건만 담아서 타임라인 오염 방지
                _live_state["recent_items"].append({
                    "title": a.title,
                    "keyword": keyword,
                    "category": a.category,
                    "url": a.url,
                    "fetched_at": now_iso,
                })


def _record_cycle(total_items: int, duration_ms: int) -> None:
    """search_all_keywords() 한 사이클 끝날 때마다 호출."""
    now_iso = _now_iso_utc()
    now_ts = time.time()
    with _live_lock:
        _live_state["last_cycle_at"] = now_iso
        _live_state["last_cycle_items"] = total_items
        _live_state["last_cycle_ms"] = duration_ms
        _live_state["cycles_total"] += 1
        _live_state["items_total"] += total_items
        _live_state["cycle_history"].append((now_ts, total_items))


def get_live_status() -> dict:
    """대시보드용 네이버 라이브 상태 스냅샷."""
    now_ts = time.time()
    with _live_lock:
        last_at = _live_state["last_cycle_at"]
        # 최근 60분 집계
        cutoff_60 = now_ts - 3600
        cycles_60m = sum(1 for ts, _ in _live_state["cycle_history"] if ts >= cutoff_60)
        items_60m = sum(n for ts, n in _live_state["cycle_history"] if ts >= cutoff_60)

        # seconds_since_last 계산
        seconds_since = None
        if last_at:
            try:
                dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
                seconds_since = int((datetime.now(timezone.utc) - dt).total_seconds())
            except Exception:
                seconds_since = None

        # 상태 레벨
        if seconds_since is None:
            status = "dead"
        elif seconds_since < 180:
            status = "live"
        elif seconds_since < 900:
            status = "idle"
        elif seconds_since < 3600:
            status = "stale"
        else:
            status = "dead"

        # 키워드별 60분 집계
        per_keyword = []
        for spec in SEARCH_KEYWORDS:
            kw = spec["keyword"]
            p = _live_state["per_keyword"].get(kw, {})
            hist = p.get("hit_history", [])
            hits_60m = sum(n for ts, n in hist if ts >= cutoff_60)
            per_keyword.append({
                "keyword": kw,
                "category": spec["category"],
                "hits_total": p.get("hits_total", 0),
                "hits_60m": hits_60m,
                "last_hit_at": p.get("last_hit_at"),
                "last_fetch_at": p.get("last_fetch_at"),
                "last_fetch_items": p.get("last_fetch_items", 0),
            })

        recent = list(_live_state["recent_items"])
        recent.reverse()  # 최신순

        return {
            "status": status,
            "last_cycle_at": last_at,
            "seconds_since_last": seconds_since,
            "last_cycle_items": _live_state["last_cycle_items"],
            "last_cycle_ms": _live_state["last_cycle_ms"],
            "cycles_60m": cycles_60m,
            "items_60m": items_60m,
            "cycles_total": _live_state["cycles_total"],
            "items_total": _live_state["items_total"],
            "per_keyword": per_keyword,
            "recent_items": recent[:20],
            "configured": bool(settings.naver_client_id and settings.naver_client_secret),
        }


class _HtmlStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip(text: str) -> str:
    if not text:
        return ""
    try:
        s = _HtmlStripper()
        s.feed(text)
        return s.get_text()[:300]
    except Exception:
        return re.sub(r"<[^>]+>", "", text)[:300]


async def search_keyword(keyword: str, category: str, display: int = 5) -> list[RssArticle]:
    """
    단일 키워드로 Naver 뉴스를 검색합니다.

    Args:
        keyword: 검색어
        category: 카테고리 (economy / politics / crypto 등)
        display: 결과 수 (최대 100)

    Returns:
        RssArticle 목록
    """
    if not (settings.naver_client_id and settings.naver_client_secret):
        return []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NAVER_API_URL,
                headers={
                    "X-Naver-Client-Id":     settings.naver_client_id,
                    "X-Naver-Client-Secret": settings.naver_client_secret,
                },
                params={
                    "query":   keyword,
                    "display": display,
                    "sort":    "date",   # 최신순
                },
            )
            resp.raise_for_status()
            data = resp.json()
            record_call(1)

        articles = []
        blocked = 0
        for item in data.get("items", []):
            title  = _strip(item.get("title", ""))
            url    = item.get("originallink") or item.get("link", "")
            summary = _strip(item.get("description", ""))
            if not title or not url:
                continue
            if _is_blocked_url(url):
                blocked += 1
                continue
            articles.append(RssArticle(
                title=title[:300],
                url=url.strip(),
                summary=summary,
                category=category,
                source=f"Naver/{keyword}",
            ))
        if blocked:
            logger.debug(f"Naver '{keyword}': SEO 도메인 {blocked}건 제외")
        _record_keyword_fetch(keyword, articles)
        return articles

    except Exception as e:
        logger.warning(f"Naver API 오류 ('{keyword}'): {e}")
        _record_keyword_fetch(keyword, [])
        return []


async def search_all_keywords() -> list[RssArticle]:
    """모든 키워드를 병렬 검색합니다."""
    import asyncio

    if not (settings.naver_client_id and settings.naver_client_secret):
        logger.debug("Naver API 키 없음 — 건너뜁니다")
        return []

    t0 = time.time()
    tasks = [
        search_keyword(k["keyword"], k["category"])
        for k in SEARCH_KEYWORDS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[RssArticle] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
    duration_ms = int((time.time() - t0) * 1000)
    _record_cycle(len(articles), duration_ms)
    logger.info(f"Naver 검색 완료: {len(articles)}개 기사 ({duration_ms}ms)")
    return articles
