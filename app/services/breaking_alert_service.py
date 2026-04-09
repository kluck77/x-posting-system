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
from datetime import datetime, timedelta, timezone
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
# 카드 포맷 상수 (TELEGRAM_BREAKING_ALERT_TEMPLATE.md §3 / §4 / §5)
# ---------------------------------------------------------------------------
# §4 길이 제한
_CARD_MAX_CHARS: int = 600              # 카드 전체 권장 상한
_TITLE_MAX_CHARS: int = 60              # 제목 상한
_SUMMARY_MAX_CHARS: int = 200           # 핵심 요지 상한 (1~2문장 기준 대략치)
_SUMMARY_MAX_SENTENCES: int = 2         # 핵심 요지 문장 수 상한
_KEYWORDS_MAX: int = 3                  # 키워드 최대 3개 (§3)

# §6 예시에서 추출한 시각 포맷 (수집 시각 부가 정보)
_KST = timezone(timedelta(hours=9))

# 한/영 문장 종결부호 뒤 공백 기준 분할 (숫자 내부 `.` 는 공백 없어서 분할 안 됨)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.。!?])\s+")

# ---------------------------------------------------------------------------
# Dedup 상수 (TELEGRAM_DEDUP_DATA_MODEL_SPEC §8)
# ---------------------------------------------------------------------------
# BREAKING_NOW 기본 윈도우 : 6시간
BREAKING_DEDUP_WINDOW_SECONDS: int = 6 * 60 * 60

# 프로세스 내 dedup 저장소 : issue_key → 마지막 발행 epoch seconds
# 인메모리 1차 + DB write-through 영속화. 시작 시 DB→메모리 복원.
_dedup_store: dict[str, float] = {}
_dedup_lock = Lock()
_dedup_loaded_from_db = False


def _get_api_url(method: str) -> str:
    return f"{_TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


# ---------------------------------------------------------------------------
# 카드 포맷 헬퍼 (TELEGRAM_BREAKING_ALERT_TEMPLATE.md §3 / §4 / §5)
# ---------------------------------------------------------------------------
# §4 "이모지 금지" → 본 모듈은 어떤 헬퍼도 이모지를 생성하지 않는다.
# §4 "단정적 투자 조언 금지" → 운영자 액션 힌트는 문서 §3 지정 3종 + 짧은 보충만.

def _operator_action_hint(urgency: Optional[str]) -> str:
    """
    §3 필드 8 : `즉시 확인` / `정보만` / `추가 검증 필요` + 짧은 보충.
    §6 예시 문장을 그대로 고정 템플릿으로 사용한다 (매수/매도 추천 표현 없음).
    """
    if urgency == "high":
        return "즉시 확인. 코멘트 작성 검토 권장."
    if urgency == "medium":
        return "정보만. 후속 확인 권장."
    return "추가 검증 필요."


def _clip_title(title: str) -> str:
    """§4 : 제목 60자 이하. 잘릴 경우 끝에 `…` 추가."""
    t = (title or "-").strip() or "-"
    if len(t) <= _TITLE_MAX_CHARS:
        return t
    return t[: _TITLE_MAX_CHARS - 1].rstrip() + "…"


def _extract_summary(body: Optional[str], fallback_title: str) -> str:
    """
    §3 필드 2 : 핵심 요지 1~2문장.

    - body 가 주어지면 선두 최대 2문장 추출
    - body 가 없거나 파싱 실패 시 fallback_title (제목) 을 요지 자리로 재활용
      (§4 "보수가 기본값" — 요약을 지어내지 않는다).
    """
    if body:
        text = body.strip()
        if text:
            sents = _SENTENCE_SPLIT_RE.split(text)
            picked = " ".join(s.strip() for s in sents[:_SUMMARY_MAX_SENTENCES] if s.strip())
            if not picked:
                picked = text
            if len(picked) > _SUMMARY_MAX_CHARS:
                picked = picked[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"
            return picked
    # body 없음 → 제목으로 대체 (중복 느낌이지만 body 부재 신호 역할)
    return fallback_title[:_SUMMARY_MAX_CHARS]


def _format_keywords(matched_keywords: Optional[list[str]]) -> str:
    """§3 필드 3 : 강한 키워드 최대 3개, 슬래시 구분."""
    if not matched_keywords:
        return "-"
    top = [k.strip() for k in matched_keywords[:_KEYWORDS_MAX] if k and k.strip()]
    return " / ".join(top) if top else "-"


def _format_asset_groups(topic_domain: Optional[str]) -> str:
    """
    §3 필드 4 : 금융 / 투자 / 크립토 / 주식.
    현재 classifier 는 단일 primary_domain 만 반환 → 단일값 그대로 사용.
    복수 도메인 지원은 본 세션 범위 밖.
    """
    if not topic_domain or topic_domain == "none":
        return "-"
    return topic_domain


def _format_urgency(urgency: Optional[str]) -> str:
    """§3 필드 5 : high 또는 medium. (§4 소문자 유지)"""
    if urgency in ("high", "medium"):
        return urgency
    return "-"


def _format_reason(breaking_reason: Optional[str]) -> str:
    """§3 필드 6 : 왜 BREAKING_NOW 인지 1줄."""
    if not breaking_reason:
        return "-"
    r = breaking_reason.strip().replace("\n", " ")
    return r or "-"


def _format_collected_at(collected_at: Optional[datetime]) -> str:
    """§3 부가 정보 `수집 시각` : `YYYY-MM-DD HH:MM KST`."""
    dt = collected_at or datetime.now(tz=_KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    else:
        dt = dt.astimezone(_KST)
    return dt.strftime("%Y-%m-%d %H:%M KST")


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
    _load_dedup_from_db()
    with _dedup_lock:
        last = _dedup_store.get(issue_key)
    if last is None:
        return False
    return (now - last) < BREAKING_DEDUP_WINDOW_SECONDS


def _record_sent(issue_key: str, now: float) -> None:
    """전송 성공 시에만 호출. 차단 경로에서는 기록하지 않는다."""
    with _dedup_lock:
        _dedup_store[issue_key] = now
    _persist_dedup_to_db(issue_key, now)


def _reset_dedup_store_for_tests() -> None:
    """테스트 전용. 운영 코드에서 호출 금지."""
    global _dedup_loaded_from_db
    with _dedup_lock:
        _dedup_store.clear()
    _dedup_loaded_from_db = False


def _persist_dedup_to_db(issue_key: str, sent_at: float) -> None:
    """DB write-through (fail-open)."""
    try:
        from app.db import get_db
        from app.models.dedup import BreakingDedupEntry
        db = get_db()
        try:
            db.add(BreakingDedupEntry(issue_key=issue_key, sent_at=sent_at))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("[dedup] DB persist 실패 (fail-open)")


def _load_dedup_from_db() -> None:
    """시작 시 DB → 메모리 복원. 6h 윈도우 내 항목만 로드."""
    global _dedup_loaded_from_db
    if _dedup_loaded_from_db:
        return
    try:
        from app.db import get_db
        from app.models.dedup import BreakingDedupEntry
        cutoff = time.time() - BREAKING_DEDUP_WINDOW_SECONDS
        db = get_db()
        try:
            rows = db.query(BreakingDedupEntry).filter(
                BreakingDedupEntry.sent_at > cutoff
            ).all()
            with _dedup_lock:
                for row in rows:
                    existing = _dedup_store.get(row.issue_key)
                    if existing is None or row.sent_at > existing:
                        _dedup_store[row.issue_key] = row.sent_at
            logger.info(f"[dedup] DB 로드 완료: {len(rows)}건 (6h 윈도우)")
        finally:
            db.close()
    except Exception:
        logger.debug("[dedup] DB 로드 실패 (fail-open, 인메모리만 사용)")
    _dedup_loaded_from_db = True


def build_breaking_alert_text(
    *,
    breaking_result: "ClassificationResult",
    title: str,
    url: Optional[str],
    body: Optional[str] = None,
    collected_at: Optional[datetime] = None,
) -> str:
    """
    BREAKING_NOW 텔레그램 카드 본문.

    docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md §3 (8필드 고정) / §4 (문장 규칙) /
    §5 (복붙 템플릿) 기준.

    8필드 순서 고정, 이모지 금지, 한국어 only, 600자 상한. approval card
    (telegram_service.py) 와는 의도적으로 분리되어 있다.

    Args:
        breaking_result: classify_article 결과.
        title: 원문 제목 (§3 필드 1).
        url: 원문 링크 (§3 필드 7). None 이면 "원문" 라인 생략 (§10.2 참조).
        body: 원문 본문. 선두 최대 2문장을 핵심 요지로 사용 (§3 필드 2).
              None 이면 제목을 요지 자리에 대체.
        collected_at: 수집 시각. None 이면 호출 시점 KST 를 사용.
    """
    clipped_title = _clip_title(title)
    summary = _extract_summary(body, fallback_title=clipped_title)
    keywords = _format_keywords(breaking_result.matched_keywords)
    asset_groups = _format_asset_groups(breaking_result.topic_domain)
    urgency_str = _format_urgency(breaking_result.urgency)
    reason = _format_reason(breaking_result.breaking_reason)
    action_hint = _operator_action_hint(breaking_result.urgency)
    collected_str = _format_collected_at(collected_at)

    # §5 복붙 템플릿 순서 고정
    lines = [
        f"[속보] {clipped_title}",
        "",
        f"핵심 : {summary}",
        f"키워드 : {keywords}",
        f"영향 자산군 : {asset_groups}",
        f"긴급도 : {urgency_str}",
        f"분류 사유 : {reason}",
        f"운영자 액션 : {action_hint}",
    ]
    if url:
        lines.append("")
        lines.append(f"원문 : {url}")
    lines.append(f"시각 : {collected_str}")

    text = "\n".join(lines)
    # §4 600자 상한 — 초과 시 끝부분만 잘라 잘림 방지. 제목/요지는 이미 내부 clip.
    if len(text) > _CARD_MAX_CHARS:
        text = text[: _CARD_MAX_CHARS - 1].rstrip() + "…"
    return text


async def send_breaking_alert(
    *,
    breaking_result: "ClassificationResult",
    title: str,
    url: Optional[str] = None,
    body: Optional[str] = None,
    collected_at: Optional[datetime] = None,
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
        body: 원문 본문. build_breaking_alert_text 로 전달되어 핵심 요지 추출에 사용.
        collected_at: 수집 시각 KST. None 이면 호출 시점.
        now: 현재 epoch seconds (테스트에서 dedup 시간 주입용, 기본 time.time()).

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
        body=body,
        collected_at=collected_at,
    )

    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] BREAKING alert:\n{text}")
        if issue_key is not None:
            _record_sent(issue_key, now_ts)
        return True

    # §4 "이모지 금지" + 한국어 전용 plain text → parse_mode 미지정.
    # (HTML 파서는 `<`, `>`, `&` 가 섞인 기사 텍스트에서 parse 실패할 수 있다.)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
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
