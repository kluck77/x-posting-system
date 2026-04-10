"""
TOP5 BRIEFING SERVICE
=====================
22:00 ~ 05:00 KST 야간 CANDIDATE 기사 중 점수 상위 5건을 선정하여
05:00 KST 에 텔레그램 브리핑 카드로 발송한다.

기준 문서
- docs/TOP5_BRIEFING_SCORING_SPEC.md       — 점수 산정 + 5건 선정 규칙
- docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md — §7~§9 Top5 카드 양식
- docs/ACCOUNT_CONSTITUTION.md             — 계정 적합도 판단 근거

설계 원칙
- 기존 BREAKING 라인 (breaking_alert_service.py) 과 완전 분리.
- approval flow (telegram_service.py) 무간섭.
- fail-open : 점수 계산 / 카드 생성 / 전송 어디서든 실패하면 로그만 남기고 진행.
- DB 스키마 변경 금지. 인메모리 저장소만 사용 (프로세스 재시작 시 초기화).
- 외부 패키지 추가 금지 (stdlib + httpx 만 사용).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import TYPE_CHECKING, Optional

import httpx

from app.config import settings

if TYPE_CHECKING:
    from app.services.breaking_classifier import ClassificationResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 시간대 상수
# ---------------------------------------------------------------------------
_KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# 인메모리 CANDIDATE 저장소
# ---------------------------------------------------------------------------

@dataclass
class CandidateEntry:
    """야간 큐에 적재되는 CANDIDATE 기사 1건."""
    title: str
    body: Optional[str]
    url: Optional[str]
    topic_domain: str
    matched_keywords: list[str]
    breaking_reason: Optional[str]
    urgency: Optional[str]
    collected_at: datetime  # UTC
    score: float = 0.0


_candidate_store: list[CandidateEntry] = []
_candidate_lock = Lock()

# BREAKING_NOW 로 전송된 issue_key 추적 (Top5 제외용)
_breaking_sent_keys: set[str] = set()
_breaking_sent_lock = Lock()

# DB 복원 플래그
_candidates_loaded_from_db = False


def record_candidate(
    *,
    title: str,
    body: Optional[str],
    url: Optional[str],
    topic_domain: str,
    matched_keywords: list[str],
    breaking_reason: Optional[str] = None,
    urgency: Optional[str] = None,
    collected_at: Optional[datetime] = None,
) -> None:
    """CANDIDATE 분류된 기사를 야간 큐에 적재. orchestrator Step 1.5 에서 호출."""
    entry = CandidateEntry(
        title=title,
        body=body,
        url=url,
        topic_domain=topic_domain,
        matched_keywords=matched_keywords,
        breaking_reason=breaking_reason,
        urgency=urgency,
        collected_at=collected_at or datetime.now(tz=timezone.utc),
    )
    with _candidate_lock:
        _candidate_store.append(entry)
    _persist_candidate_to_db(entry)
    logger.debug(f"[top5] candidate recorded: {title[:40]}")


def record_breaking_sent(*, title: str, topic_domain: str) -> None:
    """BREAKING_NOW 전송 성공 시 호출. Top5 제외 대상 등록."""
    key = _issue_key(title, topic_domain)
    with _breaking_sent_lock:
        _breaking_sent_keys.add(key)
    _persist_breaking_sent_to_db(key)


def _issue_key(title: str, topic_domain: str) -> str:
    """제목 + 도메인 기반 간이 issue key (dedup/제외 판별용)."""
    norm = re.sub(r"[^\w]", "", title.lower())
    raw = f"{norm}|{topic_domain}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _reset_stores_for_tests() -> None:
    """테스트 전용."""
    global _candidates_loaded_from_db
    with _candidate_lock:
        _candidate_store.clear()
    with _breaking_sent_lock:
        _breaking_sent_keys.clear()
    _candidates_loaded_from_db = False


def _current_cycle_date() -> str:
    """현재 브리핑 사이클 날짜 (YYYY-MM-DD KST). 05:00 전이면 당일, 이후면 익일."""
    now_kst = datetime.now(tz=_KST)
    if now_kst.hour < 5:
        return now_kst.strftime("%Y-%m-%d")
    return (now_kst + timedelta(days=1)).strftime("%Y-%m-%d")


def _persist_candidate_to_db(entry: CandidateEntry) -> None:
    """DB write-through (fail-open)."""
    try:
        import json
        from app.db import get_db
        from app.models.dedup import CandidatePoolEntry
        db = get_db()
        try:
            db.add(CandidatePoolEntry(
                title=entry.title,
                body=entry.body,
                url=entry.url,
                topic_domain=entry.topic_domain,
                matched_keywords_json=json.dumps(entry.matched_keywords, ensure_ascii=False),
                breaking_reason=entry.breaking_reason,
                urgency=entry.urgency,
                collected_at=entry.collected_at,
                cycle_date=_current_cycle_date(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("[top5] DB candidate persist 실패 (fail-open)")


def _persist_breaking_sent_to_db(issue_key: str) -> None:
    """DB write-through (fail-open)."""
    try:
        from app.db import get_db
        from app.models.dedup import BreakingSentKey
        db = get_db()
        try:
            db.add(BreakingSentKey(
                issue_key=issue_key,
                cycle_date=_current_cycle_date(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("[top5] DB breaking_sent persist 실패 (fail-open)")


def _load_candidates_from_db() -> None:
    """시작 시 DB → 메모리 복원. 현재 사이클 항목만 로드."""
    global _candidates_loaded_from_db
    if _candidates_loaded_from_db:
        return
    try:
        import json
        from app.db import get_db
        from app.models.dedup import BreakingSentKey, CandidatePoolEntry
        cycle = _current_cycle_date()
        db = get_db()
        try:
            rows = db.query(CandidatePoolEntry).filter(
                CandidatePoolEntry.cycle_date == cycle
            ).all()
            with _candidate_lock:
                for row in rows:
                    entry = CandidateEntry(
                        title=row.title,
                        body=row.body,
                        url=row.url,
                        topic_domain=row.topic_domain,
                        matched_keywords=json.loads(row.matched_keywords_json) if row.matched_keywords_json else [],
                        breaking_reason=row.breaking_reason,
                        urgency=row.urgency,
                        collected_at=row.collected_at,
                    )
                    _candidate_store.append(entry)
            sent_rows = db.query(BreakingSentKey).filter(
                BreakingSentKey.cycle_date == cycle
            ).all()
            with _breaking_sent_lock:
                for row in sent_rows:
                    _breaking_sent_keys.add(row.issue_key)
            logger.info(f"[top5] DB 로드 완료: candidates={len(rows)}, sent_keys={len(sent_rows)} (cycle={cycle})")
        finally:
            db.close()
    except Exception:
        logger.debug("[top5] DB 로드 실패 (fail-open, 인메모리만 사용)")
    _candidates_loaded_from_db = True


def _cleanup_db_after_briefing() -> None:
    """05:00 브리핑 전송 후 DB 정리. 현재 사이클 데이터 삭제."""
    try:
        from app.db import get_db
        from app.models.dedup import BreakingSentKey, CandidatePoolEntry
        cycle = _current_cycle_date()
        db = get_db()
        try:
            db.query(CandidatePoolEntry).filter(
                CandidatePoolEntry.cycle_date == cycle
            ).delete()
            db.query(BreakingSentKey).filter(
                BreakingSentKey.cycle_date == cycle
            ).delete()
            db.commit()
            logger.info(f"[top5] DB 사이클 데이터 삭제 완료 (cycle={cycle})")
        finally:
            db.close()
    except Exception:
        logger.debug("[top5] DB 정리 실패 (fail-open)")


# ---------------------------------------------------------------------------
# 야간 시간대 필터
# ---------------------------------------------------------------------------
_NIGHT_START_HOUR = 22  # KST
_NIGHT_END_HOUR = 5     # KST (다음 날)


def _is_in_night_window(dt_utc: datetime, ref_kst: datetime) -> bool:
    """dt_utc 가 ref_kst 기준 전일 22:00 ~ 당일 05:00 KST 범위 안인지 확인."""
    dt_kst = dt_utc.astimezone(_KST) if dt_utc.tzinfo else dt_utc.replace(tzinfo=timezone.utc).astimezone(_KST)
    # ref_kst 당일 05:00
    end = ref_kst.replace(hour=_NIGHT_END_HOUR, minute=0, second=0, microsecond=0)
    # 전일 22:00
    start = (end - timedelta(hours=7)).replace(hour=_NIGHT_START_HOUR)
    return start <= dt_kst <= end


# ---------------------------------------------------------------------------
# 점수 산정 (docs/TOP5_BRIEFING_SCORING_SPEC.md §4~§9)
# ---------------------------------------------------------------------------
_SCORE_THRESHOLD = 60
_MAX_SAME_ASSET = 3

# §5 신선도 (20점)
def _score_freshness(collected_at: datetime, ref_kst: datetime) -> int:
    """수집 시각의 KST 시간대 위치로 신선도 점수 산정."""
    dt_kst = collected_at.astimezone(_KST) if collected_at.tzinfo else collected_at.replace(tzinfo=timezone.utc).astimezone(_KST)
    hour = dt_kst.hour
    # 03:00 ~ 05:00 → 16~20
    if 3 <= hour < 5:
        return 16 + min(4, (dt_kst.minute // 15))
    # 00:00 ~ 03:00 → 11~15
    if 0 <= hour < 3:
        return 11 + min(4, hour + (1 if dt_kst.minute >= 30 else 0))
    # 22:00 ~ 24:00 → 6~10
    if 22 <= hour <= 23:
        return 6 + min(4, hour - 22 + (2 if dt_kst.minute >= 30 else 0))
    return 0


# §6 시장 영향도 (30점)
_MACRO_KEYWORDS = frozenset([
    "금리", "기준금리", "FOMC", "연준", "Fed", "ECB", "BOJ", "한은",
    "GDP", "CPI", "고용", "실업", "인플레이션", "디플레이션", "양적완화",
    "QE", "QT", "테이퍼링", "긴축", "완화", "경기침체", "리세션",
    "달러", "환율", "유가", "금값", "국채", "수익률곡선",
])
_TIER1_KEYWORDS = frozenset([
    "비트코인", "이더리움", "BTC", "ETH", "ETF", "삼성전자",
    "애플", "엔비디아", "테슬라", "S&P", "나스닥", "코스피",
    "코스닥", "다우", "항셍", "닛케이",
])


def _score_market_impact(topic_domain: str, matched_keywords: list[str], body: Optional[str]) -> int:
    """키워드 + 도메인 기반 시장 영향도 추정."""
    kw_set = set(k.lower() for k in matched_keywords)
    body_lower = (body or "").lower()

    macro_hits = sum(1 for k in _MACRO_KEYWORDS if k.lower() in body_lower or k.lower() in kw_set)
    tier1_hits = sum(1 for k in _TIER1_KEYWORDS if k.lower() in body_lower or k.lower() in kw_set)

    if macro_hits >= 2:
        return min(30, 25 + macro_hits)
    if tier1_hits >= 2 or macro_hits >= 1:
        return min(24, 17 + tier1_hits + macro_hits)
    if topic_domain in ("금융", "투자", "크립토", "주식"):
        return max(8, min(16, 8 + len(matched_keywords)))
    return 4


# §7 근거 강도 (25점)
_NUM_PATTERN = re.compile(r"\d[\d,.]*[%억원달러조만]")
_QUOTE_PATTERN = re.compile(r'["\u201c\u201d]|에 따르면|밝혔다|발표했다|공시')


def _score_evidence(body: Optional[str], url: Optional[str]) -> int:
    """본문 길이 / 수치 / 인용 기반 근거 강도 추정."""
    if not body:
        return 3
    length = len(body)
    numbers = len(_NUM_PATTERN.findall(body))
    quotes = len(_QUOTE_PATTERN.findall(body))

    score = 0
    # 본문 길이
    if length >= 1500:
        score += 12
    elif length >= 800:
        score += 9
    elif length >= 400:
        score += 6
    else:
        score += 3
    # 수치
    score += min(7, numbers * 2)
    # 인용
    score += min(6, quotes * 2)
    return min(25, score)


# §8 계정 적합도 (25점)
_DOMAIN_SET = frozenset(["금융", "투자", "크립토", "주식"])
_INTERPRETATION_SIGNALS = re.compile(
    r"왜|전망|영향|분석|의미|시사|전략|자금흐름|심리|수급|포지션|리스크"
)


def _score_account_fit(topic_domain: str, matched_keywords: list[str], body: Optional[str]) -> int:
    """계정 4개 도메인 적합도 추정."""
    body_text = body or ""
    in_domain = topic_domain in _DOMAIN_SET
    interp_count = len(_INTERPRETATION_SIGNALS.findall(body_text))

    if in_domain and interp_count >= 2:
        return min(25, 20 + min(5, interp_count - 1))
    if in_domain and interp_count >= 1:
        return min(19, 12 + len(matched_keywords))
    if in_domain:
        return min(11, 6 + len(matched_keywords))
    return min(5, interp_count)


# §9 패널티
_SENSATIONAL_WORDS = re.compile(
    r"충격|발칵|초비상|긴급속보|폭등|폭락|대폭발|속보!", flags=re.IGNORECASE,
)
_EXCLAMATION_DOUBLE = re.compile(r"!!+")


def _penalty_sensational_title(title: str) -> int:
    """자극 제목 패널티. 0 ~ -10."""
    penalty = 0
    penalty += len(_SENSATIONAL_WORDS.findall(title)) * 3
    if _EXCLAMATION_DOUBLE.search(title):
        penalty += 3
    return min(10, penalty)


def _penalty_thin_body(body: Optional[str]) -> int:
    """본문 빈약 패널티. 0 ~ -10."""
    if not body:
        return 10
    penalty = 0
    if len(body) < 400:
        penalty += 5
    has_num = bool(_NUM_PATTERN.search(body))
    has_quote = bool(_QUOTE_PATTERN.search(body))
    has_context = bool(_INTERPRETATION_SIGNALS.search(body))
    if not has_num and not has_quote and not has_context:
        penalty += 5
    return min(10, penalty)


def score_candidate(entry: CandidateEntry, ref_kst: datetime) -> float:
    """단일 CANDIDATE 총점 계산. §4 구조 기반."""
    freshness = _score_freshness(entry.collected_at, ref_kst)
    market = _score_market_impact(entry.topic_domain, entry.matched_keywords, entry.body)
    evidence = _score_evidence(entry.body, entry.url)
    fit = _score_account_fit(entry.topic_domain, entry.matched_keywords, entry.body)

    gross = freshness + market + evidence + fit

    pen_title = _penalty_sensational_title(entry.title)
    pen_body = _penalty_thin_body(entry.body)

    total = max(0, gross - pen_title - pen_body)
    return total


# ---------------------------------------------------------------------------
# §9.1 중복도 패널티 + §10 Top5 선정
# ---------------------------------------------------------------------------
def _group_by_issue(candidates: list[CandidateEntry]) -> dict[str, list[CandidateEntry]]:
    """같은 issue_key 로 묶어 중복도 패널티 준비."""
    groups: dict[str, list[CandidateEntry]] = {}
    for c in candidates:
        key = _issue_key(c.title, c.topic_domain)
        groups.setdefault(key, []).append(c)
    return groups


def select_top5(
    *,
    ref_kst: Optional[datetime] = None,
) -> list[CandidateEntry]:
    """
    야간 CANDIDATE 저장소에서 Top5 선정.
    - BREAKING_NOW 전송분 제외
    - 야간 시간대 필터
    - 점수 산정 + 패널티
    - 자산군 균형 (§10.2)
    - 60점 하한선 (§10.4)
    """
    if ref_kst is None:
        ref_kst = datetime.now(tz=_KST)

    _load_candidates_from_db()

    with _candidate_lock:
        pool = list(_candidate_store)

    with _breaking_sent_lock:
        sent_keys = set(_breaking_sent_keys)

    # 1) 야간 시간대 필터
    pool = [c for c in pool if _is_in_night_window(c.collected_at, ref_kst)]

    # 2) BREAKING_NOW 전송분 제외
    pool = [c for c in pool if _issue_key(c.title, c.topic_domain) not in sent_keys]

    # 3) 점수 산정
    for c in pool:
        c.score = score_candidate(c, ref_kst)

    # 4) 중복도 패널티 (§9.1) — 같은 이슈 중 최고점 1건만 유지
    groups = _group_by_issue(pool)
    deduped: list[CandidateEntry] = []
    for entries in groups.values():
        best = max(entries, key=lambda x: x.score)
        deduped.append(best)

    # 5) 60점 하한선
    deduped = [c for c in deduped if c.score >= _SCORE_THRESHOLD]

    # 6) 점수 내림차순 정렬 + 동률 처리 (§10.3)
    deduped.sort(key=lambda c: (
        -c.score,
        -_score_evidence(c.body, c.url),
        _penalty_sensational_title(c.title),
        -_score_freshness(c.collected_at, ref_kst),
    ))

    # 7) 자산군 균형 (§10.2) — 동일 자산군 최대 3건
    result: list[CandidateEntry] = []
    asset_counts: dict[str, int] = {}
    for c in deduped:
        domain = c.topic_domain
        count = asset_counts.get(domain, 0)
        # 시장 영향도 28+ 면 캡 미적용
        market_score = _score_market_impact(domain, c.matched_keywords, c.body)
        if count >= _MAX_SAME_ASSET and market_score < 28:
            continue
        result.append(c)
        asset_counts[domain] = count + 1
        if len(result) >= 5:
            break

    return result


# ---------------------------------------------------------------------------
# 카드 생성 (§7 / §8 / §9 템플릿)
# ---------------------------------------------------------------------------
_TITLE_MAX = 50
_SUMMARY_MAX = 70
_CARD_MAX_CHARS = 800


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _one_line_summary(body: Optional[str], title: str) -> str:
    """본문 선두 1문장 추출. 없으면 제목 압축."""
    if not body:
        return _clip(title, _SUMMARY_MAX)
    # 첫 마침표/물음표/느낌표 기준 1문장
    m = re.match(r"(.+?[.?!。])\s", body)
    if m:
        return _clip(m.group(1).strip(), _SUMMARY_MAX)
    return _clip(body[:_SUMMARY_MAX], _SUMMARY_MAX)


def build_top5_briefing_text(
    selected: list[CandidateEntry],
    *,
    ref_kst: Optional[datetime] = None,
) -> str:
    """§9 복붙 템플릿 기반 Top5 카드 텍스트 생성."""
    if ref_kst is None:
        ref_kst = datetime.now(tz=_KST)

    date_str = ref_kst.strftime("%Y-%m-%d")
    end_kst = ref_kst.replace(hour=5, minute=0, second=0, microsecond=0)
    start_kst = (end_kst - timedelta(hours=7)).replace(hour=22)

    start_str = start_kst.strftime("%Y-%m-%d %H:%M")
    end_str = end_kst.strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    lines.append(f"[새벽 5시 브리핑] {date_str} — Top {len(selected)}")
    lines.append("")
    lines.append(f"기간 : {start_str} ~ {end_str}")
    lines.append("기준 : 야간 CANDIDATE 점수 상위 5건. BREAKING_NOW 발송분 제외.")
    lines.append("")

    urls: list[str] = []
    for i, entry in enumerate(selected, 1):
        asset = entry.topic_domain if entry.topic_domain != "none" else "기타"
        title_short = _clip(entry.title, _TITLE_MAX)
        summary = _one_line_summary(entry.body, entry.title)
        lines.append(f"{i}. [{asset}] {title_short}")
        lines.append(f"   {summary}")
        lines.append("")
        if entry.url:
            urls.append(entry.url)

    if urls:
        lines.append("원문")
        for u in urls:
            lines.append(f"- {u}")

    card = "\n".join(lines)
    if len(card) > _CARD_MAX_CHARS:
        card = card[:_CARD_MAX_CHARS - 1] + "\u2026"
    return card


# ---------------------------------------------------------------------------
# 텔레그램 전송
# ---------------------------------------------------------------------------
def _get_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def send_top5_briefing(
    *,
    ref_kst: Optional[datetime] = None,
) -> bool:
    """
    Top5 브리핑 카드 생성 + 텔레그램 전송.
    - 60점 이상 후보 0건이면 브리핑 생략 (True 반환).
    - fail-open.
    """
    try:
        selected = select_top5(ref_kst=ref_kst)
    except Exception as e:
        logger.warning(f"[top5] 선정 실패 (fail-open): {e}")
        return False

    if not selected:
        logger.info("[top5] 60점 이상 후보 0건 — 05:00 브리핑 생략")
        return True

    text = build_top5_briefing_text(selected, ref_kst=ref_kst)

    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] Top5 briefing:\n{text}")
        return True

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
                logger.info(f"[top5] 브리핑 전송 성공 ({len(selected)}건)")
                return True
            logger.warning(f"[top5] 텔레그램 응답 ok=false: {result}")
            return False
    except httpx.HTTPError as e:
        logger.warning(f"[top5] 텔레그램 전송 실패 (fail-open): {e}")
        return False


async def run_top5_briefing() -> bool:
    """
    05:00 KST 스케줄러 진입점.
    선정 → 전송 → 저장소 초기화.
    """
    ref_kst = datetime.now(tz=_KST)
    logger.info(f"[top5] 05:00 브리핑 시작 ref={ref_kst.isoformat()}")

    result = await send_top5_briefing(ref_kst=ref_kst)

    # 전송 후 야간 저장소 초기화 (다음 사이클 준비)
    global _candidates_loaded_from_db
    with _candidate_lock:
        cleared = len(_candidate_store)
        _candidate_store.clear()
    with _breaking_sent_lock:
        _breaking_sent_keys.clear()
    _candidates_loaded_from_db = False

    # DB 사이클 데이터도 정리
    _cleanup_db_after_briefing()

    logger.info(f"[top5] 저장소 초기화 완료 (candidates={cleared})")
    return result
