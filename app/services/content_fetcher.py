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

        # F3: 작성일 추출 (HTML meta + <time> 우선, 본문 패턴 fallback)
        published_at = _extract_published_at(html) or _extract_published_at(text)
        # F2: clean text 기준 cap 8000 (메타 prepend 는 _postprocess 뒤)
        clean_body = text[:8000]

        logger.info(
            f"[Strategy 1 ✓] Direct: '{title[:60]}' ({len(clean_body)}자) "
            f"published_at={published_at or '(unknown)'}"
        )
        return {
            "title": title,
            "text": clean_body,
            "url": url,
            "source": "direct",
            "published_at": published_at,
            "error": None,
        }

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

        # F4: 제목 추출 (Title: / # heading / 본문 안 헤딩)
        title = _extract_jina_title(raw, url)
        # F3: 작성일 추출 (못 찾으면 빈 문자열 — 추정 X)
        published_at = _extract_published_at(raw)
        # F1: 사이드바 잡문 제거 후 기사 본문 시작점부터 슬라이스
        article_only = _extract_article_body_from_jina(raw)
        # 메타 헤더 (URL/Title/Published/...) 정리
        clean_body = _clean_jina_text(article_only)
        # F2: clean text 기준으로 cap 적용 (8000) — 메타 prepend 는 _postprocess 뒤
        clean_body = clean_body[:8000]

        logger.info(
            f"[Strategy 2 ✓] Jina: '{title[:60]}' ({len(clean_body)}자) "
            f"published_at={published_at or '(unknown)'}"
        )
        return {
            "title": title,
            "text": clean_body,
            "url": url,
            "source": "jina",
            "published_at": published_at,
            "error": None,
        }

    except Exception as e:
        logger.debug(f"Jina fetch 실패: {e}")
        return None


def _extract_jina_title(text: str, fallback: str) -> str:
    """Jina 마크다운 응답에서 제목 추출.

    우선순위:
    1. "Title: ..." 메타 라인 (Jina 표준 헤더)
    2. 첫 # 헤딩
    3. 본문 안의 강한 heading (첫 50 줄 내, 글 본문 진입 직전)
    4. URL fallback
    """
    lines = text.splitlines()
    # 1+2: 첫 10 줄 안 표준 위치
    for line in lines[:10]:
        s = line.strip()
        if s.startswith("Title:"):
            return s.replace("Title:", "").strip()[:300]
        if s.startswith("# "):
            return s[2:].strip()[:300]
    # 3: 본문 안 어딘가의 첫 헤딩 (사이드바 메뉴 뒤에 헤딩이 올 때)
    for line in lines[:200]:
        s = line.strip()
        if s.startswith("# ") and len(s) > 5 and len(s) < 200:
            return s[2:].strip()[:300]
    return fallback[:300]


# 기사 본문 시작 신호 — 기자 + 날짜 / (소속=매체) / 기자명 단독 / Jina 메타
# 한국 매체 전반 적용 가능한 일반 패턴. 특정 매체 하드코딩 X.
_ARTICLE_START_PATTERNS = [
    # "박형기 기자 2026.04.29 오전 04:38" / "홍길동 기자\n2026-04-29"
    re.compile(
        r"[가-힣]{2,4}\s*기자\s*[\s\-·•|]*\s*"
        r"(?:20\d{2}[.\-]\d{1,2}[.\-]\d{1,2}|20\d{2}년)"
    ),
    # "(서울=뉴스1)" / "(로이터=뉴스1)" / "(워싱턴=AFP)"
    re.compile(r"\([\w가-힣]+\s*=\s*[\w가-힣]+\)"),
    # 날짜 + 시각 ("2026.04.29 오전 04:38" / "2026-04-29 04:38")
    re.compile(
        r"20\d{2}[.\-]\d{1,2}[.\-]\d{1,2}"
        r"(?:\s*(?:오전|오후|AM|PM)?\s*\d{1,2}:\d{2})"
    ),
]

# 작성일 추출 — 우선순위 별 패턴
_PUBLISHED_AT_PATTERNS = [
    # "2026.04.29 오전 04:38" / "2026-04-29 PM 04:38"
    re.compile(
        r"(20\d{2}[.\-]\d{1,2}[.\-]\d{1,2}"
        r"\s*(?:오전|오후|AM|PM)?\s*\d{1,2}:\d{2})"
    ),
    # "2026.04.29" / "2026-04-29" (시각 없이)
    re.compile(r"(20\d{2}[.\-]\d{1,2}[.\-]\d{1,2})"),
    # ISO 8601: "2026-04-29T04:38:00+09:00"
    re.compile(
        r"(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:[+\-]\d{2}:?\d{2}|Z)?)"
    ),
]


def _extract_published_at(text: str) -> str:
    """기사 본문 markdown/HTML 에서 작성일 추출.

    날짜를 못 찾으면 빈 문자열 반환 — 추정/현재 시각 대체 X.
    추출 우선순위 (HTML meta 는 _fetch_direct 의 _parse_html 에서 별도 처리):
    1. ISO 8601 datetime (article:published_time / datePublished)
    2. "YYYY.MM.DD 오전/오후 HH:MM" 형식
    3. "YYYY.MM.DD" / "YYYY-MM-DD" 형식 (보조)
    """
    # HTML meta 우선 (Jina 응답에는 거의 없지만 direct 에서 도움).
    # `<meta property="article:published_time" content="2026-04-29T04:38:00+09:00">`
    # 같은 형식 — property 이름 다음 임의 attr 사이를 lazy 로 건너뛴 뒤 ISO
    # 8601 datetime 캡처.
    iso_meta = re.search(
        r'(?:article:published_time|datePublished|og:published_time)'
        r'[^>]*?(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
        r'(?:[+\-]\d{2}:?\d{2}|Z)?)',
        text, re.IGNORECASE,
    )
    if iso_meta:
        return iso_meta.group(1).strip()
    # <time datetime="...">
    time_tag = re.search(
        r'<time[^>]+datetime=["\'](20\d{2}[^"\']+)["\']',
        text, re.IGNORECASE,
    )
    if time_tag:
        return time_tag.group(1).strip()
    # 본문 안 패턴 — 첫 N 줄 안에서만 (사이드바 광고 날짜 회피)
    head = "\n".join(text.splitlines()[:200])
    for pat in _PUBLISHED_AT_PATTERNS:
        m = pat.search(head)
        if m:
            return m.group(1).strip()
    return ""


def _extract_article_body_from_jina(text: str) -> str:
    """Jina 마크다운 응답에서 사이드바 잡문 제거 후 기사 본문만 추출.

    전략:
    1. 기사 시작 신호 (_ARTICLE_START_PATTERNS) 검색 — 가장 빠른 hit 위치 +
       그 이전 잡문 제거.
    2. 신호 없으면 첫 본격 # 헤딩부터 시작.
    3. 신호 없고 헤딩도 없으면 원문 그대로 반환 (fail-open).

    한국 매체 전반 일반 패턴. 특정 매체 하드코딩 X.
    """
    if not text:
        return text
    earliest = -1
    for pat in _ARTICLE_START_PATTERNS:
        m = pat.search(text)
        if m and (earliest == -1 or m.start() < earliest):
            earliest = m.start()
    if earliest > 0:
        # 신호 직전 줄바꿈으로 정렬 (단어 중간 자르지 않게)
        nl = text.rfind("\n", 0, earliest)
        cut = nl if nl != -1 else earliest
        return text[cut:].lstrip()
    # 신호 없으면 첫 # 헤딩부터 (단, 본문보다 사이드바 메뉴가 먼저 # 일 수
    # 있으니 너무 짧은 헤딩은 skip)
    for m in re.finditer(r"\n#\s+([^\n]{8,})", text):
        return text[m.start():].lstrip()
    return text


def _prepend_article_metadata(
    title: str, published_at: str, source: str, body: str,
) -> str:
    """body 앞에 기사 메타 prepend — title / 작성일 / 출처.

    downstream 모델이 시점·핵심 신호를 먼저 받게 한다.
    """
    parts: list[str] = []
    if title and not title.startswith("http"):
        parts.append(f"[기사 제목: {title[:200]}]")
    if published_at:
        parts.append(f"[기사 작성일: {published_at}]")
    if source:
        parts.append(f"[본문 출처: {source}]")
    if not parts:
        return body
    return "\n".join(parts) + "\n\n" + body


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

        published_at = _extract_published_at(html) or _extract_published_at(text)
        clean_body = text[:8000]

        logger.info(f"[Strategy 3 ✓] Google Cache: '{title[:60]}' ({len(clean_body)}자)")
        return {
            "title": title,
            "text": clean_body,
            "url": url,
            "source": "google_cache",
            "published_at": published_at,
            "error": None,
        }

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
        "published_at": "",
        "error": "모든 수집 전략 실패 (직접 접근 / Jina / Google Cache). 기사 텍스트를 직접 붙여넣어 주세요.",
        "low_quality": False,
    }


def _postprocess(result: dict) -> dict:
    """수집 결과에 UI 잡문 정제 + 기사 밀도 체크를 적용한다.

    F3: 정제 후 [기사 제목 / 작성일 / 출처] 메타 prepend → downstream 모델이
    시점·핵심 신호를 먼저 받도록. text_cleaner 가 메타를 strip 하지 않게
    cleaning 뒤에 prepend.
    """
    try:
        from app.services.text_cleaner import clean_article_text, is_article_like
        raw_text = result.get("text", "")
        cleaned = clean_article_text(raw_text)
        result["low_quality"] = not is_article_like(raw_text)
        # 메타 prepend (정제 뒤)
        merged = _prepend_article_metadata(
            result.get("title", "") or "",
            result.get("published_at", "") or "",
            result.get("source", "") or "",
            cleaned,
        )
        result["text"] = merged
        if result["low_quality"]:
            logger.info(
                f"[밀도 체크 ✗] 기사형 아님: '{result.get('title', '')[:50]}' "
                f"(정제 후 {len(cleaned)}자)"
            )
    except Exception as e:
        logger.debug(f"postprocess fail-open: {e}")
        result["low_quality"] = False
    return result
