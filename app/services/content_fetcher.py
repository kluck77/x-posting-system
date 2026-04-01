"""
콘텐츠 수집기
=============
URL에서 뉴스 기사 텍스트를 추출합니다.
텔레그램 봇에서 사용자가 보낸 링크를 자동으로 처리합니다.
"""

import re
import logging
import httpx
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# 뉴스 기사 제외 태그 (본문과 관계없는 영역)
_SKIP_TAGS = frozenset(["script", "style", "nav", "header", "footer",
                         "aside", "noscript", "form", "iframe", "svg"])


class _TextExtractor(HTMLParser):
    """HTML에서 본문 텍스트만 추출하는 간단한 파서."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip: int = 0  # skip-tag 중첩 카운터

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
    """
    X/Twitter URL에서 트윗 ID를 추출합니다.
    예) https://x.com/user/status/1234567890 → "1234567890"
    """
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else None


def is_x_url(url: str) -> bool:
    """X(Twitter) URL인지 확인합니다."""
    return bool(re.search(r"(x\.com|twitter\.com)/", url))


async def fetch_url_content(url: str) -> dict:
    """
    URL에서 기사 제목과 본문 텍스트를 가져옵니다.

    Returns:
        {
            "title": str,
            "text": str,
            "url": str,
            "error": str | None,
        }
    """
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; XPostingBot/1.0; "
                    "+https://github.com/kluck77/x-posting-system)"
                )
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        # 제목 추출
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        raw_title = title_match.group(1).strip() if title_match else url
        # HTML 엔티티 기본 처리
        raw_title = re.sub(r"<[^>]+>", "", raw_title)
        title = raw_title[:300]

        # 본문 텍스트 추출
        extractor = _TextExtractor()
        extractor.feed(html)
        raw_text = extractor.get_text()
        # 공백 정리 후 3000자 제한
        text = " ".join(raw_text.split())[:3000]

        logger.info(f"URL 수집 완료: '{title[:60]}' ({len(text)}자)")
        return {"title": title, "text": text, "url": url, "error": None}

    except httpx.HTTPStatusError as e:
        err = f"HTTP 오류 {e.response.status_code}"
        logger.warning(f"URL 수집 실패 ({url}): {err}")
        return {"title": url, "text": "", "url": url, "error": err}
    except Exception as e:
        err = str(e)[:200]
        logger.warning(f"URL 수집 오류 ({url}): {err}")
        return {"title": url, "text": "", "url": url, "error": err}
