"""Affiliate 링크 레지스트리.

data/affiliate_links.json 에서 파트너 링크를 로드하고,
뉴스레터/이메일 본문에 삽입할 CTA 블록을 생성.

X 포스트 본문에는 삽입하지 않음.
affiliate_enabled=False 이면 완전 비활성.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_links() -> dict[str, Any]:
    """affiliate_links.json 로드. 실패 시 빈 dict."""
    path = settings.affiliate_links_path or "data/affiliate_links.json"
    if not os.path.exists(path):
        logger.warning(f"[Affiliate] 링크 파일 없음: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Affiliate] 링크 파일 로드 실패: {e}")
        return {}


def get_cta_block(category: str = "crypto") -> str:
    """카테고리에 맞는 Affiliate CTA 블록 반환.

    Returns:
        HTML CTA 블록 (없으면 빈 문자열)
    """
    if not settings.affiliate_enabled:
        return ""

    links = _load_links()
    partners = links.get(category, links.get("default", []))
    if not partners:
        return ""

    blocks = []
    for p in partners[:2]:  # 최대 2개
        name = p.get("name", "")
        url = p.get("url", "")
        desc = p.get("desc", "")
        if not url:
            continue
        blocks.append(
            f'<p>📎 <a href="{url}">{name}</a> — {desc}</p>'
        )

    if not blocks:
        return ""

    return (
        "<hr>"
        "<p><small>파트너 서비스</small></p>"
        + "\n".join(blocks)
    )


def inject_into_newsletter(html: str, category: str = "crypto") -> str:
    """뉴스레터 HTML에 Affiliate CTA 블록 삽입."""
    cta = get_cta_block(category)
    if not cta:
        return html
    # unsubscribe 링크 바로 앞에 삽입
    return html.replace("<p style=\"font-size:12px", cta + "\n<p style=\"font-size:12px")
