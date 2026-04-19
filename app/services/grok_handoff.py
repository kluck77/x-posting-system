"""
Grok Handoff
============
source_pack + angle_pack + final_body 를 Grok (x.ai) 편집용 컨텍스트 블록으로
렌더링한다. 또한 orchestrator 에서 DraftWriter / Reviewer 에게 pack 정보를
주입할 때 쓰는 compose 헬퍼 2개 를 제공한다.

제공 함수:
  format_handoff(source_pack, angle_pack, final_body) -> str
  compose_enriched_source(original, source_pack, winner_angle) -> str
  compose_pack_context(source_pack, winner_angle) -> str

원칙:
- 모든 함수는 pure string 반환. 예외 던지지 않는다 (호출측이 await 없이 바로 씀).
- pack dict 누락 키는 빈 블록으로 처리.
- 출력 길이 상한: handoff <= 3500자, enriched_source 는 원문 + 600자 상한 pack block.
"""

from __future__ import annotations

from typing import Any


def _bullets(items: Any, limit: int = 8, max_len: int = 240) -> str:
    if not items or not isinstance(items, list):
        return "  (none)"
    lines: list[str] = []
    for x in items[:limit]:
        s = str(x).strip()
        if not s:
            continue
        lines.append(f"  - {s[:max_len]}")
    return "\n".join(lines) if lines else "  (none)"


def _safe(val: Any, limit: int = 300) -> str:
    if val is None:
        return ""
    return str(val).strip()[:limit]


def compose_pack_context(source_pack: dict, winner_angle: dict) -> str:
    """
    DraftWriter / Reviewer 의 criteria_context 에 주입할 텍스트 블록.
    기존 criteria_context 에 append 되는 형태로 쓰인다.
    """
    sp = source_pack if isinstance(source_pack, dict) else {}
    wa = winner_angle if isinstance(winner_angle, dict) else {}

    parts = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "PACK CONTEXT (Phase 1 — Grok Handoff)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "[Winner Angle]",
        f"  angle:  {_safe(wa.get('angle'), 200)}",
        f"  reason: {_safe(wa.get('reason'), 240)}",
        f"  score:  {wa.get('score', 'n/a')}",
        "",
        "[Confirmed Facts]",
        _bullets(sp.get("confirmed_facts"), limit=6),
        "",
        "[Conflicts / Uncertainty]",
        _bullets(sp.get("conflicts_or_uncertainty"), limit=5),
        "",
        "[Korea Angle]",
        _bullets(sp.get("korea_angle"), limit=3),
        "",
        "[Global Angle]",
        _bullets(sp.get("global_angle"), limit=3),
        "",
        "[Watch Next]",
        _bullets(sp.get("watch_next"), limit=3),
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
    header.append("=== ORIGINAL SOURCE ===")

    pack_block = "\n".join(header)
    # pack_block 상한 ~600자 방어 (헤더가 길어지지 않도록 한 번 더 자름)
    if len(pack_block) > 700:
        pack_block = pack_block[:700]

    orig = original or ""
    return f"{pack_block}\n{orig}"


def format_handoff(source_pack: dict, angle_pack: dict, final_body: str) -> str:
    """
    Grok (x.ai) 편집용 handoff 텍스트. 텔레그램 copy_grok 버튼으로 복사될 예정.

    구성:
      1. Winner angle + 이유
      2. Confirmed / Conflicts
      3. Korea / Global angle
      4. Watch next
      5. 최종 본문 (DB 저장된 review_result.body)
      6. 편집 지시 (Grok 가 어떤 방향으로 각도를 살릴지)
    """
    sp = source_pack if isinstance(source_pack, dict) else {}
    ap = angle_pack if isinstance(angle_pack, dict) else {}
    wa = ap.get("winner_angle") if isinstance(ap.get("winner_angle"), dict) else {}
    sq = sp.get("source_quality") if isinstance(sp.get("source_quality"), dict) else {}

    lines = [
        "## GROK HANDOFF — angle-aware edit pass",
        "",
        "### Source",
        f"- title: {_safe(sq.get('title'), 200)}",
        f"- url:   {_safe(sq.get('url'), 200)}",
        f"- type:  {sq.get('source_type', 'manual')}",
        f"- factcheck_verified: {sq.get('factcheck_verified', False)} "
        f"(confidence={sq.get('factcheck_confidence', 'low')})",
        "",
        "### Winner angle",
        f"- angle:  {_safe(wa.get('angle'), 200)}",
        f"- reason: {_safe(wa.get('reason'), 300)}",
        f"- score:  {wa.get('score', 'n/a')}",
        f"- series_type:   {ap.get('series_type', 'analysis')}",
        f"- follow_reason: {_safe(ap.get('follow_reason'), 200)}",
        f"- share_reason:  {_safe(ap.get('share_reason'), 200)}",
        "",
        "### Core tension",
        _safe(ap.get("core_tension"), 400) or "(none)",
        "",
        "### Confirmed facts",
        _bullets(sp.get("confirmed_facts"), limit=8),
        "",
        "### Conflicts / uncertainty",
        _bullets(sp.get("conflicts_or_uncertainty"), limit=6),
        "",
        "### Korea angle",
        _bullets(sp.get("korea_angle"), limit=4),
        "",
        "### Global angle (what English coverage misses)",
        _bullets(sp.get("global_angle"), limit=4),
        "",
        "### Watch next",
        _bullets(sp.get("watch_next"), limit=4),
        "",
        "### Final body (as saved to DB)",
        "```",
        (final_body or "").strip()[:1800],
        "```",
        "",
        "### Edit instructions",
        "- Sharpen the winner angle. Do NOT introduce new facts.",
        "- Keep every numeric claim tied to Confirmed facts.",
        "- Treat Conflicts as open — hedge verbs, not assert.",
        "- Target tone: Korea-origin insight for global readers.",
    ]
    out = "\n".join(lines)
    return out[:3500]
