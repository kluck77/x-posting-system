"""X 트렌딩 크립토 키워드 감지.

trends24.in 스크래핑 (15분 주기 캐시, robots.txt 준수).
실패/차단 시 빈 리스트 반환 (파이프라인 중단 없음).
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

CRYPTO_KEYWORDS = re.compile(
    r"\b(?:btc|eth|sol|xrp|bnb|도지|비트|이더|솔라나|코인"
    r"|업비트|빗썸|김프|온체인|스테이킹|디파이|nft"
    r"|etf|halving|반감기|altseason|알트시즌)\b",
    re.IGNORECASE,
)

TRENDS_URL = "https://trends24.in/south-korea/"
_ROBOTS_CACHE: dict[str, bool] = {}
_LAST_FETCH: float = 0.0
_CACHE_TTL = 900  # 15분
_TRENDING_CACHE: list[str] = []
_UA = "CryptoTrendBot/1.0 (+contact@sskorea02)"


async def _check_robots(url: str) -> bool:
    """robots.txt 허용 여부. 접근 실패 시 허용(fail-open)."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[robots_url]
    try:
        async with httpx.AsyncClient(timeout=5, headers={"User-Agent": _UA}) as client:
            resp = await client.get(robots_url)
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
        allowed = rp.can_fetch(_UA, url)
        _ROBOTS_CACHE[robots_url] = allowed
        return allowed
    except Exception:
        return True


async def get_trending_crypto() -> list[str]:
    """크립토 관련 트렌딩 키워드 반환. 캐시 15분."""
    global _LAST_FETCH, _TRENDING_CACHE

    if time.time() - _LAST_FETCH < _CACHE_TTL and _TRENDING_CACHE:
        return _TRENDING_CACHE

    if not await _check_robots(TRENDS_URL):
        logger.warning("[XTrending] robots.txt 차단")
        return []

    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": _UA}) as client:
            resp = await client.get(TRENDS_URL)
            resp.raise_for_status()

        # trends24 는 trend-card 내부 li 에 키워드 노출
        trend_pattern = re.compile(
            r"trend-card__list.*?<li>(.*?)</li>", re.DOTALL
        )
        raw_trends = trend_pattern.findall(resp.text)[:20]

        crypto_trends: list[str] = []
        for trend in raw_trends:
            clean = re.sub(r"<[^>]+>", "", trend).strip()
            if CRYPTO_KEYWORDS.search(clean):
                crypto_trends.append(clean)

        _TRENDING_CACHE = crypto_trends
        _LAST_FETCH = time.time()

        if crypto_trends:
            logger.info(
                f"[XTrending] 크립토 트렌딩 {len(crypto_trends)}개: "
                f"{crypto_trends[:3]}"
            )
        return crypto_trends
    except Exception as e:
        logger.warning(f"[XTrending] 수집 실패: {e}")
        return []
