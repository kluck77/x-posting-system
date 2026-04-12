"""
RSS 피드 파서
=============
한국 뉴스 RSS 피드를 파싱하고 신규 기사를 반환합니다.
feedparser 대신 표준 라이브러리 xml.etree.ElementTree 사용 (의존성 최소화).

지원 피드:
  - 경제: 한국경제, 매일경제
  - 정치/정책: 연합뉴스
  - 크립토: 코인데스크코리아
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)

# ─── 피드 목록 ────────────────────────────────────────────────────────────────

RSS_FEEDS: list[dict] = [
    # ── 한국 뉴스 ─────────────────────────────────────────────────────────────
    {"url": "https://www.hankyung.com/feed/economy",              "category": "economy",  "source": "한국경제",        "region": "KR"},
    {"url": "https://www.mk.co.kr/rss/30000001/",                  "category": "economy",  "source": "매일경제",        "region": "KR"},
    {"url": "https://www.yna.co.kr/rss/politics.xml",             "category": "politics", "source": "연합뉴스",        "region": "KR"},
    {"url": "https://www.yna.co.kr/rss/economy.xml",              "category": "economy",  "source": "연합뉴스",        "region": "KR"},
    {"url": "https://www.coindeskkorea.com/feed/",                "category": "crypto",   "source": "코인데스크코리아", "region": "KR"},
    # ── 미국/글로벌 뉴스 ──────────────────────────────────────────────────────
    {"url": "https://apnews.com/feed",                             "category": "politics", "source": "AP News",        "region": "US"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",     "category": "economy",  "source": "BBC Business",   "region": "US"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html","category": "economy", "source": "CNBC",           "region": "US"},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/","category": "economy", "source": "MarketWatch",    "region": "US"},
    {"url": "https://decrypt.co/feed",                            "category": "crypto",   "source": "Decrypt",        "region": "US"},
]


# ─── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class RssArticle:
    title: str
    url: str
    summary: str
    category: str
    source: str
    region: str = "KR"  # KR / US / GLOBAL
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── HTML 스트립 ──────────────────────────────────────────────────────────────

class _HtmlStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(text: str) -> str:
    if not text:
        return ""
    try:
        s = _HtmlStripper()
        s.feed(text)
        return s.get_text()[:500]
    except Exception:
        return re.sub(r"<[^>]+>", "", text)[:500]


# ─── RSS 파서 ─────────────────────────────────────────────────────────────────

# RSS/Atom 네임스페이스
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc":   "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _text(el, *tags: str) -> str:
    """여러 태그 경로 중 첫 번째로 찾은 값 반환."""
    for tag in tags:
        try:
            found = el.find(tag, _NS)
            if found is not None and found.text:
                return found.text.strip()
        except Exception:
            pass
    return ""


def _parse_feed(xml_text: str, category: str, source: str) -> list[RssArticle]:
    """RSS/Atom XML 문자열에서 기사 목록 파싱."""
    articles: list[RssArticle] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"RSS XML 파싱 오류 ({source}): {e}")
        return articles

    # RSS 2.0
    items = root.findall(".//item")
    # Atom
    if not items:
        items = root.findall(".//atom:entry", _NS) or root.findall(".//entry")

    for item in items[:20]:  # 최근 20개만
        title = _strip_html(_text(item, "title", "atom:title"))
        url   = (_text(item, "link", "atom:link", "guid")
                 or _text(item, "atom:id"))
        # Atom <link href="...">
        if not url:
            link_el = item.find("atom:link", _NS) or item.find("link")
            if link_el is not None:
                url = link_el.get("href", "")
        summary = _strip_html(
            _text(item, "description", "atom:summary",
                  "content:encoded", "atom:content")
        )

        if not title or not url:
            continue
        url = url.strip()
        if not url.startswith("http"):
            continue

        articles.append(RssArticle(
            title=title[:300],
            url=url,
            summary=summary,
            category=category,
            source=source,
        ))

    return articles


# ─── 메인 퍼블릭 API ──────────────────────────────────────────────────────────

async def fetch_feed(feed: dict) -> list[RssArticle]:
    """단일 RSS 피드를 가져와 파싱합니다."""
    url      = feed["url"]
    category = feed["category"]
    source   = feed["source"]
    region   = feed.get("region", "KR")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; KoNewsBot/1.0)"},
            )
            resp.raise_for_status()
            articles = _parse_feed(resp.text, category, source)
            for a in articles:
                a.region = region
            return articles
    except Exception as e:
        logger.warning(f"피드 가져오기 실패 ({source} / {url}): {e}")
        return []


async def fetch_all_feeds() -> list[RssArticle]:
    """모든 RSS 피드를 병렬로 가져옵니다."""
    import asyncio
    tasks = [fetch_feed(f) for f in RSS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[RssArticle] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
    logger.info(f"RSS 수집 완료: 총 {len(articles)}개 기사")
    return articles


def filter_new_articles(
    articles: list[RssArticle],
    seen_urls: set[str],
) -> list[RssArticle]:
    """
    이미 처리한 URL을 제외하고 신규 기사만 반환합니다.
    seen_urls는 호출 측에서 관리합니다.
    """
    new = [a for a in articles if a.url not in seen_urls]
    logger.info(f"신규 기사: {len(new)}개 (전체 {len(articles)}개 중)")
    return new
