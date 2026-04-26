"""자료 날짜 자동 검증 — W4 원칙 구현.

0~30일:   fresh (무조건 통과)
31~180일: acceptable (연월 표기 의무)
181~365일: stale (경고 표시 필수)
365일+:   blocked (역사/배경 설명에만 예외)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

import httpx

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:  # pragma: no cover
    KST = timezone(timedelta(hours=9))


@dataclass
class Source:
    url:           str
    title:         str
    publish_date:  Optional[datetime]
    domain:        str
    extracted_via: str = "unknown"


@dataclass
class ValidationResult:
    status:       Literal["fresh", "acceptable", "stale", "blocked", "unknown"]
    age_days:     Optional[int]
    warning:      Optional[str]
    block_reason: Optional[str]
    label:        Optional[str]   # 본문에 표시할 라벨


def _fmt_ko(dt: datetime, with_day: bool = False) -> str:
    """KST '2024년 4월' 형식 (Linux strftime '%-m' 비호환 방어)."""
    if with_day:
        return f"{dt.year}년 {dt.month}월 {dt.day}일"
    return f"{dt.year}년 {dt.month}월"


def validate_source(
    src: Source,
    today: Optional[datetime] = None,
    doc_kind: str = "news",
) -> ValidationResult:
    """자료 날짜 검증 — W4 원칙."""
    today = today or datetime.now(KST)

    if src.publish_date is None:
        return ValidationResult(
            status="unknown",
            age_days=None,
            warning="날짜 미확인 — 사용 시 '[미확인]' 라벨 의무",
            block_reason=None,
            label="[미확인]",
        )

    # naive datetime → KST 보정
    pub = src.publish_date
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=KST)

    age = (today - pub).days

    if age < 0:
        return ValidationResult(
            "blocked", age, None, "미래 날짜 자료", None,
        )

    if age <= 30:
        return ValidationResult("fresh", age, None, None, None)

    if age <= 180:
        label = f"({_fmt_ko(pub)} 자료)"
        return ValidationResult(
            "acceptable", age, None, None, label,
        )

    if age <= 365:
        label = f"[구 자료: {_fmt_ko(pub)}]"
        return ValidationResult(
            "stale", age,
            f"⚠️ {age}일 전 자료. 본문 연월 명시 필수.",
            None, label,
        )

    # 365일 초과
    if doc_kind in ("history", "background"):
        label = f"({pub.year}년 역사 배경)"
        return ValidationResult(
            "acceptable", age, None, None, label,
        )

    return ValidationResult(
        "blocked", age, None,
        f"1년 초과 자료 ({age}일). 배경/역사 글에만 허용. "
        "doc_kind='background' 명시 필요",
        None,
    )


def validate_sources_bulk(
    sources: list[Source],
    today: Optional[datetime] = None,
) -> dict:
    """여러 출처 일괄 검증."""
    today = today or datetime.now(KST)
    results = [validate_source(s, today) for s in sources]
    blocked = [r for r in results if r.status == "blocked"]
    stale = [r for r in results if r.status == "stale"]
    unknown = [r for r in results if r.status == "unknown"]
    return {
        "all_pass":      len(blocked) == 0,
        "has_blocked":   len(blocked) > 0,
        "has_stale":     len(stale) > 0,
        "has_unknown":   len(unknown) > 0,
        "results":       results,
        "block_reasons": [r.block_reason for r in blocked if r.block_reason],
        "warnings":      [r.warning for r in (stale + unknown) if r.warning],
    }


_URL_DATE_PATTERNS = [
    re.compile(r"/(\d{4})/(\d{2})/(\d{2})/"),
    re.compile(r"/(\d{4})-(\d{2})-(\d{2})/"),
    re.compile(r"[?&]date=(\d{4})(\d{2})(\d{2})"),
]

_META_DATE_PATTERNS = [
    re.compile(r'published_time"[^"]*"(\d{4}-\d{2}-\d{2})'),
    re.compile(r'"datePublished"[^"]*"(\d{4}-\d{2}-\d{2})'),
    re.compile(r'<meta[^>]+published[^>]+content="(\d{4}-\d{2}-\d{2})'),
]


async def extract_publish_date_from_url(url: str) -> Optional[datetime]:
    """URL/메타데이터에서 발행 날짜 추출 시도.

    1) URL 경로 패턴
    2) HTML <meta> published / datePublished
    실패 시 None.
    """
    if not url:
        return None
    # 1) URL 패턴
    for pattern in _URL_DATE_PATTERNS:
        m = pattern.search(url)
        if m:
            try:
                return datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    tzinfo=KST,
                )
            except Exception:
                continue
    # 2) HTML 메타 (상단만)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (sskorea02-bot)"},
                follow_redirects=True,
            )
            text = (resp.text or "")[:8000]
        for pattern in _META_DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    parts = m.group(1).split("-")
                    return datetime(
                        int(parts[0]), int(parts[1]), int(parts[2]),
                        tzinfo=KST,
                    )
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"[date_validator] meta 추출 실패 {url}: {e}")
    return None
