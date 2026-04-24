"""
editorial_meta.py
==================
Phase 4 + 5: Grok 편집장에게 넘어가는 handoff 를 "검토 메모" 가 아니라
"편집장 지시서" 로 쓰기 위한 메타 신호. 각 필드는 1줄 중심.

원칙:
- 시스템은 본문을 재작성하지 않는다. 신호만 생산.
- 외부 LLM 호출 0. 결정론적 휴리스틱 + 기존 데이터 재조립.
- fail-open: 각 파생 함수 실패 시 해당 필드만 빈값 / None.
  전체 dict 는 항상 유효한 스키마로 반환.
- 중복 없음: too_obvious 는 grok_handoff 의 기존 휴리스틱 재사용.

반환 스키마 (META_VERSION="2", key 12):
    meta_version, stop_scroll_line, rt_motive_type, identity_signal,
    hidden_variable, stake_sentence, too_obvious_flag, too_obvious_warning,
    editorial_goal, what_to_sharpen (list, ≤2), what_to_cut (list, ≤3),
    salvageability: {score, reason, checks}
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

META_VERSION = "2"

_RT_MOTIVE_TYPES = (
    "approval", "argue", "signal", "identity", "practical", "unclear",
)

# 휴리스틱 상수
_NUM_RE = re.compile(r"\d")
_CONTRAST_TOKENS = (
    "대비", "반면", "그러나", "vs", " vs ", "배", "두 배",
    "절반", "보다", "unlike", "before", "now",
)
_PRACTICAL_TOKENS = (
    # "대비" 단독은 "전년 대비" 같은 비교 표현에도 매치되므로 "대비해" 로 좁힘.
    "체크", "확인", "점검", "대비해", "주의", "watch", "check", "monitor",
)
_ARGUE_TOKENS = (
    "반박", "논쟁", "허구", "오류", "진실", "사실은", "실제로는",
    "wrong", "myth",
)
_APPROVAL_TOKENS = (
    "정확히 이", "맞는 말", "공감", "옳다", "that's right", "exactly",
)
_IDENTITY_TOKENS = ("우리", "한국", "대한민국", "서울", "국내", "한국인")

_TOO_OBVIOUS_REASONS = {
    "no_numbers": "표면 인과만 — 구체 수치가 없어 독자가 이미 아는 설명 수준",
    "no_hidden": "표면 인과만 — 숨은 변수 / 비대칭 노출이 드러나지 않음",
    "news_echo": "주류 매체가 이미 반복한 결론을 재진술",
}


# ─── 유틸 ───────────────────────────────────────────────────────────────

def _safe_str(x: Any, limit: int = 300) -> str:
    if x is None:
        return ""
    try:
        s = str(x).strip()
    except Exception:
        return ""
    return s[:limit] if len(s) > limit else s


def _clip(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _nonempty(s: Any) -> bool:
    return isinstance(s, str) and bool(s.strip())


def _has_number(text: str) -> bool:
    return bool(_NUM_RE.search(text or ""))


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(t.lower() in low for t in tokens)


# ─── 파생 함수 ──────────────────────────────────────────────────────────

def _derive_stop_scroll_line(hook: str, angle_pack: dict | None) -> str:
    """훅 후보 1줄. hook / share_trigger / core_tension 중 숫자·대비 단서
    가장 강한 것 선택. 최대 90자."""
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    candidates = [
        _safe_str(hook, 300),
        _safe_str(ap.get("share_trigger"), 300),
        _safe_str(ap.get("core_tension"), 300),
    ]
    best = ""
    best_score = -1
    for c in candidates:
        if not c:
            continue
        score = 0
        if _has_number(c):
            score += 2
        if _has_any(c, _CONTRAST_TOKENS):
            score += 2
        if 10 <= len(c) <= 90:
            score += 1
        if score > best_score:
            best_score = score
            best = c
    return _clip(best, 90)


def _derive_rt_motive(
    body: str,
    category: str | None,
    linter_labels: dict | None,
    strategy_os: dict | None,
) -> str:
    """RT 동기 추정. 우선순위: identity → argue → practical → signal → approval → unclear."""
    b = _safe_str(body, 2000)
    lab = linter_labels if isinstance(linter_labels, dict) else {}
    frame_rt = lab.get("frame_rt") if isinstance(lab.get("frame_rt"), dict) else {}
    if frame_rt.get("identity_signal_present") or frame_rt.get("korea_angle_used"):
        if _has_any(b, _IDENTITY_TOKENS):
            return "identity"
    if _has_any(b, _ARGUE_TOKENS):
        return "argue"
    if _has_any(b, _PRACTICAL_TOKENS) and _has_number(b):
        return "practical"
    if _has_number(b) and _has_any(b, _CONTRAST_TOKENS):
        return "signal"
    if _has_any(b, _APPROVAL_TOKENS):
        return "approval"
    if category and category.lower() in ("policy", "regulation", "economy"):
        if _has_number(b):
            return "signal"
    return "unclear"


def _derive_identity_signal(body: str, strategy_os: dict | None) -> str:
    """Strategy OS positioning+lenses 재조립. 본문에 매칭되는 렌즈가 있으면
    "{렌즈} 관점 독자 — {one_liner}" 로 조립."""
    so = strategy_os if isinstance(strategy_os, dict) else {}
    pos = so.get("positioning") if isinstance(so.get("positioning"), dict) else {}
    one = _safe_str(pos.get("one_liner") if isinstance(pos, dict) else "", 160)
    lenses_raw = pos.get("lenses") if isinstance(pos, dict) else []
    lenses = [str(x).strip() for x in (lenses_raw or []) if isinstance(x, str) and x.strip()]
    b_low = (body or "").lower()
    matched = [l for l in lenses if l.lower() in b_low]
    if matched:
        tail = f" — {one}" if one else ""
        return _clip(f"{matched[0]} 관점 독자{tail}", 120)
    if one:
        return _clip(one, 120)
    return ""


def _derive_hidden_variable(source_pack: dict | None) -> str:
    """숨은 변수 후보. conflicts_or_uncertainty / watch_next 재포장."""
    sp = source_pack if isinstance(source_pack, dict) else {}
    conflicts = sp.get("conflicts_or_uncertainty") if isinstance(sp.get("conflicts_or_uncertainty"), list) else []
    watch = sp.get("watch_next") if isinstance(sp.get("watch_next"), list) else []
    for c in conflicts[:2]:
        cs = _safe_str(c, 160)
        cs = re.sub(r"^\[[a-zA-Z_]+\]\s*", "", cs).strip()
        if cs:
            return _clip(cs, 120)
    for w in watch[:2]:
        ws = _safe_str(w, 160)
        ws = re.sub(r"^\[[a-zA-Z_]+\]\s*", "", ws).strip()
        if ws:
            return _clip(ws, 120)
    return ""


def _derive_stake_sentence(source_pack: dict | None, angle_pack: dict | None) -> str:
    """독자 손익 1줄. watch_next → share_trigger → [opportunity] conflict."""
    sp = source_pack if isinstance(source_pack, dict) else {}
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    watch = sp.get("watch_next") if isinstance(sp.get("watch_next"), list) else []
    for w in watch[:3]:
        ws = _safe_str(w, 200)
        ws = re.sub(r"^\[[a-zA-Z_]+\]\s*", "", ws).strip()
        if ws:
            return _clip(ws, 120)
    st = _safe_str(ap.get("share_trigger"), 200)
    if st:
        return _clip(st, 120)
    conflicts = sp.get("conflicts_or_uncertainty") if isinstance(sp.get("conflicts_or_uncertainty"), list) else []
    for c in conflicts[:3]:
        cs = _safe_str(c, 200)
        if cs.startswith("[opportunity]"):
            cleaned = cs[len("[opportunity]"):].strip()
            if cleaned:
                return _clip(cleaned, 120)
    return ""


def _compute_too_obvious_flag(body: str, linter_labels: dict | None) -> bool:
    """grok_handoff._derive_too_obvious 와 동일 휴리스틱: body>=100자 + 숫자 0."""
    b = _safe_str(body, 2000)
    if len(b) < 100:
        return False
    return not _has_number(b)


def _derive_too_obvious_warning(body: str, linter_labels: dict | None) -> str | None:
    """flag True 일 때 편집장용 행동 지시 1줄. 3 고정 문구 중 하나.

    Phase 4 의 too_obvious_reason 과 동일 로직, 키 명만 변경
    (Phase 5 에서 handoff 블록 명을 '지금 초안이 평평한 이유' 로 재편하면서
    필드명도 편집장 톤 'warning' 으로 통일)."""
    b = _safe_str(body, 2000)
    if len(b) < 100:
        return None
    if not _has_number(b):
        return _TOO_OBVIOUS_REASONS["no_numbers"]
    lab = linter_labels if isinstance(linter_labels, dict) else {}
    flags = lab.get("flags") if isinstance(lab.get("flags"), dict) else {}
    if not _has_any(b, ("숨은", "비대칭", "실제로는", "그 뒤에", "hidden")):
        if flags.get("missing_context_flag") or flags.get("weak_share_value_flag"):
            return _TOO_OBVIOUS_REASONS["no_hidden"]
        if len(re.findall(r"(악화|상승|하락|증가|감소|영향|압박)", b)) >= 3:
            return _TOO_OBVIOUS_REASONS["news_echo"]
    return None


# ─── Phase 5 신규 3 필드 ────────────────────────────────────────────────

def _derive_editorial_goal(angle_pack: dict | None, stake_sentence: str,
                           core_tension: str, share_trigger: str) -> str:
    """이 글을 왜 이 각도로 세게 써야 하는지 1줄.
    winner_angle.reason 우선, 없으면 core_tension + stake 조합.
    영어면 placeholder (handoff 에서 sanitize 가 다시 걸러내지만 안전망)."""
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    wa = ap.get("winner_angle") if isinstance(ap.get("winner_angle"), dict) else {}
    reason = _safe_str(wa.get("reason") if isinstance(wa, dict) else "", 160)
    # heuristic fallback 마커는 제외 (angle_pack.py 가 넣는 placeholder)
    if reason and "heuristic" not in reason.lower() and "fallback" not in reason.lower():
        return _clip(reason, 100)
    # 파생 조합
    ct = _clip(core_tension or "", 40)
    trig = _clip(share_trigger or stake_sentence or "", 40)
    if ct and trig:
        return _clip(f"{ct} → {trig}", 100)
    return ct or trig or ""


def _derive_what_to_sharpen(
    stop_scroll_line: str, hidden_variable: str, stake_sentence: str
) -> list[str]:
    """반드시 세게 밀어야 할 포인트 최대 2개. 행동 동사 앞세움.
    후보 3개 중 비어있지 않은 상위 2개 선택 + 행동 동사 포장."""
    out: list[str] = []
    if _nonempty(stop_scroll_line):
        out.append(_clip(f"첫 줄로 끌어올려라: {stop_scroll_line}", 140))
    if _nonempty(hidden_variable):
        out.append(_clip(f"숨은 변수 명시: {hidden_variable}", 140))
    if _nonempty(stake_sentence):
        out.append(_clip(f"독자 손익 드러내라: {stake_sentence}", 140))
    return out[:2]


# weakness flag → 행동 지시 매핑 (Phase 5 신규)
_CUT_LABELS = {
    "weak_hook":       "약한 훅 문장 삭제 — 숫자·고유명사·대비 들어간 줄로 교체",
    "too_obvious":     "표면 인과 문장 삭제 — 숨은 변수/비대칭 노출 드러내기",
    "missing_context": "고유명사 뒤 1줄 설명 추가 — 링크 없이 읽는 독자 대상",
    "weak_ending":     "엔딩 재작성 — 독자 행동/판단 요구 질문 또는 관전 포인트",
    "generic_cta":     "흔한 CTA 문구 삭제 — 팔로우/구독/좋아요 금지",
    "ai_tone":         "금지 표현 교체 — Strategy OS banned_style 기준",
}

# 우선순위 (치명도 높은 것 먼저)
_CUT_PRIORITY = (
    "weak_hook", "too_obvious", "weak_ending",
    "missing_context", "generic_cta", "ai_tone",
)


def _is_weak_hook(hook: str) -> bool:
    """grok_handoff._derive_weak_hook 와 동일 휴리스틱: 길이 10 미만, 또는
    숫자·대문자·한국 기관명 중 하나도 없음."""
    h = (hook or "").strip()
    if len(h) < 10:
        return True
    has_num = bool(re.search(r"\d", h))
    has_caps = bool(re.search(r"[A-Z]{2,}", h))
    has_kr_entity = bool(
        re.search(r"(정부|은행|금융위|공정위|국회|총리실|산업부|기재부|검찰|경찰|삼성|현대|SK|LG|네이버|카카오)", h)
    )
    return not (has_num or has_caps or has_kr_entity)


def _derive_what_to_cut(
    linter_labels: dict | None,
    too_obvious_flag: bool,
    hook: str = "",
) -> list[str]:
    """감지된 weakness 를 행동 지시 문장으로 최대 3개. 없으면 []."""
    lab = linter_labels if isinstance(linter_labels, dict) else {}
    flags = lab.get("flags") if isinstance(lab.get("flags"), dict) else {}
    ending = lab.get("ending") if isinstance(lab.get("ending"), dict) else {}

    detected: set[str] = set()
    # weak_hook 은 hook 직접 체크 (post_linter 는 이 필드 안 만듦).
    if _is_weak_hook(hook):
        detected.add("weak_hook")
    if too_obvious_flag:
        detected.add("too_obvious")
    if flags.get("missing_context_flag"):
        detected.add("missing_context")
    if flags.get("weak_ending_flag") or ending.get("ending_type") == "question_only":
        detected.add("weak_ending")
    if flags.get("generic_cta_flag"):
        detected.add("generic_cta")
    if flags.get("ai_tone_flag"):
        detected.add("ai_tone")

    out: list[str] = []
    for key in _CUT_PRIORITY:
        if key in detected:
            out.append(_CUT_LABELS[key])
        if len(out) >= 3:
            break
    return out


# ─── salvageability ─────────────────────────────────────────────────────

_LABEL_KR = {
    "has_frame":       "frame 부재",
    "has_rt_motive":   "RT 동기 불명확",
    "has_stake":       "독자 스테이크 부재",
    "has_hidden_var":  "숨은 변수 부재",
    "has_context":     "회사/기관 맥락 부족",
    "has_perspective": "주류 요약 반복(관점 부재)",
}


def _score_salvageability(
    *,
    angle_pack: dict | None,
    stake_sentence: str,
    hidden_variable: str,
    rt_motive_type: str,
    linter_labels: dict | None,
    too_obvious_flag: bool,
) -> dict[str, Any]:
    """6 항목 체크리스트. A=5~6 / B=3~4 / C=0~2."""
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    lab = linter_labels if isinstance(linter_labels, dict) else {}
    flags = lab.get("flags") if isinstance(lab.get("flags"), dict) else {}
    company = lab.get("company_context") if isinstance(lab.get("company_context"), dict) else {}

    has_frame = (
        isinstance(ap.get("frame_type"), str) and bool(ap.get("frame_type"))
        and ap.get("method") != "heuristic_en_blocked"
    )
    has_stake = _nonempty(stake_sentence)
    has_hidden = _nonempty(hidden_variable)
    has_rt_motive = bool(rt_motive_type) and rt_motive_type != "unclear"
    has_context = (
        not flags.get("missing_context_flag")
        and not (company.get("entities_requiring_context") or [])
    )
    has_perspective = (
        not flags.get("ai_tone_flag")
        and not too_obvious_flag
    )

    checks = {
        "has_frame": has_frame,
        "has_stake": has_stake,
        "has_hidden_var": has_hidden,
        "has_rt_motive": has_rt_motive,
        "has_context": has_context,
        "has_perspective": has_perspective,
    }
    score = sum(1 for v in checks.values() if v)
    grade = "A" if score >= 5 else ("B" if score >= 3 else "C")

    # reason 에는 grade prefix 없음 (뱃지 쪽에서 "## 🎯 살릴 가치: {grade} — {reason}"
    # 로 조립하므로 중복 회피).
    missing = [_LABEL_KR[k] for k, v in checks.items() if not v][:2]
    if grade == "A":
        reason = "핵심 요소 대부분 확보. 훅 리듬/마감만 다듬기."
        if missing:
            reason = f"{' / '.join(missing)} 보완 시 상위권."
    elif grade == "B":
        reason = "재각도 또는 구조 재배열 권장."
        if missing:
            reason = f"{' / '.join(missing)} 보완 필요."
    else:
        reason = "brief 또는 reject 권장."
        if missing:
            reason = f"{' / '.join(missing)}. 재각도/reject 권장."

    return {
        "score": grade,
        "reason": _clip(reason, 160),
        "checks": checks,
    }


# ─── 엔트리 포인트 ─────────────────────────────────────────────────────

def build_editorial_meta(
    *,
    hook: str | None,
    body: str | None,
    source_pack: dict | None = None,
    angle_pack: dict | None = None,
    linter_labels: dict | None = None,
    strategy_os: dict | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """
    7 필드 + salvageability 를 한 dict 로 반환.
    각 파생 함수는 try/except 로 감싸 개별 실패 허용. 반환은 항상 유효.
    """
    h = _safe_str(hook, 400)
    b = _safe_str(body, 3000)

    out: dict[str, Any] = {
        "meta_version": META_VERSION,
        "stop_scroll_line": "",
        "rt_motive_type": "unclear",
        "identity_signal": "",
        "hidden_variable": "",
        "stake_sentence": "",
        "too_obvious_flag": False,
        "too_obvious_warning": None,     # Phase 5: reason → warning 리네이밍
        "editorial_goal": "",             # Phase 5 신규
        "what_to_sharpen": [],            # Phase 5 신규 (max 2)
        "what_to_cut": [],                # Phase 5 신규 (max 3)
        "salvageability": {"score": "C", "reason": "", "checks": {}},
    }

    try:
        out["stop_scroll_line"] = _derive_stop_scroll_line(h, angle_pack)
    except Exception as e:
        logger.warning(f"[editorial_meta] stop_scroll_line 실패: {e}")
    try:
        out["rt_motive_type"] = _derive_rt_motive(b, category, linter_labels, strategy_os)
    except Exception as e:
        logger.warning(f"[editorial_meta] rt_motive_type 실패: {e}")
    try:
        out["identity_signal"] = _derive_identity_signal(b, strategy_os)
    except Exception as e:
        logger.warning(f"[editorial_meta] identity_signal 실패: {e}")
    try:
        out["hidden_variable"] = _derive_hidden_variable(source_pack)
    except Exception as e:
        logger.warning(f"[editorial_meta] hidden_variable 실패: {e}")
    try:
        out["stake_sentence"] = _derive_stake_sentence(source_pack, angle_pack)
    except Exception as e:
        logger.warning(f"[editorial_meta] stake_sentence 실패: {e}")
    try:
        out["too_obvious_flag"] = _compute_too_obvious_flag(b, linter_labels)
    except Exception as e:
        logger.warning(f"[editorial_meta] too_obvious_flag 실패: {e}")
    try:
        if out["too_obvious_flag"]:
            out["too_obvious_warning"] = _derive_too_obvious_warning(b, linter_labels)
    except Exception as e:
        logger.warning(f"[editorial_meta] too_obvious_warning 실패: {e}")

    # ── Phase 5 신규 3 필드 ─────────────────────────────────
    try:
        ap = angle_pack if isinstance(angle_pack, dict) else {}
        out["editorial_goal"] = _derive_editorial_goal(
            angle_pack=ap,
            stake_sentence=out["stake_sentence"],
            core_tension=_safe_str(ap.get("core_tension"), 200),
            share_trigger=_safe_str(ap.get("share_trigger"), 200),
        )
    except Exception as e:
        logger.warning(f"[editorial_meta] editorial_goal 실패: {e}")
    try:
        out["what_to_sharpen"] = _derive_what_to_sharpen(
            out["stop_scroll_line"],
            out["hidden_variable"],
            out["stake_sentence"],
        )
    except Exception as e:
        logger.warning(f"[editorial_meta] what_to_sharpen 실패: {e}")
    try:
        out["what_to_cut"] = _derive_what_to_cut(
            linter_labels, out["too_obvious_flag"], hook=h,
        )
    except Exception as e:
        logger.warning(f"[editorial_meta] what_to_cut 실패: {e}")

    try:
        out["salvageability"] = _score_salvageability(
            angle_pack=angle_pack,
            stake_sentence=out["stake_sentence"],
            hidden_variable=out["hidden_variable"],
            rt_motive_type=out["rt_motive_type"],
            linter_labels=linter_labels,
            too_obvious_flag=out["too_obvious_flag"],
        )
    except Exception as e:
        logger.warning(f"[editorial_meta] salvageability 실패: {e}")

    # 영어 누출 차단 — handoff 사용자 노출 필드 한국어 강제 (fail-open)
    try:
        from app.services.angle_pack import _ensure_korean
        if out.get("editorial_goal"):
            out["editorial_goal"] = _ensure_korean(out["editorial_goal"])
        if out.get("hidden_variable"):
            out["hidden_variable"] = _ensure_korean(out["hidden_variable"])
        if out.get("stake_sentence"):
            out["stake_sentence"] = _ensure_korean(out["stake_sentence"])
        if out.get("stop_scroll_line"):
            out["stop_scroll_line"] = _ensure_korean(out["stop_scroll_line"])
    except Exception as e:
        logger.warning(f"[editorial_meta] 한국어 강제 실패 (무시): {e}")

    return out
