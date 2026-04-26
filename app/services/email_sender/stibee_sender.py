"""Stibee 뉴스레터 연동.

newsletter_routine_service.export_newsletter() 결과를
Stibee API 로 발송.

Stibee API v2:
  POST https://api.stibee.com/v2/lists/{list_id}/subscribers
  POST https://api.stibee.com/v2/letters (캠페인 발송)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

STIBEE_BASE_URL = "https://api.stibee.com/v2"


async def add_subscriber(email: str, name: str = "") -> bool:
    """Stibee 리스트에 구독자 추가.

    Returns:
        True = 성공, False = 실패 (파이프라인 중단 없음)
    """
    if not settings.stibee_api_key or not settings.stibee_list_id:
        logger.warning("[Stibee] API 키 또는 리스트 ID 없음 — skip")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{STIBEE_BASE_URL}/lists/{settings.stibee_list_id}/subscribers",
                headers={
                    "AccessToken": settings.stibee_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "subscribers": [
                        {
                            "email": email,
                            "name": name,
                        }
                    ],
                    "eventOccuredBy": "MANUAL",
                    "confirmEmailYN": "Y",
                },
            )
            resp.raise_for_status()
            logger.info(f"[Stibee] 구독자 추가 성공: {email}")
            return True
    except Exception as e:
        logger.warning(f"[Stibee] 구독자 추가 실패 (무시): {e}")
        return False


async def send_newsletter(
    subject: str,
    html_content: str,
    preview_text: str = "",
) -> bool:
    """Stibee 뉴스레터 발송.

    Returns:
        True = 성공, False = 실패
    """
    if not settings.stibee_api_key or not settings.stibee_list_id:
        logger.warning("[Stibee] API 키 또는 리스트 ID 없음 — skip")
        return False

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{STIBEE_BASE_URL}/letters",
                headers={
                    "AccessToken": settings.stibee_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "listId": settings.stibee_list_id,
                    "subject": subject,
                    "previewText": preview_text,
                    "contents": html_content,
                    "senderName": "@sskorea02",
                    "senderEmail": settings.stibee_sender_email or "",
                },
            )
            resp.raise_for_status()
            logger.info(f"[Stibee] 뉴스레터 발송 성공: {subject}")
            return True
    except Exception as e:
        logger.warning(f"[Stibee] 뉴스레터 발송 실패 (무시): {e}")
        return False


def format_newsletter_html(items: list[dict[str, Any]]) -> str:
    """뉴스레터 export 결과를 HTML로 변환."""
    rows = ""
    for item in items:
        title = item.get("title", "")
        body = item.get("body", "")
        url = item.get("url", "")
        rows += (
            f"<h3>{title}</h3>"
            f"<p>{body}</p>"
            f'{"<p><a href=" + url + ">원문 보기</a></p>" if url else ""}'
            f"<hr>"
        )
    return f"""
<html><body>
<h2>@sskorea02 주간 브리프</h2>
{rows}
<p style="font-size:12px;color:#888;">
수신 거부: <a href="{{unsubscribe_url}}">여기를 클릭</a>
</p>
</body></html>
"""
