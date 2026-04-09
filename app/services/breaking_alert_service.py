"""
BREAKING ALERT SERVICE (P1 stage-3, S3-C + S3-A)
================================================
BREAKING_NOW 분류 결과를 텔레그램으로 알리는 최소 핸드오프 경로.

본 모듈은 기존 approval card (telegram_service.py / build_approval_card /
send_approval_card) 흐름과 **의도적으로 완전히 분리된 경로** 다.
approval flow 의 의미를 변경하지 않기 위해 telegram_service.py 의 함수를
재사용하지 않는다 (RUNNER_RULES §5 영구 보호 영역 유지).

S3-C 범위 (직전 세션)
- payload 최소 : title / classification / topic_domain / matched_keywords /
                 breaking_reason / urgency / url (운영자 지시 7개 필드)
- 호출 측 fail-open 전제 : 텔레그램 실패 시 False 반환, 예외 전파 금지

S3-A 범위 (본 세션, dedup 최소 연결)
- 같은 issue_key 가 dedup window (6h, §8) 내 이미 발행됐으면 차단
- dedup 저장소 : 프로세스 내 dict (DB / 외부 저장소 / 캐시 서버 금지)
- title_normalized : docs/TELEGRAM_DEDUP_DATA_MODEL_SPEC.md §6 최소 구현
- issue_key        : §7.1 형식 최소 구현 (entity_slug 자동추출 없음, unknown 고정)
- dedup 계산 자체 실패 시 fail-open (전송 진행)
- 전송 성공 시에만 issue_last_published 기록 (차단 경로에서는 저장 안 함)

참고
- docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md         — 카드 포맷 기준
- docs/TELEGRAM_DEDUP_DATA_MODEL_SPEC.md §6/§7/§8  — 본 세션 dedup 규격
- docs/ACCOUNT_CONSTITUTION.md §1.2                — 4개 도메인 한정
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from threading import Lock
from typing import TYPE_CHECKING, Optional

import httpx

from app.config import settings

if TYPE_CHECKING:
    from app.services.breaking_classifier import ClassificationResult

logger = logging.getLogger(__name__)

# 텔레그램 Bot API 기본 URL (telegram_service.py 와 동일 포맷, 재사용 금지하여 별도 정의)
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"

# ---------------------------------------------------------------------------
# Dedup 상수 (TELEGRAM_DEDUP_DATA_MODEL_SPEC §8)
# ---------------------------------------------------------------------------
# BREAKING_NOW 기본 윈도우 : 6시간
BREAKING_DEDUP_WINDOW_SECONDS: int = 6 * 60 * 60

# 프로세스 내 dedup 저장소 : issue_key → 마지막 발행 epoch seconds
# 단일 프로세스 MVP. 재시작 시 초기화됨. DB / 외부 캐시 없음 (운영자 명시).
_dedup_store: dict[str, float] = {}
_dedup_lock = Lock()


def _get_api_url(method: str) -> str:
    return f"{_TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


def _urgency_emoji(urgency: Optional[str]) -> str:
    if urgency == "high":
        return "🚨"
    if urgency == "medium":
        return "⚠️"
    return "🔔"


# ---------------------------------------------------------------------------
# title_normalized / issue_key (TELEGRAM_DEDUP_DATA_MODEL_SPEC §6, §7)
# ---------------------------------------------------------------------------
# §6 최소 구현 : NFKC / strip / 선행 브래킷 태그 제거 / 언론사 꼬리 제거 /
#                구두점 제거 / 이모지 제거 / lowercase / 공백 정규화
_BRACKET_TAG_RE = re.compile(r"^(?:\[[^\]]*\]|\([^)]*\))+\s*")
_PUBLISHER_TAIL_RE = re.compile(r"\s+[-|]\s+[^-|]+$")
_PUNCT_RE = re.compile(r"[「」『』\"'“”‘’.,!?…·~\-—()\[\]{}<>／/]")
_WHITESPACE_RE = re.compile(r"\s+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000027BF"
    "]"
)

# §7.1 coarse_bucket : ACCOUNT_CONSTITUTION 4개 도메인 → spec 의 6개 버킷 매핑
_DOMAIN_TO_BUCKET: dict[str, str] = {
    "크립토": "crypto",
    "주식": "stock",
    "금융": "macro",
    "투자": "macro",
    "none": "other",
}


def normalize_title(title: str) -> str:
    """
    TELEGRAM_DEDUP_DATA_MODEL_SPEC §6 최소 구현.
    결정적(deterministic) : 같은 입력 → 항상 같은 출력.
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title).strip()
    # 선행 브래킷 태그 반복 제거 ([속보][단독] 같은 케이스 포함)
    while True:
        nt = _BRACKET_TAG_RE.sub("", t)
        if nt == t:
            break
        t = nt
    # 언론사 꼬리 제거 (뒤쪽 한 번만)
    t = _PUBLISHER_TAIL_RE.sub("", t)
    # 구두점 / 이모지 / lowercase
    t = _PUNCT_RE.sub(" ", t)
    t = _EMOJI_RE.sub("", t)
    t = t.lower()
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return t


def _coarse_bucket(topic_domain: str) -> str:
    return _DOMAIN_TO_BUCKET.get(topic_domain, "other")


def compute_issue_key(*, title: str, topic_domain: str) -> str:
    """
    TELEGRAM_DEDUP_DATA_MODEL_SPEC §7.1 최소 구현 :
        <coarse_bucket>:<entity_slug>:<topic_slug>:<hash8>

    MVP 범위 제약
    - 자동 엔티티 추출 없음 → entity_slug = "unknown" 고정 (§7.3 fallback 과 유사)
    - topic_slug = 정규화 제목 앞 3토큰 join
    - hash8 = SHA-256(title_normalized + bucket) 앞 8자 (§7.1)

    참고 : §7.3 은 fallback 시 card_status=hold 를 요구하지만, 본 모듈은 1단계
    dedup 게이트 MVP 이므로 hold 전이 시맨틱을 적용하지 않는다. 운영자는 차단
    여부만 판단한다.
    """
    bucket = _coarse_bucket(topic_domain)
    normalized = normalize_title(title)
    if not normalized:
        # 정규화 결과 빈 문자열 → 고유 키 반환 (같은 시점에도 충돌 없도록).
        # dedup 을 우회해 전송이 발생하지만, 운영자 입장에서 문제 인지 가능.
        salt = hashlib.sha256(
            f"{bucket}|empty|{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:8]
        return f"{bucket}:unknown:empty:{salt}"
    tokens = normalized.split(" ")[:3]
    topic_slug = "-".join(tokens) if tokens else "empty"
    h = hashlib.sha256(f"{normalized}|{bucket}".encode("utf-8")).hexdigest()[:8]
    return f"{bucket}:unknown:{topic_slug}:{h}"


# ---------------------------------------------------------------------------
# Dedup 저장소 조작 (프로세스 내 dict + Lock)
# ---------------------------------------------------------------------------
def _is_duplicate_within_window(issue_key: str, now: float) -> bool:
    """True = dedup 차단 / False = 통과. 단순 마지막발행시각 비교."""
    with _dedup_lock:
        last = _dedup_store.get(issue_key)
    if last is None:
        return False
    return (now - last) < BREAKING_DEDUP_WINDOW_SECONDS


def _record_sent(issue_key: str, now: float) -> None:
    """전송 성공 시에만 호출. 차단 경로에서는 기록하지 않는다."""
    with _dedup_lock:
        _dedup_store[issue_key] = now


def _reset_dedup_store_for_tests() -> None:
    """테스트 전용. 운영 코드에서 호출 금지."""
    with _dedup_lock:
        _dedup_store.clear()


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
    now: Optional[float] = None,
) -> bool:
    """
    BREAKING_NOW 알림 핸드오프.

    - classification != BREAKING_NOW 이면 즉시 False 반환 (호출 측 안전망)
    - dedup window (6h, §8) 내 같은 issue_key 재발생 시 전송 생략하고 False 반환
    - dedup 계산 자체 실패 시 fail-open : 경고만 남기고 전송 진행
    - 텔레그램 설정 없으면 MOCK 로그 후 True 반환
    - httpx 예외는 내부에서 삼키고 False 반환 (fail-open)
    - 전송 성공 시에만 dedup 저장소에 기록 (차단 경로 / 전송 실패 경로에서는 기록 안 함)

    Args:
        now: 현재 epoch seconds (테스트에서 시간 주입용, 기본 time.time()).

    Returns:
        전송 성공 여부 (True/False). MOCK 모드도 True 로 간주.
    """
    if breaking_result.classification != "BREAKING_NOW":
        logger.warning(
            f"[breaking-alert] classification != BREAKING_NOW "
            f"({breaking_result.classification}), 호출 무시"
        )
        return False

    # Dedup 게이트 (fail-open: 계산/조회 실패 시 전송 진행)
    issue_key: Optional[str] = None
    now_ts: float = now if now is not None else time.time()
    try:
        issue_key = compute_issue_key(
            title=title,
            topic_domain=breaking_result.topic_domain,
        )
        if _is_duplicate_within_window(issue_key, now_ts):
            logger.info(
                f"[breaking-alert] dedup blocked issue_key={issue_key} "
                f"(window {BREAKING_DEDUP_WINDOW_SECONDS}s)"
            )
            return False
    except Exception as e:
        logger.warning(
            f"[breaking-alert] dedup 계산 실패 (fail-open, 전송 진행): {e}"
        )
        issue_key = None

    text = build_breaking_alert_text(
        breaking_result=breaking_result,
        title=title,
        url=url,
    )

    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] BREAKING alert:\n{text}")
        if issue_key is not None:
            _record_sent(issue_key, now_ts)
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
                if issue_key is not None:
                    _record_sent(issue_key, now_ts)
                return True
            logger.error(f"[breaking-alert] 텔레그램 API 오류: {result}")
            return False
    except httpx.HTTPError as e:
        logger.error(f"[breaking-alert] 전송 실패 (fail-open): {e}")
        return False
