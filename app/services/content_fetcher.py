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

GitHub 파일 링크:
  github.com/.../blob/{branch}/path → 로컬 파일 직접 읽기 → GPT 등에 공유
"""

import re
from pathlib import Path
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

    Returns:
        {
            "title": str,
            "text": str,
            "url": str,
            "source": "direct"|"jina"|"google_cache"|"failed",
            "error": str | None,
        }
    """
    logger.info(f"URL 수집 시작: {url[:80]}")

    # 전략 1: 직접 요청
    result = await _fetch_direct(url)
    if result:
        return result

    # 전략 2: Jina AI Reader
    logger.info(f"Jina AI Reader로 재시도: {url[:60]}")
    result = await _fetch_jina(url)
    if result:
        return result

    # 전략 3: Google Cache
    logger.info(f"Google Cache로 재시도: {url[:60]}")
    result = await _fetch_google_cache(url)
    if result:
        return result

    # 모두 실패
    logger.warning(f"URL 수집 전략 모두 실패: {url[:80]}")
    return {
        "title": url,
        "text": "",
        "url": url,
        "source": "failed",
        "error": "모든 수집 전략 실패 (직접 접근 / Jina / Google Cache). 기사 텍스트를 직접 붙여넣어 주세요.",
    }


# =============================================================================
# GitHub 파일 링크 → 로컬 파일 읽기
# =============================================================================

# 프로젝트 루트 (봇이 실행되는 VPS와 동일한 경로)
_REPO_ROOT = Path("/home/user/x-posting-system")

# 지원하는 GitHub 도메인 (github.com + 로컬 Gitea)
_GITHUB_BLOB_RE = re.compile(
    r"https?://(?:github\.com|127\.0\.0\.1[:\d]*/git)/[^/]+/[^/]+/blob/([^/]+)/(.+)"
)


def is_github_file_url(url: str) -> bool:
    """github.com/.../blob/... 형식의 파일 URL인지 확인."""
    return bool(_GITHUB_BLOB_RE.search(url))


def github_url_to_local_path(url: str) -> Path | None:
    """
    GitHub blob URL을 로컬 파일 경로로 변환.

    예)
      https://github.com/kluck77/x-posting-system/blob/main/app/config.py
      → /home/user/x-posting-system/app/config.py
    """
    m = _GITHUB_BLOB_RE.search(url)
    if not m:
        return None
    # branch = m.group(1)  (사용 안 함, 로컬 파일은 현재 체크아웃 기준)
    rel_path = m.group(2).lstrip("/")
    return _REPO_ROOT / rel_path


def read_github_file(url: str) -> dict:
    """
    GitHub 파일 URL → 로컬 파일 내용 읽기.

    Returns:
        {
            "path": str,           # 상대 경로
            "content": str,        # 파일 내용
            "language": str,       # 확장자 기반 언어 (py/ts/md 등)
            "line_count": int,
            "error": str | None,
        }
    """
    local_path = github_url_to_local_path(url)
    if local_path is None:
        return {"path": url, "content": "", "language": "", "line_count": 0,
                "error": "GitHub blob URL 파싱 실패"}

    if not local_path.exists():
        return {"path": str(local_path), "content": "", "language": "", "line_count": 0,
                "error": f"파일 없음: {local_path.relative_to(_REPO_ROOT)}"}

    try:
        content = local_path.read_text(encoding="utf-8")
        ext = local_path.suffix.lstrip(".")
        lang_map = {
            "py": "python", "ts": "typescript", "tsx": "typescript",
            "js": "javascript", "json": "json", "md": "markdown",
            "yaml": "yaml", "yml": "yaml", "sh": "bash", "toml": "toml",
        }
        language = lang_map.get(ext, ext or "text")
        rel = str(local_path.relative_to(_REPO_ROOT))
        line_count = content.count("\n") + 1
        logger.info(f"[GitHub 파일 읽기] {rel} ({line_count}줄)")
        return {
            "path": rel,
            "content": content,
            "language": language,
            "line_count": line_count,
            "error": None,
        }
    except Exception as e:
        return {"path": str(local_path), "content": "", "language": "", "line_count": 0,
                "error": str(e)[:200]}


def split_code_for_telegram(path: str, content: str, language: str) -> list[str]:
    """
    긴 파일을 Telegram 4096자 제한에 맞게 분할.
    각 파트는 독립적으로 코드블록으로 감싸짐.

    Returns:
        list[str] — Telegram에 순서대로 전송할 메시지들
    """
    LIMIT = 3800  # 헤더/코드블록 마크업 여유분 포함

    header = f"📄 <b>{path}</b>\n"
    lines = content.splitlines(keepends=True)
    parts: list[str] = []
    chunk_lines: list[str] = []
    chunk_len = 0

    for line in lines:
        if chunk_len + len(line) > LIMIT and chunk_lines:
            chunk = "".join(chunk_lines)
            part_num = len(parts) + 1
            parts.append(
                f"{header}{'(파트 ' + str(part_num) + ')' if part_num > 1 else ''}\n"
                f"<pre><code class=\"language-{language}\">{_esc(chunk)}</code></pre>"
            )
            chunk_lines = [line]
            chunk_len = len(line)
        else:
            chunk_lines.append(line)
            chunk_len += len(line)

    if chunk_lines:
        chunk = "".join(chunk_lines)
        part_num = len(parts) + 1
        parts.append(
            f"{header}{'(파트 ' + str(part_num) + ')' if part_num > 1 else ''}\n"
            f"<pre><code class=\"language-{language}\">{_esc(chunk)}</code></pre>"
        )

    return parts


def _esc(text: str) -> str:
    """HTML 특수문자 이스케이프 (<pre> 내부용)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
