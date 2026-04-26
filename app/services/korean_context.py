"""한국 맥락 엔티티 프리페치.

query + source_text 에서 한국 엔티티 힌트를 추출하고,
korean_entities DB 3테이블을 조회해 Gemini·DraftWriter 에
주입할 compact 텍스트 블록을 생성한다.

Gemini research() context 상한(2000자) 고려해
기본 max_chars=600 제한. 매칭 없으면 빈 문자열 반환.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import get_db
from app.models.korean_entities import (
    KoreanAICompany,
    KoreanCryptoExposure,
    KoreanPolicy,
)

logger = logging.getLogger(__name__)


# 매칭 힌트 키워드 (lowercase 비교).
# 짧은 글자수는 False positive 방지를 위해 한국어 또는 티커 형태로 제한.
_AI_HINTS = {
    "naver": "Naver", "네이버": "Naver", "035420": "Naver",
    "kakao": "Kakao", "카카오": "Kakao", "035720": "Kakao",
    "kanana": "Kakao", "클로바": "Naver", "hyperclova": "Naver",
    "skt": "SKT", "sk텔레콤": "SKT", "017670": "SKT",
    "lg": "LG", "003550": "LG", "exaone": "LG",
    "kt": "KT", "030200": "KT", "mi:dm": "KT", "midm": "KT",
    "ncsoft": "NCSOFT", "varco": "NCSOFT", "036570": "NCSOFT",
    "upstage": "Upstage", "solar": "Upstage",
}

_POLICY_HINTS = {
    "vaupa": "VAUPA", "가상자산이용자보호": "VAUPA", "이용자보호법": "VAUPA",
    "daba": "DABA", "디지털자산기본법": "DABA", "스테이블코인": "DABA",
    "특금법": "특금법", "특정금융정보": "특금법", "vasp": "특금법",
    "ai기본법": "AI기본법", "인공지능 기본법": "AI기본법",
    "자본시장법": "자본시장법", "유사투자자문": "자본시장법",
    "외환거래법": "외환거래법", "외국환거래": "외환거래법",
    "전자금융거래법": "전자금융거래법",
    "k-isms": "K-ISMS", "isms": "K-ISMS",
}

_EXPOSURE_HINTS = {
    "우리기술투자": "우리기술투자", "041190": "우리기술투자",
    "한화투자증권": "한화투자증권", "003530": "한화투자증권",
    "dunamu": "우리기술투자", "두나무": "우리기술투자", "upbit": "우리기술투자",
    "업비트": "우리기술투자",
    "위메이드": "위메이드", "wemix": "위메이드", "112040": "위메이드",
    "장현국": "위메이드",
    "컴투스": "컴투스", "xpla": "컴투스", "c2x": "컴투스", "078340": "컴투스",
    "넷마블": "넷마블", "marblex": "넷마블", "251270": "넷마블",
    "klaytn": "카카오", "kaia": "카카오", "ground x": "카카오",
    "line next": "네이버", "finschia": "네이버", "dosi": "네이버",
}


def _find_hits(text: str, hints: dict[str, str]) -> list[str]:
    """힌트 딕셔너리에서 매칭된 정식 키(중복 제거) 반환."""
    if not text:
        return []
    lower = text.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for hint, canonical in hints.items():
        if hint in lower and canonical not in seen:
            hits.append(canonical)
            seen.add(canonical)
    return hits


def _render_ai(rows: Iterable[KoreanAICompany]) -> list[str]:
    out: list[str] = []
    for r in rows:
        ticker = f" ({r.ticker_kr})" if r.ticker_kr else ""
        model = r.ai_model_name or "-"
        partners = r.us_partners or ""
        status = r.msit_sovereign_ai_status or ""
        tail = []
        if partners:
            tail.append(f"US파트너: {partners}")
        if status:
            tail.append(f"주권AI: {status}")
        tail_str = ", ".join(tail)
        line = f"- {r.group_name}{ticker}: {model}"
        if tail_str:
            line += f" | {tail_str}"
        out.append(line)
    return out


def _render_policy(rows: Iterable[KoreanPolicy]) -> list[str]:
    out: list[str] = []
    for r in rows:
        peer = r.global_peer_name or ""
        eff = r.effective_date or ""
        tail = []
        if eff:
            tail.append(f"시행 {eff}")
        if peer:
            tail.append(f"글로벌 peer: {peer}")
        tail_str = ", ".join(tail)
        line = f"- {r.kr_short} ({r.kr_name})"
        if tail_str:
            line += f" | {tail_str}"
        out.append(line)
    return out


def _render_exposure(rows: Iterable[KoreanCryptoExposure]) -> list[str]:
    out: list[str] = []
    for r in rows:
        ticker = f" ({r.ticker_kr})" if r.ticker_kr else ""
        kind = r.exposure_kind or ""
        summary = (r.exposure_summary or "").strip()
        # 요약은 한 줄에 90자 제한
        if len(summary) > 90:
            summary = summary[:87] + "..."
        line = f"- {r.corp_name}{ticker}"
        if kind:
            line += f" [{kind}]"
        if summary:
            line += f": {summary}"
        out.append(line)
    return out


def build_korean_entity_brief(
    query: str,
    source_text: str,
    max_chars: int = 600,
    db: Session | None = None,
) -> str:
    """query + source_text 로부터 한국 맥락 엔티티 브리프 생성.

    매칭 없으면 빈 문자열 반환.
    max_chars 상한 초과 시 우선순위(Policy > Exposure > AI)로 절사.
    """
    combined = f"{query or ''} {source_text or ''}"

    ai_hits = _find_hits(combined, _AI_HINTS)
    policy_hits = _find_hits(combined, _POLICY_HINTS)
    exposure_hits = _find_hits(combined, _EXPOSURE_HINTS)

    if not (ai_hits or policy_hits or exposure_hits):
        return ""

    own_db = False
    if db is None:
        db = get_db()
        own_db = True

    try:
        sections: list[str] = []

        if policy_hits:
            rows = (
                db.query(KoreanPolicy)
                .filter(KoreanPolicy.kr_short.in_(policy_hits))
                .all()
            )
            if rows:
                sections.append("[KR 정책]\n" + "\n".join(_render_policy(rows)))

        if exposure_hits:
            rows = (
                db.query(KoreanCryptoExposure)
                .filter(KoreanCryptoExposure.corp_name.in_(exposure_hits))
                .all()
            )
            if rows:
                sections.append("[KR 상장사 크립토 노출]\n" + "\n".join(_render_exposure(rows)))

        if ai_hits:
            rows = (
                db.query(KoreanAICompany)
                .filter(KoreanAICompany.group_name.in_(ai_hits))
                .all()
            )
            if rows:
                sections.append("[KR AI/클라우드]\n" + "\n".join(_render_ai(rows)))

        if not sections:
            return ""

        brief = "\n\n".join(sections)
        if len(brief) > max_chars:
            brief = brief[:max_chars - 3] + "..."
        return brief

    except Exception as e:
        logger.warning(f"[korean_context] DB 조회 실패 (무시): {e}")
        return ""
    finally:
        if own_db:
            try:
                db.close()
            except Exception:
                pass
