"""
Post Linter (시스템 규칙 / 라벨러)
====================================
초안/최종본에 대해 "반복 가능하고 점수화 가능한" 구조 체크 결과를 라벨로만
뽑아 sidecar 에 누적한다. 문장 품질 / 훅 압축 / AI 냄새 제거 같은 prose
편집은 구독형 Grok 에이전트가 최종 편집장으로 맡는다. 여기선 오직 라벨.

설계 원칙
---------
- 역할 분리 : 시스템 = 검사관 / 구조 설계자 / 라벨러. Grok = 최종 편집장.
- 재작성 0 : 본문을 고치지 않는다. 라벨만 리턴.
- fail-open: 어떤 내부 체크가 터져도 해당 영역만 None/False 로 떨어뜨리고
             전체는 항상 dict 를 리턴. 호출부가 sidecar 저장을 놓치지 않게.
- 결정론적 : 외부 호출 0. 정규식 + 키워드. 한 draft 당 수십 ms 이내.
- 확장성   : LINTER_VERSION 을 bump 하면 나중 분석에서 세대 분리 가능.

스키마 (반환 dict 최상위 키 고정, 하위 값은 None/기본으로 채워짐):
  linter_version, linkless_context, why_now, company_context, ending,
  frame_rt, emoji, flags, meta
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

LINTER_VERSION = "1"

# ─── 키워드 사전 ────────────────────────────────────────────────────────────

# "왜 지금" 트리거 어휘 (한/영 혼용)
_WHY_NOW_TOKENS = (
    "오늘", "지금", "이번주", "이번 주", "최근", "방금", "직전",
    "이번달", "이번 달", "어제", "내일", "다음주", "다음 주",
    "just now", "today", "recently", "this week", "last week",
)

# 날짜/시점 앵커 정규식 (하나라도 맞으면 True)
_DATE_ANCHOR_PATTERNS = (
    re.compile(r"\b20\d{2}\b"),                          # 2024, 2026 등
    re.compile(r"\b(Q[1-4])\b", re.IGNORECASE),          # Q1
    re.compile(r"\b\d{1,2}/\d{1,2}\b"),                  # 6/15
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),           # 4월 20일
    re.compile(r"\d{1,2}\s*월"),                          # 4월
    re.compile(r"\d{1,2}\s*일"),                          # 20일
    re.compile(r"\d{1,2}\s*분기"),                         # 1분기
    re.compile(r"(상반기|하반기|연말|연초|연내)"),
)

# 단계/상태 어휘
_STAGE_STATUS_TOKENS = (
    "발표", "공표", "공개", "통과", "가결", "부결", "상정", "심사",
    "검토", "유예", "연기", "시행", "발효", "폐기", "합의", "의결",
    "제출", "접수", "승인", "거부", "도입", "추진", "철회",
    "announced", "approved", "rejected", "delayed", "effective",
)

# Why-Now 적용 대상 category
_WHY_NOW_CATEGORIES = (
    "policy", "regulation", "politics", "economy", "society",
    "company", "market",
)

# generic CTA 패턴 (낮은 임계)
_GENERIC_CTA_PATTERNS = (
    re.compile(r"팔로(?:우|워|ㅇ)"),
    re.compile(r"구독\s*(?:해|부탁)"),
    re.compile(r"알림\s*(?:설정|켜|신청)"),
    re.compile(r"좋아요\s*(?:눌러|부탁)"),
    re.compile(r"RT\s*(?:부탁|해)"),
    re.compile(r"\bfollow\b", re.IGNORECASE),
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\blike\b.{0,6}\bretweet\b", re.IGNORECASE),
)

# AI 톤 fallback (한/영 혼용, 소규모)
_AI_TONE_FALLBACK = (
    "it's worth noting", "furthermore", "as we can see", "delve into",
    "tapestry", "it is important to", "nuanced", "multifaceted",
    "game-changer", "paradigm shift",
    "바야흐로", "다름아닌", "라고 할 수 있다", "임을 알 수 있다",
    "다시 한 번 강조", "주목할 필요가 있다",
)

# 국가/시장/권역 키워드
_MARKET_OR_COUNTRY_TOKENS = (
    "한국", "대한민국", "서울", "부산", "Korea", "KRX", "코스피", "코스닥",
    "미국", "중국", "일본", "유럽", "EU", "US", "Japan", "China",
    "글로벌", "국내", "해외", "아시아", "국제",
)

# 정체성(identity) 시그널 — 이 계정 특유 / "우리" 프레임
_IDENTITY_TOKENS = ("우리", "한국", "대한민국", "서울", "국내", "한국인")

# 이모지 분류용 (structure 성격)
_STRUCTURE_EMOJIS = ("⚠️", "🚨", "📌", "✅", "❌", "➡️", "▶", "→", "🔥", "💡")

# 고유명사/기관 후보 — Latin CAPS 패턴 (대문자 2자+) 또는 CamelCase 한 단어
_ENTITY_PATTERN_LATIN = re.compile(r"\b([A-Z][A-Za-z0-9&\.\-]{1,24})\b")
# 한글 고유명사: "한국은행/금융위원회/삼성전자" 류는 휴리스틱 어려우니 후속 과제.
# 이번엔 Latin 표기만 잡는다.


# ─── 내부 유틸 ──────────────────────────────────────────────────────────────

def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""


def _count_emojis(text: str) -> int:
    # 명시적 이모지/심볼 블록만 카운트. 한글(U+AC00–U+D7AF) / CJK 는 제외.
    count = 0
    for ch in text:
        cp = ord(ch)
        if (0x2600 <= cp <= 0x27BF) or (0x1F000 <= cp <= 0x1FAFF):
            count += 1
    return count


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    for t in tokens:
        if t.lower() in low:
            return True
    return False


def _split_sentences(body: str) -> list[str]:
    """한/영 혼용 본문 문장 분할. 간단한 규칙 + 줄바꿈 존중."""
    if not body:
        return []
    # 줄바꿈은 문장 구분으로 본다
    raw = re.split(r"(?<=[\.\?!])\s+|\n+", body)
    return [s.strip() for s in raw if s.strip()]


def _last_sentence(body: str) -> str:
    sents = _split_sentences(body)
    return sents[-1] if sents else ""


# ─── 체크 함수들 ────────────────────────────────────────────────────────────

def _check_linkless_context(hook: str, body: str) -> dict[str, bool]:
    text = (hook + "\n" + body).strip()
    # who: 대문자 영문 고유명사 OR 한국어 기관/회사명 후보(간이)
    who = bool(_ENTITY_PATTERN_LATIN.search(text)) or bool(
        re.search(r"(정부|은행|금융위|공정위|국회|총리실|산업부|기재부|검찰|경찰|삼성|현대|SK|LG|네이버|카카오)", text)
    )
    # what: 동사형 어미 (한국어) OR 동작 동사 (영어)
    what = bool(re.search(r"(했다|한다|발표|예정|추진|검토|통과|출시|도입|시행|공개)", text)) or bool(
        re.search(r"\b(launched|announced|released|passed|approved|rejected|plans?|expects?)\b", text, re.IGNORECASE)
    )
    # when: 날짜 앵커
    when = any(p.search(text) for p in _DATE_ANCHOR_PATTERNS) or _has_any(text, _WHY_NOW_TOKENS)
    # market/country
    market = _has_any(text, _MARKET_OR_COUNTRY_TOKENS)
    return {
        "who_present": who,
        "what_present": what,
        "when_present": when,
        "market_or_country_present": market,
        "linkless_context_complete": who and what and when and market,
    }


def _check_why_now(body: str, category: str | None) -> dict[str, Any]:
    applies = bool(category) and str(category).lower() in _WHY_NOW_CATEGORIES
    why_now_present = _has_any(body, _WHY_NOW_TOKENS)
    date_anchor = any(p.search(body) for p in _DATE_ANCHOR_PATTERNS)
    stage_status = _has_any(body, _STAGE_STATUS_TOKENS)
    return {
        "applies": applies,
        "why_now_present": why_now_present,
        "date_anchor_present": date_anchor,
        "stage_status_present": stage_status,
    }


def _check_company_context(text: str) -> dict[str, Any]:
    """
    Latin 대문자 고유명사(AAPL, BBC 등) 만 판정.
    고유명사 뒤 8자 이내에 한국어 조사/동사 또는 괄호/쉼표 수식이 붙으면
    context_used 로 간주. 매우 보수적.
    """
    entities_missing: list[str] = []
    entities_all: set[str] = set()
    for m in _ENTITY_PATTERN_LATIN.finditer(text):
        tok = m.group(1)
        # 흔한 약어/단어는 제외
        if tok in {"US", "EU", "UK", "AI", "CEO", "CFO", "IT", "NEW", "KO", "EN", "X"}:
            continue
        if len(tok) < 2:
            continue
        entities_all.add(tok)
        tail = text[m.end(): m.end() + 20]
        has_ctx = bool(
            re.search(r"[\(\[][^\)\]]{1,30}[\)\]]", tail)    # (설명)
            or re.match(r"^\s*(은|는|이|가|을|를|의|에|으로|,|—|-|은\s*|는\s*)", tail)
        )
        if not has_ctx:
            if tok not in entities_missing:
                entities_missing.append(tok)
        if len(entities_missing) >= 5:
            break
    needed = len(entities_all) > 0
    return {
        "company_context_needed": needed,
        "company_context_used": needed and not entities_missing,
        "entities_requiring_context": entities_missing[:5],
    }


def _classify_ending(body: str) -> str:
    s = _last_sentence(body)
    if not s:
        return "other"
    low = s.lower()
    # question_only — 마지막 문장이 의문문이고, 앞부분에 결론성 진술이 거의 없음
    ends_with_q = s.rstrip().endswith("?") or s.rstrip().endswith("？")
    # checklist — 번호/불릿/체크 표시
    if re.search(r"(^|\n)\s*(\d+[\.\)]|[-•▪])\s", body):
        return "checklist"
    # warning — 경고 신호 + 마지막 문장에 위험성/주의 어휘
    if "⚠️" in body or "🚨" in body or any(
        t in s for t in ("주의", "위험", "조심", "경계", "리스크", "risk", "caution", "warning")
    ):
        return "warning"
    # scenario — "만약/가정/시나리오/할 경우" 등
    if any(t in body for t in ("만약", "가정", "시나리오", "할 경우", "한다면", "if ", "scenario")):
        return "scenario"
    # position_plus_question — 결론 진술이 있고 끝을 질문으로 맺음
    if ends_with_q:
        prior = body[: -len(s)].strip()
        # 임계 30자: 짧은 결론 한 문장 수준이면 "진술 + 질문" 으로 인정
        if prior and len(prior) >= 30:
            return "position_plus_question"
        return "question_only"
    return "other"


def _check_ending(body: str) -> dict[str, Any]:
    ending_type = _classify_ending(body)
    weak = (ending_type == "question_only")
    # 추가 약한 엔딩: 마지막 문장이 너무 짧고 일반적
    last = _last_sentence(body)
    if not weak and last:
        if len(last) <= 10 and not last.endswith(("?", "？", "!")):
            weak = True
    return {
        "ending_type": ending_type,
        "weak_ending_flag": weak,
    }


def _check_frame_rt(hook: str, body: str, pack: dict | None) -> dict[str, Any]:
    text = (hook + "\n" + body)
    frame_type = None
    if isinstance(pack, dict):
        angle = pack.get("angle_pack") or pack.get("angle") or {}
        if isinstance(angle, dict):
            frame_type = angle.get("frame_type") or angle.get("frame")
    triggers: list[str] = []
    if re.search(r"(N?\s*배|두 배|절반|대비|vs\.?|비해|보다)", text, re.IGNORECASE):
        triggers.append("comparison")
    if re.search(r"(전\s*→\s*후|이전엔|지금은|예전엔|그때는|before|now)", text, re.IGNORECASE):
        triggers.append("before_after")
    if re.search(r"(아무도|지금도|여전히|감춰|숨겨|알려지지 않|밝혀지지 않)", text):
        triggers.append("gap_exposure")
    if re.search(r"\b(\d{1,3}(?:[,\d]*)|\d+\.\d+)\s*(%|명|원|달러|건|곳|위)", text):
        triggers.append("specific_number")
    if re.search(r"(어느 쪽|선택|포기|지키|포기|갈림길)", text):
        triggers.append("moral_choice")
    identity = _has_any(text, _IDENTITY_TOKENS)
    korea = ("한국" in text) or ("Korea" in text) or ("대한민국" in text)
    return {
        "frame_type": frame_type,
        "rt_trigger_type": triggers,
        "identity_signal_present": identity,
        "korea_angle_used": korea,
    }


def _check_emoji(hook: str, body: str) -> dict[str, Any]:
    text = hook + "\n" + body
    count = _count_emojis(text)
    fn = "none"
    if count > 0:
        if any(e in text for e in _STRUCTURE_EMOJIS):
            fn = "structure"
        else:
            fn = "other"
    return {"emoji_count": count, "emoji_function": fn}


def _load_banned_style() -> tuple[str, ...]:
    """Strategy OS banned_style 조회. 실패하면 fallback."""
    try:
        from app.services.strategy_os import load_strategy_os
        d = load_strategy_os()
        bs = d.get("banned_style") if isinstance(d, dict) else None
        if isinstance(bs, list) and bs:
            out: list[str] = []
            for x in bs:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip())
            if out:
                # Strategy OS 에 있는 것 + fallback 한국어 세트 일부
                ko_fallback = tuple(t for t in _AI_TONE_FALLBACK if re.search(r"[가-힣]", t))
                return tuple(out) + ko_fallback
    except Exception as e:
        logger.warning(f"[post_linter] banned_style 로드 실패, fallback 사용: {e}")
    return _AI_TONE_FALLBACK


def _check_flags(
    hook: str,
    body: str,
    linkless: dict[str, Any],
    ending: dict[str, Any],
    banned_style: tuple[str, ...],
) -> dict[str, bool]:
    text = hook + "\n" + body
    low = text.lower()
    ai_tone = any(t.lower() in low for t in banned_style)
    has_number = bool(re.search(r"\d", text))
    weak_share = not has_number
    missing_ctx = not bool(linkless.get("linkless_context_complete"))
    weak_ending = bool(ending.get("weak_ending_flag"))
    generic_cta = any(p.search(text) for p in _GENERIC_CTA_PATTERNS)
    return {
        "ai_tone_flag": ai_tone,
        "weak_share_value_flag": weak_share,
        "missing_context_flag": missing_ctx,
        "weak_ending_flag": weak_ending,
        "generic_cta_flag": generic_cta,
    }


# ─── 엔트리 포인트 ─────────────────────────────────────────────────────────

def run_post_linter(
    *,
    hook: str,
    body: str,
    pack: dict | None = None,
    category: str | None = None,
    title: str | None = None,
    banned_style: list[str] | None = None,
) -> dict[str, Any]:
    """
    라벨 dict 을 리턴한다. 어떤 체크가 예외로 빠져도 그 영역만 None/False 로
    떨어뜨리고 전체는 항상 dict 를 리턴 — sidecar 저장을 놓치지 않기 위함.
    """
    h = _safe_str(hook)
    b = _safe_str(body)
    out: dict[str, Any] = {
        "linter_version": LINTER_VERSION,
        "linkless_context": None,
        "why_now": None,
        "company_context": None,
        "ending": None,
        "frame_rt": None,
        "emoji": None,
        "flags": None,
        "meta": None,
    }

    # linkless_context
    try:
        out["linkless_context"] = _check_linkless_context(h, b)
    except Exception as e:
        logger.warning(f"[post_linter] linkless_context 실패: {e}")

    # why_now
    try:
        out["why_now"] = _check_why_now(b, category)
    except Exception as e:
        logger.warning(f"[post_linter] why_now 실패: {e}")

    # company_context
    try:
        out["company_context"] = _check_company_context((title or "") + "\n" + h + "\n" + b)
    except Exception as e:
        logger.warning(f"[post_linter] company_context 실패: {e}")

    # ending
    ending: dict[str, Any] = {}
    try:
        ending = _check_ending(b)
        out["ending"] = ending
    except Exception as e:
        logger.warning(f"[post_linter] ending 실패: {e}")

    # frame_rt
    try:
        out["frame_rt"] = _check_frame_rt(h, b, pack if isinstance(pack, dict) else None)
    except Exception as e:
        logger.warning(f"[post_linter] frame_rt 실패: {e}")

    # emoji
    try:
        out["emoji"] = _check_emoji(h, b)
    except Exception as e:
        logger.warning(f"[post_linter] emoji 실패: {e}")

    # flags
    try:
        bs: tuple[str, ...]
        if banned_style is not None:
            bs = tuple(s for s in banned_style if isinstance(s, str) and s.strip())
        else:
            bs = _load_banned_style()
        out["flags"] = _check_flags(h, b, out["linkless_context"] or {}, ending or {}, bs)
    except Exception as e:
        logger.warning(f"[post_linter] flags 실패: {e}")

    # meta
    try:
        out["meta"] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_hook_len": len(h),
            "source_body_len": len(b),
        }
    except Exception:
        out["meta"] = {"checked_at": None, "source_hook_len": len(h), "source_body_len": len(b)}

    return out
