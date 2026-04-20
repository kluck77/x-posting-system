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


def _build_weakness_block(hook: str, body: str, linter_labels: dict | None) -> list[str]:
    """## 시스템이 감지한 약한 지점 — True 만 한국어 1줄씩. 전부 False 면 [].

    linter_labels 가 None (post_linter 경로 자체를 안 탄 경우) 이면 블록 전체 생략.
    빈 dict 이면 post_linter 가 fail-open 된 것으로 보고 파생 플래그만 돌림.
    """
    if linter_labels is None:
        return []
    lab = linter_labels if isinstance(linter_labels, dict) else {}
    flags = lab.get("flags") if isinstance(lab.get("flags"), dict) else {}
    detected: list[str] = []
    if _derive_weak_hook(hook):
        detected.append("weak_hook")
    if _derive_too_obvious(body):
        detected.append("too_obvious")
    if flags.get("missing_context_flag"):
        detected.append("missing_context")
    if flags.get("weak_ending_flag"):
        detected.append("weak_ending")
    if flags.get("generic_cta_flag"):
        detected.append("generic_cta")
    if flags.get("ai_tone_flag"):
        detected.append("ai_tone")
    if not detected:
        return []
    lines = [f"- {k}: {_WEAKNESS_LABELS[k]}" for k in detected]
    return ["## 시스템이 감지한 약한 지점", *lines]


def _build_account_tone_block(strategy_os: dict | None) -> list[str]:
    """## 계정 톤 (참고) — positioning.one_liner 1줄 + 훅 2개 + 금지 3개. 비면 []."""
    so = strategy_os if isinstance(strategy_os, dict) else {}
    pos = so.get("positioning") if isinstance(so.get("positioning"), dict) else {}
    one = _clip_line(pos.get("one_liner") if isinstance(pos, dict) else "", 160)
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
    return ["## 계정 톤 (참고)", *lines]


def format_handoff(
    source_pack: dict,
    angle_pack: dict,
    final_body: str,
    *,
    final_hook: str | None = None,
    strategy_os: dict | None = None,
    linter_labels: dict | None = None,
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

    confirmed = _drop_url_only(sp.get("confirmed_facts") or [])
    conflicts = _drop_url_only(sp.get("conflicts_or_uncertainty") or [])
    ct = _strip_urls(_safe(sp.get("concept_translation"), 220))
    ep = _drop_url_only(sp.get("evidence_pack") or [])

    # ── ## 원문 초안 ────────────────────────────────────────
    section_draft = [
        "## 원문 초안",
        "```",
        body if body else "(empty)",
        "```",
    ]

    # ── ## 이 글의 핵심 각도 ────────────────────────────────
    section_angle = ["## 이 글의 핵심 각도"]
    section_angle.append(f"- 앵글: {winner}")
    if core_tension:
        section_angle.append(f"- 핵심 긴장: {core_tension}")
    section_angle.append(f"- frame: {frame_type}")
    if spine_str:
        section_angle.append(f"- 뼈대: {spine_str}")
    section_angle.append(f"- 가독성 리스크: {readability_risk}")
    if share_trigger:
        section_angle.append(f"- 공유 트리거: {share_trigger}")
    # 편집 목표 — Grok 편집장용 1줄 지시문. 있을 때만 append.
    _goal = _derive_editorial_goal(ap)
    if _goal:
        section_angle.append(f"- 편집 목표: {_goal}")

    # ── ## 절대 바꾸지 말 것 ────────────────────────────────
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
    if scan_pattern:
        section_free.append(f"- 스캔 패턴 힌트: {scan_pattern}")
    section_free.append("- 훅/클로저 문장 (사실 추가 없이 어휘만)")
    if conflicts:
        c0 = str(conflicts[0]).strip()[:160]
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
    chunks.extend(["\n".join(section_draft)] + fixed_tail)
    for opt in optional_sections[:2]:
        chunks.append("\n".join(opt))

    # 편집 신호 블록 2개 (있을 때만). Grok 이 본문→각도→규칙을 본 뒤 읽도록 뒤쪽에.
    # (편집 목표 1줄은 위 `## 이 글의 핵심 각도` 블록에 이미 append 됨 — 중복 방지.)
    editorial_blocks = [
        _build_weakness_block(final_hook or "", body_raw, linter_labels),
        _build_account_tone_block(strategy_os),
    ]
    for eb in editorial_blocks:
        if eb:
            chunks.append("\n".join(eb))

    out = "\n\n".join(chunks)

    # 길이 제한 — 뒤(선택 블록 + 편집 신호 블록)부터 잘라낸다.
    # 고정 5블록 + (경고 블록 있으면 1) 은 유지.
    _min_keep = 5 + (1 if _warning_block_text else 0)
    while len(out) > _HANDOFF_HARD_MAX and len(chunks) > _min_keep:
        chunks.pop()
        out = "\n\n".join(chunks)

    if len(out) > _HANDOFF_HARD_MAX:
        out = _truncate_to(out, _HANDOFF_HARD_MAX)
    return out
