"""한국 커뮤니티 트렌딩 감지.

디시인사이드 코인 갤러리 + 코인판 등.
- robots.txt 준수 (fail-open)
- 15분 주기 캐시
- 초당 1req 이하 (source 별 delay)
- 제목+시간만 수집. 본문·로그인·조회수 DB 저장 금지.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

CRYPTO_KEYWORDS = re.compile(
    r"\b(?:btc|eth|sol|xrp|비트|이더|솔라나|코인|업비트"
    r"|빗썸|김프|온체인|스테이킹|디파이|nft|etf|반감기"
    r"|알트|선물|레버리지|롱|숏|청산|펀딩|고래)\b",
    re.IGNORECASE,
)

SOURCES = [
    {
        "name":  "dcinside_coin",
        "url":   "https://gall.dcinside.com/board/lists/?id=bitcoins",
        "title_pattern": re.compile(r'class="ub-word"[^>]*>([^<]+)<'),
        "delay": 2.0,
    },
    {
        "name":  "coinpan",
        "url":   "https://coinpan.com/free",
        "title_pattern": re.compile(
            r'<a[^>]+class="[^"]*subject[^"]*"[^>]*>([^<]+)<'
        ),
        "delay": 2.0,
    },
]

_ROBOTS_CACHE: dict[str, RobotFileParser | None] = {}
_CACHE: dict[str, dict] = {}   # name → {trending, ts}
_CACHE_TTL = 900               # 15분
_UA = "CryptoTrendBot/1.0 (+contact@sskorea02)"


async def _check_robots(base_url: str, path: str) -> bool:
    """robots.txt 허용 여부. 접근 실패 시 허용 (fail-open)."""
    robots_url = f"{base_url}/robots.txt"
    if robots_url not in _ROBOTS_CACHE:
        try:
            async with httpx.AsyncClient(timeout=5, headers={"User-Agent": _UA}) as client:
                resp = await client.get(robots_url)
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            _ROBOTS_CACHE[robots_url] = rp
        except Exception:
            _ROBOTS_CACHE[robots_url] = None
    rp = _ROBOTS_CACHE.get(robots_url)
    if rp is None:
        return True
    return rp.can_fetch(_UA, f"{base_url}{path}")


async def _fetch_source(source: dict) -> list[str]:
    parsed = urlparse(source["url"])
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    if not await _check_robots(base_url, parsed.path):
        logger.info(f"[KorComm] robots.txt 차단: {source['name']}")
        return []

    try:
        await asyncio.sleep(source.get("delay", 1.0))
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": _UA}) as client:
            resp = await client.get(source["url"])
            resp.raise_for_status()
        titles = source["title_pattern"].findall(resp.text)[:30]
        crypto_titles = [
            t.strip() for t in titles if CRYPTO_KEYWORDS.search(t)
        ]
        return crypto_titles
    except Exception as e:
        logger.warning(f"[KorComm] {source['name']} 수집 실패: {e}")
        return []


async def get_trending() -> dict[str, list[str]]:
    """캐시 우선, 만료 시 각 source 순차 수집."""
    now = time.time()
    results: dict[str, list[str]] = {}

    for source in SOURCES:
        cached = _CACHE.get(source["name"])
        if cached and now - cached["ts"] < _CACHE_TTL:
            results[source["name"]] = cached["trending"]
            continue

        trending = await _fetch_source(source)
        _CACHE[source["name"]] = {"trending": trending, "ts": now}
        results[source["name"]] = trending
        if trending:
            logger.info(
                f"[KorComm] {source['name']}: {len(trending)}개 → {trending[:2]}"
            )
    return results


def get_all_trending_keywords() -> list[str]:
    """캐시된 모든 소스의 트렌딩 키워드 (dedup, 최대 10개)."""
    all_kw: list[str] = []
    for cached in _CACHE.values():
        all_kw.extend(cached.get("trending", []))
    return list(dict.fromkeys(all_kw))[:10]
