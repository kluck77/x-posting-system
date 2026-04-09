"""
BREAKING ALERT SERVICE (P1 stage-3, S3-C)
==========================================
BREAKING_NOW 분류 결과를 텔레그램으로 알리는 최소 핸드오프 경로.

본 모듈은 기존 approval card (telegram_service.py / build_approval_card /
send_approval_card) 흐름과 **의도적으로 완전히 분리된 경로** 다.
approval flow 의 의미를 변경하지 않기 위해 telegram_service.py 의 함수를
재사용하지 않는다 (RUNNER_RULES §5 영구 보호 영역 유지).

1단계 범위 (이번 세션)
- payload 최소 : title / classification / topic_domain / matched_keywords /
                 breaking_reason / urgency / url (운영자 지시 7개 필드)
- 호출 측 fail-open 전제 : 텔레그램 실패 시 False 반환, 예외 전파 금지
- DB 저장 / dedup / 버튼 / 승인 플로우 / Top5 / 대시보드 일체 없음
- BREAKING_NOW 가 아닌 classification 은 즉시 False 반환 (호출 측 안전망)

참고
- docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md — 카드 포맷 기준 (단순화본)
- docs/ACCOUNT_CONSTITUTION.md §1.2 — 4개 도메인 한정
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import httpx

from app.config import settings

if TYPE_CHECKING:
    from app.services.breaking_classifier import ClassificationResult

logger = logging.getLogger(__name__)

# 텔레그램 Bot API 기본 URL (telegram_service.py 와 동일 포맷, 재사용 금지하여 별도 정의)
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _get_api_url(method: str) -> str:
    return f"{_TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


def _urgency_emoji(urgency: Optional[str]) -> str:
    if urgency == "high":
        return "🚨"
    if urgency == "medium":
        return "⚠️"
    return "🔔"


def build_breaking_alert_text(
    *,
    breaking_result: "ClassificationResult",
    title: str,
    url: Optional[str],
) -> str:
    """
    BREAKING_NOW 알림용 최소 페이로드 텍스트.

    기존 approval card 와 의도적으로 다른 포맷이며, 버튼/승인 없이 순수
    알림 전용이다. 운영자 지시 7개 필드를 모두 포함한다.
    """
    em = _urgency_emoji(breaking_result.urgency)
    kws = ", ".join(breaking_result.matched_keywords[:5]) or "-"
    reason = breaking_result.breaking_reason or "-"
    urgency_label = (breaking_result.urgency or "-").upper()

    lines = [
        f"{em} <b>BREAKING ALERT</b>",
        "─" * 30,
        f"📰 <b>Title:</b> {title}",
        f"🏷️ <b>Classification:</b> {breaking_result.classification}",
        f"📂 <b>Topic:</b> {breaking_result.topic_domain}",
        f"🔑 <b>Keywords:</b> {kws}",
        f"💥 <b>Reason:</b> {reason}",
        f"⚡ <b>Urgency:</b> {urgency_label}",
    ]
    if url:
        lines.append(f"🔗 <b>Source:</b> {url}")
    return "\n".join(lines)


async def send_breaking_alert(
    *,
    breaking_result: "ClassificationResult",
    title: str,
    url: Optional[str] = None,
) -> bool:
    """
    BREAKING_NOW 알림 핸드오프.

    - classification != BREAKING_NOW 이면 즉시 False 반환 (호출 측 안전망)
    - 텔레그램 설정 없으면 MOCK 로그 후 True 반환
    - httpx 예외는 내부에서 삼키고 False 반환 (fail-open)

    Returns:
        전송 성공 여부 (True/False). MOCK 모드도 True 로 간주.
    """
    if breaking_result.classification != "BREAKING_NOW":
        logger.warning(
            f"[breaking-alert] classification != BREAKING_NOW "
            f"({breaking_result.classification}), 호출 무시"
        )
        return False

    text = build_breaking_alert_text(
        breaking_result=breaking_result,
        title=title,
        url=url,
    )

    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] BREAKING alert:\n{text}")
        return True

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _get_api_url("sendMessage"),
                data=payload,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(
                    f"[breaking-alert] 전송 성공 "
                    f"urgency={breaking_result.urgency or '-'} "
                    f"domain={breaking_result.topic_domain}"
                )
                return True
            logger.error(f"[breaking-alert] 텔레그램 API 오류: {result}")
            return False
    except httpx.HTTPError as e:
        logger.error(f"[breaking-alert] 전송 실패 (fail-open): {e}")
        return False
