"""
DAYTIME CANDIDATE ALERT SERVICE
================================
05:00~22:00 KST 시간대에 고점수 CANDIDATE 기사를 즉시 텔레그램으로 알림.

기존 Top5 큐 적재와 충돌 없이 동작한다.
- CANDIDATE 는 Top5 큐에 그대로 적재 (기존 흐름 유지)
- 추가로 아래 조건을 모두 만족하면 즉시 알림 발송 (본 모듈)

조건 (모두 만족해야 함):
  a. 현재 시각 05:00~22:00 KST (주간)
  b. matched_keywords >= 4 (강한 키워드 신호 4개 이상)
  c. score >= DAYTIME_SCORE_THRESHOLD (점수 컷라인)
  d. 수집 후 2시간 이내 (즉시성)

설계 원칙:
- 기존 BREAKING 라인 / Top5 라인 / approval flow 무간섭
- fail-open : 어디서든 실패하면 로그만 남기고 파이프라인 계속
- DB 스키마 변경 금지
- 외부 패키지 추가 금지 (stdlib + httpx 만 사용)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# 주간 시간대 + 조건 상수
# ---------------------------------------------------------------------------
_DAY_START_HOUR = 5    # 05:00 KST
_DAY_END_HOUR = 22     # 22:00 KST

DAYTIME_SCORE_THRESHOLD = 55       # 점수 컷라인 (주간 freshness=0 감안)
DAYTIME_MIN_KEYWORDS = 4           # 강한 키워드 신호 최소 매칭 수
DAYTIME_FRESHNESS_HOURS = 2        # 즉시성: 수집 후 N시간 이내


# ---------------------------------------------------------------------------
# 조건 판정
# ---------------------------------------------------------------------------
def _is_daytime_kst(*, now: Optional[datetime] = None) -> bool:
    """현재 시각이 05:00~22:00 KST 범위 안인지 확인."""
    now_kst = (now or datetime.now(tz=_KST))
    if now_kst.tzinfo is None:
        now_kst = now_kst.replace(tzinfo=_KST)
    else:
        now_kst = now_kst.astimezone(_KST)
    return _DAY_START_HOUR <= now_kst.hour < _DAY_END_HOUR


def _is_fresh(
    collected_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    max_hours: int = DAYTIME_FRESHNESS_HOURS,
) -> bool:
    """수집 시각이 현재 기준 N시간 이내인지 확인."""
    if collected_at is None:
        return True  # 수집 시각 미상이면 통과 (fail-open)
    ref = now or datetime.now(tz=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    diff = ref - collected_at
    return diff <= timedelta(hours=max_hours)


def should_send_daytime_alert(
    *,
    matched_keywords: list[str],
    score: float,
    collected_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    """
    주간 즉시 알림 조건 판정.

    모두 만족해야 True:
      a. 현재 05:00~22:00 KST
      b. matched_keywords >= 4 (강한 키워드 신호 4개 이상)
      c. score >= DAYTIME_SCORE_THRESHOLD
      d. 수집 후 2시간 이내 (즉시성)
    """
    if not _is_daytime_kst(now=now):
        return False
    if len(matched_keywords) < DAYTIME_MIN_KEYWORDS:
        return False
    if score < DAYTIME_SCORE_THRESHOLD:
        return False
    if not _is_fresh(collected_at, now=now):
        return False
    return True


# ---------------------------------------------------------------------------
# 카드 텍스트 (BREAKING_NOW 8필드와 구분되는 경량 형식)
# ---------------------------------------------------------------------------
_TITLE_MAX = 60
_SUMMARY_MAX = 200
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.。!?])\s+")


def build_daytime_alert_text(
    *,
    title: str,
    body: Optional[str],
    url: Optional[str],
    topic_domain: str,
    matched_keywords: list[str],
    score: float,
    collected_at: Optional[datetime] = None,
) -> str:
    """주간 고점수 CANDIDATE 알림 카드 텍스트."""
    # 제목 클립
    t = title.strip() or "-"
    title_clipped = t if len(t) <= _TITLE_MAX else t[: _TITLE_MAX - 1] + "\u2026"

    # 핵심 요지 (본문 선두 2문장)
    summary = title_clipped
    if body and body.strip():
        sents = _SENTENCE_SPLIT_RE.split(body.strip())
        picked = " ".join(s.strip() for s in sents[:2] if s.strip())
        if picked:
            summary = picked if len(picked) <= _SUMMARY_MAX else picked[: _SUMMARY_MAX - 1] + "\u2026"

    # 키워드 (최대 3개)
    kw_str = " / ".join(matched_keywords[:3]) if matched_keywords else "-"

    # 수집 시각
    dt = collected_at or datetime.now(tz=_KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    else:
        dt = dt.astimezone(_KST)
    time_str = dt.strftime("%Y-%m-%d %H:%M KST")

    lines = [
        f"[주간 주목] {title_clipped}",
        "",
        f"핵심 : {summary}",
        f"키워드 : {kw_str}",
        f"영향 자산군 : {topic_domain}",
        f"점수 : {int(score)}/100",
    ]
    if url:
        lines.append("")
        lines.append(f"원문 : {url}")
    lines.append(f"시각 : {time_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 텔레그램 전송
# ---------------------------------------------------------------------------
def _get_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def try_daytime_alert(
    *,
    title: str,
    body: Optional[str],
    url: Optional[str],
    topic_domain: str,
    matched_keywords: list[str],
    collected_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    """
    주간 고점수 CANDIDATE 즉시 알림 시도.

    1. score_candidate() 로 점수 계산
    2. should_send_daytime_alert() 로 조건 확인
    3. 조건 충족 시 텔레그램 전송

    fail-open: 어디서든 실패하면 False 반환, 파이프라인 계속.
    """
    try:
        from app.services.top5_briefing_service import CandidateEntry, score_candidate

        entry = CandidateEntry(
            title=title,
            body=body,
            url=url,
            topic_domain=topic_domain,
            matched_keywords=matched_keywords,
            breaking_reason=None,
            urgency=None,
            collected_at=collected_at or datetime.now(tz=timezone.utc),
        )

        ref_kst = (now or datetime.now(tz=_KST))
        if ref_kst.tzinfo is None:
            ref_kst = ref_kst.replace(tzinfo=_KST)
        else:
            ref_kst = ref_kst.astimezone(_KST)
        score = score_candidate(entry, ref_kst)

        if not should_send_daytime_alert(
            matched_keywords=matched_keywords,
            score=score,
            collected_at=collected_at,
            now=now,
        ):
            logger.debug(
                f"[daytime-alert] 조건 미충족: score={score:.0f}, "
                f"keywords={len(matched_keywords)}, daytime={_is_daytime_kst(now=now)}"
            )
            return False

        logger.info(
            f"[daytime-alert] 조건 충족: score={score:.0f}, "
            f"keywords={len(matched_keywords)}, domain={topic_domain}"
        )

        text = build_daytime_alert_text(
            title=title,
            body=body,
            url=url,
            topic_domain=topic_domain,
            matched_keywords=matched_keywords,
            score=score,
            collected_at=collected_at,
        )

        if not settings.has_telegram_config:
            logger.info(f"[MOCK 텔레그램] daytime alert:\n{text}")
            return True

        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": text,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _get_api_url("sendMessage"),
                data=payload,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"[daytime-alert] 전송 성공: score={score:.0f}")
                return True
            logger.warning(f"[daytime-alert] 텔레그램 응답 ok=false: {result}")
            return False

    except Exception as e:
        logger.warning(f"[daytime-alert] 실패 (fail-open): {e}")
        return False
