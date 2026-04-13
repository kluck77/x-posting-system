"""
콘텐츠 수집기
=============
URL에서 뉴스 기사 텍스트를 추출합니다.
텔레그램 봇에서 사용자가 보낸 링크를 자동으로 처리합니다.

수집 전략 (순서대로 fallback):
  1. Direct fetch — 실제 브라우저 헤더로 직접 요청
  2. Jina AI Reader (r.jina.ai) — JS 렌더링, 페이월 일부 우회, API 키 불필요
  3. Google Cache — 오래된 기사 복구

403/404/빈 콘텐츠 시 자동으로 다음 전략 시도.
"""

import re
import logging
import httpx
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# 뉴스 기사 제외 태그 (본문과 관계없는 영역)
_SKIP_TAGS = frozenset(["script", "style", "nav", "header", "footer",
                         "aside", "noscript", "form", "iframe", "svg"])

# 실제 브라우저처럼 보이는 헤더
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class _TextExtractor(HTMLParser):
    """HTML에서 본문 텍스트만 추출하는 간단한 파서."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip: int = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts)


def is_url(text: str) -> bool:
    """텍스트가 URL인지 확인합니다."""
    return bool(re.match(r"https?://\S+", text.strip()))


def extract_tweet_id(url: str) -> str | None:
    """X/Twitter URL에서 트윗 ID를 추출합니다."""
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else None


def is_x_url(url: str) -> bool:
    """X(Twitter) URL인지 확인합니다."""
    return bool(re.search(r"(x\.com|twitter\.com)/", url))


# =============================================================================
# 전략 1: Direct fetch
# =============================================================================

async def _fetch_direct(url: str) -> dict | None:
    """
    실제 브라우저 헤더로 직접 요청.
    200 응답 + 충분한 텍스트(200자+) 시 반환, 아니면 None.
    """
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
        ) as client:
            resp = await client.get(url)
            if resp.status_code in (403, 404, 429, 451):
                logger.debug(f"Direct fetch 차단: {resp.status_code} {url[:60]}")
                return None
            resp.raise_for_status()
            html = resp.text

        title, text = _parse_html(html, url)
        if len(text) < 200:
            logger.debug(f"Direct fetch 콘텐츠 부족 ({len(text)}자): {url[:60]}")
            return None

        logger.info(f"[Strategy 1 ✓] Direct: '{title[:60]}' ({len(text)}자)")
        return {"title": title, "text": text[:4000], "url": url,
                "source": "direct", "error": None}

    except Exception as e:
        logger.debug(f"Direct fetch 실패: {e}")
        return None


# =============================================================================
# 전략 2: Jina AI Reader (r.jina.ai)
# =============================================================================

async def _fetch_jina(url: str) -> dict | None:
    """
    Jina AI Reader를 통해 콘텐츠 수집.
    API 키 불필요. JS 렌더링, 페이월 일부 우회.
    반환: 마크다운 형식의 깨끗한 텍스트.
    """
    jina_url = f"https://r.jina.ai/{url}"
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "Accept": "text/plain, text/markdown",
                "X-Timeout": "20",
                "X-Return-Format": "text",
            },
        ) as client:
            resp = await client.get(jina_url)
            if resp.status_code in (400, 404, 422, 429, 500, 503):
                logger.debug(f"Jina 실패: {resp.status_code} {url[:60]}")
                return None
            resp.raise_for_status()
            raw = resp.text.strip()

        if len(raw) < 200:
            logger.debug(f"Jina 콘텐츠 부족 ({len(raw)}자): {url[:60]}")
            return None

        # Jina 응답에서 제목 추출 (첫 번째 # 헤딩 또는 Title: 라인)
        title = _extract_jina_title(raw, url)
        # 마크다운 헤딩/메타 라인 정리
        text = _clean_jina_text(raw)

        logger.info(f"[Strategy 2 ✓] Jina: '{title[:60]}' ({len(text)}자)")
        return {"title": title, "text": text[:4000], "url": url,
                "source": "jina", "error": None}

    except Exception as e:
        logger.debug(f"Jina fetch 실패: {e}")
        return None


def _extract_jina_title(text: str, fallback: str) -> str:
    """Jina 마크다운 응답에서 제목 추출."""
    for line in text.splitlines()[:10]:
        line = line.strip()
        if line.startswith("Title:"):
            return line.replace("Title:", "").strip()[:300]
        if line.startswith("# "):
            return line[2:].strip()[:300]
    return fallback[:300]


def _clean_jina_text(text: str) -> str:
    """Jina 메타 헤더(URL/Title/Published 등) 제거 후 본문만 반환."""
    lines = text.splitlines()
    body_lines = []
    meta_done = False
    meta_pattern = re.compile(
        r"^(URL:|Title:|Published|Author:|Source:|Description:|Markdown Content:)",
        re.IGNORECASE,
    )
    for line in lines:
        if not meta_done:
            if meta_pattern.match(line.strip()):
                continue
            if line.strip() == "" and not body_lines:
                continue
            meta_done = True
        body_lines.append(line)
    return " ".join(" ".join(body_lines).split())


# =============================================================================
# 전략 3: Google Cache
# =============================================================================

async def _fetch_google_cache(url: str) -> dict | None:
    """
    Google 캐시를 통해 수집 (최후 수단).
    최근 기사에는 캐시가 없을 수 있음.
    """
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
        ) as client:
            resp = await client.get(cache_url)
            if resp.status_code != 200:
                return None
            html = resp.text

        title, text = _parse_html(html, url)
        if len(text) < 200:
            return None

        logger.info(f"[Strategy 3 ✓] Google Cache: '{title[:60]}' ({len(text)}자)")
        return {"title": title, "text": text[:4000], "url": url,
                "source": "google_cache", "error": None}

    except Exception as e:
        logger.debug(f"Google Cache 실패: {e}")
        return None


# =============================================================================
# HTML 파서 공통 유틸
# =============================================================================

def _parse_html(html: str, url: str) -> tuple[str, str]:
    """HTML에서 (제목, 본문텍스트) 추출."""
    # OG title > title 태그 순으로 추출
    og_title = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        html, re.IGNORECASE,
    )
    if og_title:
        title = og_title.group(1).strip()[:300]
    else:
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        raw_title = title_match.group(1).strip() if title_match else url
        title = re.sub(r"<[^>]+>", "", raw_title)[:300]

    extractor = _TextExtractor()
    extractor.feed(html)
    raw_text = extractor.get_text()
    text = " ".join(raw_text.split())
    return title, text


# =============================================================================
# 메인 진입점
# =============================================================================

async def fetch_url_content(url: str) -> dict:
    """
    URL에서 기사 제목과 본문 텍스트를 가져옵니다.
    3단계 fallback 전략으로 404/403 자동 우회.
    수집 후 UI 잡문 정제 + 기사 밀도 체크까지 수행.

    Returns:
        {
            "title": str,
            "text": str,           # 정제된 텍스트
            "url": str,
            "source": "direct"|"jina"|"google_cache"|"failed",
            "error": str | None,
            "low_quality": bool,   # True → 앱/랜딩/허브 페이지 (기사 아님)
        }
    """
    logger.info(f"URL 수집 시작: {url[:80]}")

    # 전략 1: 직접 요청
    result = await _fetch_direct(url)
    if result:
        return _postprocess(result)

    # 전략 2: Jina AI Reader
    logger.info(f"Jina AI Reader로 재시도: {url[:60]}")
    result = await _fetch_jina(url)
    if result:
        return _postprocess(result)

    # 전략 3: Google Cache
    logger.info(f"Google Cache로 재시도: {url[:60]}")
    result = await _fetch_google_cache(url)
    if result:
        return _postprocess(result)

    # 모두 실패
    logger.warning(f"URL 수집 전략 모두 실패: {url[:80]}")
    return {
        "title": url,
        "text": "",
        "url": url,
        "source": "failed",
        "error": "모든 수집 전략 실패 (직접 접근 / Jina / Google Cache). 기사 텍스트를 직접 붙여넣어 주세요.",
        "low_quality": False,
    }


def _postprocess(result: dict) -> dict:
    """수집 결과에 UI 잡문 정제 + 기사 밀도 체크를 적용한다."""
    try:
        from app.services.text_cleaner import clean_article_text, is_article_like
        raw_text = result.get("text", "")
        cleaned = clean_article_text(raw_text)
        result["text"] = cleaned
        result["low_quality"] = not is_article_like(raw_text)
        if result["low_quality"]:
            logger.info(
                f"[밀도 체크 ✗] 기사형 아님: '{result.get('title', '')[:50]}' "
                f"(정제 후 {len(cleaned)}자)"
            )
    except Exception as e:
        logger.debug(f"postprocess fail-open: {e}")
        result["low_quality"] = False
    return result
