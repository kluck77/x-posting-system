"""UTM 파라미터 빌더.

이메일/뉴스레터 경로의 모든 URL에 UTM 파라미터를 자동 삽입.
X 포스트 본문 URL은 건드리지 않음 (운영자 수동 게시 전제).
"""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from app.config import settings


def attach_utm(
    url: str,
    medium: str = "email",
    campaign: str = "",
    content: str = "",
) -> str:
    """URL에 UTM 파라미터 추가.

    Args:
        url: 원본 URL
        medium: utm_medium (email / twitter / telegram)
        campaign: utm_campaign (brief / series_kimchi 등)
        content: utm_content (날짜 또는 이슈 번호)

    Returns:
        UTM 파라미터가 붙은 URL
    """
    if not url or not url.startswith("http"):
        return url

    parsed = urlparse(url)
    params = {
        "utm_source": settings.utm_source_default or "sskorea02",
        "utm_medium": medium,
    }
    if campaign:
        params["utm_campaign"] = campaign
    elif settings.utm_campaign_default:
        params["utm_campaign"] = settings.utm_campaign_default
    if content:
        params["utm_content"] = content

    # 기존 query string 보존
    existing = parse_qs(parsed.query, keep_blank_values=True)
    existing.update({k: [v] for k, v in params.items()})
    new_query = urlencode({k: v[0] for k, v in existing.items()})

    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


def rewrite_urls_in_html(
    html: str,
    medium: str = "email",
    campaign: str = "",
) -> str:
    """HTML 본문 내 모든 href URL에 UTM 삽입."""
    def replace_href(match: re.Match) -> str:
        url = match.group(1)
        new_url = attach_utm(url, medium=medium, campaign=campaign)
        return f'href="{new_url}"'

    return re.sub(r'href="(https?://[^"]+)"', replace_href, html)
