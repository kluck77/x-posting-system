"""
Grok Handoff
============
source_pack + angle_pack + final_body 를 Grok (x.ai) 편집용 **편집 카드**로
렌더링한다. "리서치 보고서" 가 아니라 "원문 + 각도 + 편집 규칙" 만 담는다.

제공 함수:
  format_handoff(source_pack, angle_pack, final_body) -> str
  compose_enriched_source(original, source_pack, winner_angle) -> str
  compose_pack_context(source_pack, winner_angle) -> str

원칙:
- format_handoff 출력 상한: <= 1800자 (Grok 프롬프트에 바로 붙일 수 있는 크기).
- 5개 고정 블록 + 최대 2개 선택 블록 구조 유지.
- URL 덤프 / 소스 리스트 / 긴 영어 분석 / >10 bullet 금지.
- 모든 함수는 pure string 반환. 예외 던지지 않는다.
- pack dict 누락 키는 빈 블록으로 처리.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.handoff_quality_guard import run_quality_guard

_HANDOFF_MAX = 1800         # 본문(초안) 버짓 계산 기준 — 고정 5블록 + 선택 2블록 가정
_HANDOFF_HARD_MAX = 2800    # 최종 하드 상한 (새 compact 편집 신호 3블록 포함)
_BODY_MAX = 900
_BLOCK_LINE_MAX = 160
_URL_RE = re.compile(r"https?://\S+")

# Phase 5: 한국어 비율 체크 — 편집장 handoff 는 한국어만.
_ALPHA_ONLY_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[\w가-힣]")
_KO_RE = re.compile(r"[가-힣]")
_NEED_KOREAN_THRESHOLD = 0.5


def _strip_urls(s: str) -> str:
    return _URL_RE.sub("", str(s)).strip()


def _drop_url_only(items: Any) -> list:
    if not isinstance(items, list):
        return []
    out = []
    for x in items:
        s = _strip_urls(str(x).strip())
        if s:
            out.append(s)
    return out


# ─── Phase 5: sanitize for editor ─────────────────────────────────────

def _korean_ratio(text: str) -> float:
    """(한글 문자) / (공백·구두점 제외 실제 문자) 비율. 없으면 0.0."""
    if not isinstance(text, str) or not text:
        return 0.0
    ko = len(_KO_RE.findall(text))
    total = len(_WORD_RE.findall(text))
    return (ko / total) if total else 0.0


def _sanitize_ko(text: Any, *, label: str = "원문", fallback: str = "") -> str:
    """영어 dominant 텍스트를 편집장용 placeholder 로 대체.
    한국어 토큰이 하나라도 있으면 혼합 표기 그대로 유지 (고유명사·영문 용어는
    편집장이 한국어 문맥에서 이해 가능). 한글 0 + 영어 5자+ 일 때만 placeholder.

    결과: `"{label} 영어 — 편집장 한국어 압축 필요"` 고정 문구 (번역하지 않음).
    """
    s = str(text or "").strip()
    if not s:
        return fallback
    has_ko = bool(_KO_RE.search(s))
    alpha = len(_ALPHA_ONLY_RE.findall(s))
    if not has_ko and alpha >= 5:
        return f"{label} 영어 — 편집장 한국어 압축 필요"
    return s


def _reformat_unverified(items: Any) -> list[str]:
    """`[unverified] X` → `X는 현재 검증 부족` 한국어 재포맷.
    `[en] X` → `원문 영어 — 한국어 압축 필요`.
    기타 태그는 제거만 하고 본문 노출 (한국어면 유지, 영어면 sanitize)."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        s = _strip_urls(s)
        if s.startswith("[unverified]"):
            body = s[len("[unverified]"):].strip()
            # 한글 토큰이 하나라도 있으면 그대로 "~는 현재 검증 부족" 접미사.
            # (인명/회사명이 영어여도 한국어 본문 안에 있으면 편집장이 이해함.)
            # 한글 0 이면 영어 dominant 로 간주 → placeholder.
            if len(_KO_RE.findall(body)) >= 1:
                out.append(f"{body}는 현재 검증 부족")
            else:
                out.append(f"원문 영어 — 한국어 압축 필요 ({_clip_head(body, 40)})")
            continue
        if s.startswith("[en]"):
            body = s[len("[en]"):].strip()
            out.append(f"원문 영어 — 한국어 압축 필요 ({_clip_head(body, 40)})")
            continue
        # 일반 태그 prefix 제거
        cleaned = re.sub(r"^\[[a-zA-Z_]+\]\s*", "", s).strip()
        if not cleaned:
            continue
        # 영어 dominant 면 placeholder
        if _korean_ratio(cleaned) < _NEED_KOREAN_THRESHOLD and len(_ALPHA_ONLY_RE.findall(cleaned)) >= 5:
            out.append(f"원문 영어 — 한국어 압축 필요 ({_clip_head(cleaned, 40)})")
        else:
            out.append(cleaned)
    return out


def _clip_head(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _dedupe_evidence(items: Any, *, limit: int = 2) -> list[str]:
    """evidence 블록 중복 제거. 앞 40자 normalize 기준 dedupe, 최대 limit.
    영어 dominant 항목은 제외 (handoff 한국어 원칙)."""
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        s = _strip_urls(s)
        # 영어 dominant 제외
        if _korean_ratio(s) < _NEED_KOREAN_THRESHOLD and len(_ALPHA_ONLY_RE.findall(s)) >= 5:
            continue
        # 정규화: 공백 1칸 + 앞 40자
        norm = re.sub(r"\s+", " ", s).lower()[:40]
        if norm in seen:
            continue
        seen.add(norm)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _safe(val: Any, limit: int = 300) -> str:
    if val is None:
        return ""
    return str(val).strip()[:limit]


def _compact_bullets(items: Any, limit: int = 3, max_len: int = _BLOCK_LINE_MAX) -> list[str]:
    if not items or not isinstance(items, list):
        return []
    out: list[str] = []
    for x in items[:limit]:
        s = str(x).strip()
        if not s:
            continue
        out.append(f"- {s[:max_len]}")
    return out


def compose_pack_context(source_pack: dict, winner_angle: dict) -> str:
    """
    DraftWriter / Reviewer 의 criteria_context 에 주입할 텍스트 블록.
    기존 criteria_context 에 append 되는 형태로 쓰인다.
    """
    sp = source_pack if isinstance(source_pack, dict) else {}
    wa = winner_angle if isinstance(winner_angle, dict) else {}

    parts = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "PACK CONTEXT (Phase 1.1 — Structure-Aware)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "[Winner Angle]",
        f"  angle:  {_safe(wa.get('angle'), 200)}",
        f"  reason: {_safe(wa.get('reason'), 240)}",
        f"  score:  {wa.get('score', 'n/a')}",
        "",
        "[Confirmed Facts]",
    ]
    bullets = _compact_bullets(sp.get("confirmed_facts"), limit=6, max_len=200) or ["  (none)"]
    parts.extend([f"  {b}" if not b.startswith(" ") else b for b in bullets])
    parts += ["", "[Conflicts / Uncertainty]"]
    bullets = _compact_bullets(sp.get("conflicts_or_uncertainty"), limit=5, max_len=200) or ["  (none)"]
    parts.extend([f"  {b}" if not b.startswith(" ") else b for b in bullets])
    parts += ["", "[Korea Angle]"]
    bullets = _compact_bullets(sp.get("korea_angle"), limit=3, max_len=200) or ["  (none)"]
    parts.extend([f"  {b}" if not b.startswith(" ") else b for b in bullets])
    parts += ["", "[Global Angle]"]
    bullets = _compact_bullets(sp.get("global_angle"), limit=3, max_len=200) or ["  (none)"]
    parts.extend([f"  {b}" if not b.startswith(" ") else b for b in bullets])
    parts += ["", "[Watch Next]"]
    bullets = _compact_bullets(sp.get("watch_next"), limit=3, max_len=200) or ["  (none)"]
    parts.extend([f"  {b}" if not b.startswith(" ") else b for b in bullets])

    hp = _safe(sp.get("historical_parallel"), 240)
    if hp:
        parts += ["", "[Historical Parallel]", f"  - {hp}"]
    ct = _safe(sp.get("concept_translation"), 240)
    if ct:
        parts += ["", "[Concept Translation]", f"  - {ct}"]
    ep = sp.get("evidence_pack") or []
    if isinstance(ep, list) and ep:
        parts += ["", "[Evidence Pack]"]
        for e in ep[:5]:
            parts.append(f"  - {str(e).strip()[:200]}")
    cs = _safe(sp.get("closing_signal"), 240)
    if cs:
        parts += ["", "[Closing Signal]", f"  - {cs}"]

    parts += [
        "",
        "Rules:",
        "  - Ground every claim in Confirmed Facts.",
        "  - Treat Conflicts as open questions — do NOT assert them as fact.",
        "  - Use Winner Angle as the framing lens.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(parts)


def compose_enriched_source(original: str, source_pack: dict, winner_angle: dict) -> str:
    """
    DraftWriter.generate_draft(source_text=...) 로 주입할 enriched 원문.
    원문 앞에 짧은 pack summary block 을 붙인다.
    """
    sp = source_pack if isinstance(source_pack, dict) else {}
    wa = winner_angle if isinstance(winner_angle, dict) else {}

    confirmed = sp.get("confirmed_facts") or []
    conflicts = sp.get("conflicts_or_uncertainty") or []
    hp = _safe(sp.get("historical_parallel"), 200)
    ct = _safe(sp.get("concept_translation"), 200)
    ep = sp.get("evidence_pack") or []
    cs = _safe(sp.get("closing_signal"), 200)

    header = [
        "=== PACK BRIEF ===",
        f"Winner angle: {_safe(wa.get('angle'), 200)}",
    ]
    if confirmed:
        header.append("Key confirmed facts:")
        for f in confirmed[:4]:
            s = str(f).strip()
            if s:
                header.append(f"  - {s[:200]}")
    if conflicts:
        header.append("Open questions / uncertainty:")
        for c in conflicts[:3]:
            s = str(c).strip()
            if s:
                header.append(f"  - {s[:200]}")
    if hp:
        header.append(f"Historical parallel: {hp}")
    if ct:
        header.append(f"Concept in one line: {ct}")
    if isinstance(ep, list) and ep:
        header.append("Evidence to lean on:")
        for e in ep[:3]:
            s = str(e).strip()
            if s:
                header.append(f"  - {s[:200]}")
    if cs:
        header.append(f"Closing signal: {cs}")
    header.append("=== ORIGINAL SOURCE ===")

    terminator = "=== ORIGINAL SOURCE ==="
    pack_block = "\n".join(header)
    # pack_block 상한 ~1100자 방어 (Phase 1.1 새 필드 반영 여유). 잘려도 terminator 는 보존.
    if len(pack_block) > 1100:
        pack_block = pack_block[:1100].rstrip()
        if not pack_block.endswith(terminator):
            pack_block = pack_block + "\n" + terminator

    orig = original or ""
    return f"{pack_block}\n{orig}"


def _truncate_to(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ── 편집 신호 (editorial signals) — compact 블록 ───────────────────────────
# 원칙: 정보 추가 아님, "편집 신호" 만. 값 비면 블록 전체 생략. 1줄 중심.
# 주의: core_tension / share_trigger 는 기존 `## 이 글의 핵심 각도` 블록에
#       이미 포함되므로 중복 금지 — 추가 신호는 editorial_goal 1줄뿐.

def _clip_line(s: Any, n: int) -> str:
    s = str(s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _derive_editorial_goal(ap: dict) -> str:
    """reason 이 있으면 그것, 없으면 core_tension + share_trigger 간이 조합.
    정보 추가 없이 기존 필드 재배치. 없으면 "" 리턴."""
    if not isinstance(ap, dict):
        return ""
    wa = ap.get("winner_angle") if isinstance(ap.get("winner_angle"), dict) else {}
    reason = _clip_line(wa.get("reason") if isinstance(wa, dict) else "", 80)
    if reason:
        return reason
    ct = _clip_line(ap.get("core_tension"), 40)
    st = _clip_line(ap.get("share_trigger"), 40)
    if ct and st:
        return _clip_line(f"{ct} → {st}", 80)
    return ct or st or ""


def _derive_weak_hook(hook: str) -> bool:
    h = (hook or "").strip()
    if len(h) < 10:
        return True
    has_num = bool(re.search(r"\d", h))
    has_caps = bool(re.search(r"[A-Z]{2,}", h))
    has_kr_entity = bool(
        re.search(r"(정부|은행|금융위|공정위|국회|총리실|산업부|기재부|검찰|경찰|삼성|현대|SK|LG|네이버|카카오)", h)
    )
    if not has_num and not has_caps and not has_kr_entity:
        return True
    return False


def _derive_too_obvious(body: str) -> bool:
    b = (body or "").strip()
    if len(b) < 100:
        return False
    has_num = bool(re.search(r"\d", b))
    return not has_num


_WEAKNESS_LABELS = {
    "weak_hook":       "훅이 짧거나 숫자/고유명사 없음 → 긴장선 올릴 것",
    "too_obvious":     "표면 인과만 — 숨은 변수/비대칭 노출 드러낼 것",
    "missing_context": "링크 없이 읽는 독자에게 맥락 부족",
    "weak_ending":     "엔딩 약함 — 결론 진술 또는 구체 관전 포인트로",
    "generic_cta":     "흔한 CTA 감지 — 제거 또는 구체 액션으로",
    "ai_tone":         "금지 표현 감지 — 다듬을 것",
}


def _build_account_tone_block(strategy_os: dict | None) -> list[str]:
    """## 우리 계정 편집 우선순위 — positioning.one_liner 1줄 + 훅 2개 + 금지 3개.
    Phase 5: 헤더 '우리 계정 편집 우선순위' 로 변경 ('계정 톤' → 편집장 톤)."""
    so = strategy_os if isinstance(strategy_os, dict) else {}
    pos = so.get("positioning") if isinstance(so.get("positioning"), dict) else {}
    one = _clip_line(pos.get("one_liner") if isinstance(pos, dict) else "", 160)
    # 영어 dominant one_liner 는 sanitize 로 placeholder
    if one:
        one = _sanitize_ko(one, label="포지셔닝 원문")
    hooks_raw = so.get("hook_library") if isinstance(so.get("hook_library"), list) else []
    banned_raw = so.get("banned_style") if isinstance(so.get("banned_style"), list) else []
    hooks = [str(x).strip() for x in hooks_raw if isinstance(x, str) and x.strip()][:2]
    banned = [str(x).strip() for x in banned_raw if isinstance(x, str) and x.strip()][:3]
    lines: list[str] = []
    if one:
        lines.append(f"- 정의: {one}")
    if hooks:
        lines.append("- 훅 참고: " + " | ".join(_clip_line(h, 60) for h in hooks))
    if banned:
        lines.append("- 금지 표현: " + ", ".join(_clip_line(b, 40) for b in banned))
    if not lines:
        return []
    return ["## 우리 계정 편집 우선순위", *lines]


# ── Phase 5: editorial_meta 기반 편집장 지시서 블록 ────────────────────
# 원칙: editorial_meta 가 None/비면 블록 없음 (회귀). salvageability 블록은
# 맨 아래로 이동 (뱃지 1줄 → 다단 블록).

def _build_why_push_block(
    editorial_meta: dict | None,
    *,
    angle_pack: dict | None = None,
) -> list[str]:
    """## 🔥 왜 이 글을 세게 써야 하는가 — editorial_goal + core_tension +
    share_trigger + RT 동기/정체성 신호.

    Phase 5.1: spec 준수를 위해 core_tension / share_trigger 를 섹션 2 '핵심
    각도' 와 중복으로 여기에도 재노출한다. 섹션 2 는 구조 정보, 섹션 6 은
    편집장 지시 톤 — 편집장이 지시를 한눈에 받도록.
    """
    em = editorial_meta if isinstance(editorial_meta, dict) else {}
    ap = angle_pack if isinstance(angle_pack, dict) else {}

    goal = _sanitize_ko(em.get("editorial_goal", ""), label="편집 목표", fallback="")
    if goal.endswith("한국어 압축 필요"):
        goal = ""

    # Phase 5.1: 섹션 6 에 core_tension / share_trigger 재노출 (spec 요구)
    ct = _sanitize_ko(_safe(ap.get("core_tension"), 240), label="핵심 긴장", fallback="")
    if ct.endswith("한국어 압축 필요"):
        ct = ""
    st = _sanitize_ko(
        _strip_urls(_safe(ap.get("share_trigger"), 200)),
        label="공유 트리거",
        fallback="",
    )
    if st.endswith("한국어 압축 필요"):
        st = ""

    rt_type = em.get("rt_motive_type") if isinstance(em.get("rt_motive_type"), str) else ""
    identity = _clip_line(em.get("identity_signal", ""), 120)
    if identity:
        identity = _sanitize_ko(identity, label="정체성 시그널", fallback="")
        if identity.endswith("한국어 압축 필요"):
            identity = ""

    lines: list[str] = []
    if goal:
        lines.append(f"- 편집 목표: {_clip_line(goal, 120)}")
    if ct:
        lines.append(f"- 핵심 긴장: {_clip_line(ct, 100)}")
    if st:
        lines.append(f"- 공유 트리거: {_clip_line(st, 100)}")
    if rt_type and rt_type != "unclear":
        lines.append(f"- RT 동기: {rt_type}")
    if identity:
        lines.append(f"- 정체성 시그널: {identity}")
    if not lines:
        return []
    return ["## 🔥 왜 이 글을 세게 써야 하는가", *lines]


def _build_why_flat_block(editorial_meta: dict | None) -> list[str]:
    """## 🏴 지금 초안이 평평한 이유 — too_obvious_warning + what_to_cut(≤3).
    모두 비면 블록 전체 생략."""
    em = editorial_meta if isinstance(editorial_meta, dict) else {}
    warning = _clip_line(em.get("too_obvious_warning") or "", 160)
    cuts_raw = em.get("what_to_cut") if isinstance(em.get("what_to_cut"), list) else []
    cuts = [str(c).strip() for c in cuts_raw if isinstance(c, str) and c.strip()][:3]
    lines: list[str] = []
    if warning:
        lines.append(f"- {warning}")
    for c in cuts:
        lines.append(f"- 잘라라: {_clip_line(c, 140)}")
    if not lines:
        return []
    return ["## 🏴 지금 초안이 평평한 이유", *lines]


def _build_must_keep_block(editorial_meta: dict | None) -> list[str]:
    """## 💎 반드시 살릴 포인트 — stop_scroll_line + hidden_variable +
    stake_sentence + what_to_sharpen(≤2). 비면 []."""
    em = editorial_meta if isinstance(editorial_meta, dict) else {}
    stop_line = _sanitize_ko(em.get("stop_scroll_line", ""), label="훅 후보", fallback="")
    if stop_line.endswith("한국어 압축 필요"):
        stop_line = ""
    stop_line = _clip_line(stop_line, 90)
    hidden = _clip_line(em.get("hidden_variable", ""), 120)
    stake = _clip_line(em.get("stake_sentence", ""), 120)
    sharpen_raw = em.get("what_to_sharpen") if isinstance(em.get("what_to_sharpen"), list) else []
    sharpen = [str(s).strip() for s in sharpen_raw if isinstance(s, str) and s.strip()][:2]
    lines: list[str] = []
    if stop_line:
        lines.append(f"- 훅 후보: {stop_line}")
    if hidden:
        lines.append(f"- 숨은 변수: {hidden}")
    if stake:
        lines.append(f"- 독자 스테이크: {stake}")
    for s in sharpen:
        lines.append(f"- 세게 밀어라: {_clip_line(s, 140)}")
    if not lines:
        return []
    return ["## 💎 반드시 살릴 포인트", *lines]


def _build_salvageability_block(editorial_meta: dict | None) -> list[str]:
    """## 🎯 살릴 가치 — Phase 5: 상단 뱃지 1줄 → 맨 아래 블록 (score + reason).
    meta/점수 비면 []."""
    em = editorial_meta if isinstance(editorial_meta, dict) else {}
    salv = em.get("salvageability") if isinstance(em.get("salvageability"), dict) else {}
    grade = salv.get("score")
    if grade not in ("A", "B", "C"):
        return []
    reason = _clip_line(salv.get("reason", ""), 160)
    lines = [f"- 등급: {grade}"]
    if reason:
        lines.append(f"- 사유: {reason}")
    return ["## 🎯 살릴 가치", *lines]


def format_handoff(
    source_pack: dict,
    angle_pack: dict,
    final_body: str,
    *,
    final_hook: str | None = None,
    strategy_os: dict | None = None,
    linter_labels: dict | None = None,
    editorial_meta: dict | None = None,
) -> str:
    """
    Grok (x.ai) 편집용 handoff. 복사-붙여넣기로 바로 쓰는 **편집 카드**.

    고정 5블록 (항상 포함):
      ## 원문 초안
      ## 이 글의 핵심 각도
      ## 절대 바꾸지 말 것
      ## 바꿔도 되는 것
      ## 최종 출력 규칙

    선택 블록 (있을 때만, 최대 2개):
      ## 어려운 개념 한 줄 번역
      ## 핵심 근거 2~3개

    편집 신호 블록 (optional 인자 공급 시, 값 비면 생략):
      ## 편집 신호             — 핵심 긴장 / 공유 트리거 / 편집 목표
      ## 시스템이 감지한 약한 지점  — 탐지된 weakness 만
      ## 계정 톤 (참고)         — Strategy OS compact

    Phase 4 blocks (editorial_meta 공급 시, 값 비면 생략):
      ## 🎯 살릴 가치: A/B/C — reason   (상단, 재료 품질 경고 바로 뒤)
      ## 🔥 이 글을 RT 하게 만드는 이유
      ## 🏴 지금 초안이 평평한 이유
      ## 💎 반드시 살릴 포인트

    상한: 1800자(body 버짓 계산) / 2800자(최종 하드 상한, 새 블록 포함).
    금지: URL 덤프 / 소스 리스트 / 긴 영어 분석 / >10 bullet / "research report" 톤.
    """
    sp = source_pack if isinstance(source_pack, dict) else {}
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    wa = ap.get("winner_angle") if isinstance(ap.get("winner_angle"), dict) else {}

    body_raw = _strip_urls((final_body or "").strip())
    body = _truncate_to(body_raw, _BODY_MAX)

    winner = _strip_urls(_safe(wa.get("angle"), 200)) or "(not set)"
    core_tension = _strip_urls(_safe(ap.get("core_tension"), 240))
    frame_type = _safe(ap.get("frame_type"), 40) or "underreported_angle"
    readability_risk = _safe(ap.get("readability_risk"), 20) or "medium"
    share_trigger = _strip_urls(_safe(ap.get("share_trigger"), 200))
    scan_pattern = _strip_urls(_safe(ap.get("scan_pattern"), 200))
    spine = ap.get("story_spine") if isinstance(ap.get("story_spine"), list) else []
    spine_str = " → ".join(str(p).strip()[:20] for p in spine[:6]) if spine else ""

    # Phase 5: sanitize + reformat.
    # - confirmed: [unverified] → "~는 현재 검증 부족", 영어 dominant → placeholder
    # - conflicts: 영어 dominant 는 block 에서 제외 (미확정 예시로 쓰지 않음)
    # - concept_translation: 영어 dominant 면 블록 생략
    # - evidence_pack: 의미 중복 제거 + 영어 dominant 제외 후 max 2
    confirmed = _reformat_unverified(sp.get("confirmed_facts") or [])
    conflicts = _drop_url_only(sp.get("conflicts_or_uncertainty") or [])
    ct_raw = _strip_urls(_safe(sp.get("concept_translation"), 220))
    ct = _sanitize_ko(ct_raw, label="개념 설명", fallback="")
    # ct 가 placeholder ("~한국어 압축 필요") 이면 블록 자체 생략
    if ct.endswith("한국어 압축 필요"):
        ct = ""
    ep = _dedupe_evidence(sp.get("evidence_pack") or [], limit=2)

    # ── ## 원문 초안 ────────────────────────────────────────
    section_draft = [
        "## 원문 초안",
        "```",
        body if body else "(empty)",
        "```",
    ]

    # ── ## 이 글의 핵심 각도 (sanitize 적용) ─────────────────
    # Phase 5: 각 필드 한국어 보장. 영어 dominant 필드는 placeholder 로.
    # "편집 목표" 줄은 신규 '## 왜 이 글을 세게 써야 하는가' 블록으로 이동 — 여기서 제거.
    section_angle = ["## 이 글의 핵심 각도"]
    section_angle.append(f"- 앵글: {_sanitize_ko(winner, label='앵글 원문')}")
    if core_tension:
        section_angle.append(f"- 핵심 긴장: {_sanitize_ko(core_tension, label='핵심 긴장 원문')}")
    section_angle.append(f"- frame: {frame_type}")
    if spine_str:
        section_angle.append(f"- 뼈대: {spine_str}")
    section_angle.append(f"- 가독성 리스크: {readability_risk}")
    if share_trigger:
        section_angle.append(f"- 공유 트리거: {_sanitize_ko(share_trigger, label='공유 트리거 원문')}")

    # ── ## 절대 바꾸지 말 것 ────────────────────────────────
    # Phase 5: [unverified] / 영어 원문 없이 한국어 문장만.
    section_lock: list[str] = ["## 절대 바꾸지 말 것"]
    lock_bullets = _compact_bullets(confirmed, limit=4, max_len=180)
    if lock_bullets:
        section_lock.extend(lock_bullets)
    else:
        section_lock.append("- (확정 사실이 공급되지 않음 — 새 숫자/고유명사 추가 금지)")
    section_lock.append("- 숫자·고유명사·날짜는 초안 그대로 유지")

    # ── ## 바꿔도 되는 것 ──────────────────────────────────
    section_free: list[str] = ["## 바꿔도 되는 것"]
    section_free.append("- 문장 길이·리듬·줄바꿈 (모바일 스캔 중심)")
    if scan_pattern and _korean_ratio(scan_pattern) >= _NEED_KOREAN_THRESHOLD:
        section_free.append(f"- 스캔 패턴 힌트: {scan_pattern}")
    section_free.append("- 훅/클로저 문장 (사실 추가 없이 어휘만)")
    if conflicts:
        # Phase 5: 영어 dominant conflict 는 예시로 쓰지 않음 — 한국어 conflict 만.
        c0_candidates = [c for c in conflicts[:3]
                         if _korean_ratio(str(c)) >= _NEED_KOREAN_THRESHOLD]
        if c0_candidates:
            c0 = re.sub(r"^\[[a-zA-Z_]+\]\s*", "", str(c0_candidates[0])).strip()[:160]
            if c0:
                section_free.append(f"- 미확정 항목은 헤지 동사로 (예: {c0})")

    # ── ## 최종 출력 규칙 ──────────────────────────────────
    section_rules = [
        "## 최종 출력 규칙",
        "- 한국어 한 편, 280~700자 범위",
        "- 새로운 사실/숫자/인용 추가 금지",
        "- 미확정 항목은 단정하지 말고 '~로 보임 / ~할 가능성 / ~로 추정' 톤",
        "- 마지막 줄은 독자가 공유하고 싶어질 한 문장",
    ]

    # 선택 블록 (최대 2개)
    optional_sections: list[list[str]] = []
    if ct:
        optional_sections.append([
            "## 어려운 개념 한 줄 번역",
            f"- {ct}",
        ])
    if isinstance(ep, list) and ep:
        ev_block = ["## 핵심 근거 2~3개"]
        for e in ep[:3]:
            s = str(e).strip()
            if s:
                ev_block.append(f"- {s[:180]}")
        if len(ev_block) > 1:
            optional_sections.append(ev_block)

    # 고정 4블록 (원문 초안 제외) 먼저 고정
    fixed_tail = [
        "\n".join(section_angle),
        "\n".join(section_lock),
        "\n".join(section_free),
        "\n".join(section_rules),
    ]
    # 본문 섹션은 남은 예산에 맞게 다시 잘라낸다 (고정 5블록 보존이 최우선)
    tail_text = "\n\n".join(fixed_tail)
    # 여유: "## 원문 초안\n```\n...\n```\n\n" 의 스캐폴드 (~20자) 감안
    scaffold_len = len("## 원문 초안\n```\n\n```\n\n")
    body_budget = _HANDOFF_MAX - len(tail_text) - scaffold_len
    if body_budget < 120:
        body_budget = 120  # 최소한 짧은 요약은 남김
    body = _truncate_to(body, body_budget)
    section_draft = [
        "## 원문 초안",
        "```",
        body if body else "(empty)",
        "```",
    ]

    # Phase 1: 재료 품질 가드 — source_pack + angle_pack 병합해서 검사.
    # 4종 결함 감지 시 맨 앞에 ## ⚠️ 재료 품질 경고 블록 prepend.
    # 정상 draft (결함 0) 는 빈 문자열 → 기존 동작과 완전 동일.
    try:
        _guard_input = dict(sp) if isinstance(sp, dict) else {}
        if isinstance(ap, dict):
            _guard_input["angle_pack"] = ap
        _quality = run_quality_guard(_guard_input)
        _warning_block_text = _quality.get("rendered_warning_block", "") or ""
    except Exception:
        _warning_block_text = ""

    chunks: list[str] = []
    if _warning_block_text:
        chunks.append(_warning_block_text)

    # Phase 5: 고정 5 블록 (원문/각도/lock/free/rules) + 선택 2 블록 먼저.
    chunks.extend(["\n".join(section_draft)] + fixed_tail)
    for opt in optional_sections[:2]:
        chunks.append("\n".join(opt))

    # Phase 5: editorial_meta 기반 편집장 지시서 블록들.
    # 순서: 왜 세게 → 평평한 이유 → 반드시 살릴 → 우리 계정 편집 우선순위 → 살릴 가치
    phase5_blocks = [
        _build_why_push_block(editorial_meta, angle_pack=ap),
        _build_why_flat_block(editorial_meta),
        _build_must_keep_block(editorial_meta),
        _build_account_tone_block(strategy_os),
        _build_salvageability_block(editorial_meta),
    ]
    for pb in phase5_blocks:
        if pb:
            chunks.append("\n".join(pb))

    out = "\n\n".join(chunks)

    # 길이 제한 — 뒤(선택 블록 + 편집장 지시서 블록)부터 잘라낸다.
    # 고정 5 블록 + (경고 블록 있으면 1) 은 유지.
    _min_keep = 5 + (1 if _warning_block_text else 0)
    while len(out) > _HANDOFF_HARD_MAX and len(chunks) > _min_keep:
        chunks.pop()
        out = "\n\n".join(chunks)

    if len(out) > _HANDOFF_HARD_MAX:
        out = _truncate_to(out, _HANDOFF_HARD_MAX)
    return out
