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
from html.parser import HTMLParser

import httpx

from app.config import settings
from app.services.rss_fetcher import RssArticle

logger = logging.getLogger(__name__)

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"

# 탐지 키워드 — 한국 경제/정치/정책/크립토 속보 핵심어
SEARCH_KEYWORDS: list[dict] = [
    {"keyword": "환율 달러",   "category": "economy"},
    {"keyword": "금리 한국은행", "category": "economy"},
    {"keyword": "코인 가상화폐", "category": "crypto"},
    {"keyword": "국회 법안",    "category": "politics"},
    {"keyword": "대통령 경제",  "category": "policy"},
]


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

        articles = []
        for item in data.get("items", []):
            title  = _strip(item.get("title", ""))
            url    = item.get("originallink") or item.get("link", "")
            summary = _strip(item.get("description", ""))
            if not title or not url:
                continue
            articles.append(RssArticle(
                title=title[:300],
                url=url.strip(),
                summary=summary,
                category=category,
                source=f"Naver/{keyword}",
            ))
        return articles

    except Exception as e:
        logger.warning(f"Naver API 오류 ('{keyword}'): {e}")
        return []


async def search_all_keywords() -> list[RssArticle]:
    """모든 키워드를 병렬 검색합니다."""
    import asyncio

    if not (settings.naver_client_id and settings.naver_client_secret):
        logger.debug("Naver API 키 없음 — 건너뜁니다")
        return []

    tasks = [
        search_keyword(k["keyword"], k["category"])
        for k in SEARCH_KEYWORDS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[RssArticle] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
    logger.info(f"Naver 검색 완료: {len(articles)}개 기사")
    return articles
