"""
Angle Pack
==========
source_pack 을 입력으로 받아 "어느 각도로 쓸지" 를 결정하는 층.
Gemini 1회만 호출 (safety pass 없음 — safety 는 Reviewer 단 전담).

키 (6):
  core_tension   — 이 스토리의 핵심 긴장/대립 한 문장
  angle_options  — 후보 각도 리스트 (3~4개)
  winner_angle   — Gemini 가 선택한 최적 각도 (dict: {angle, score, reason})
  series_type    — breaking / analysis / reaction / explainer / thread
  follow_reason  — 팔로우할 이유 (1줄 — 게시 후 팔로업 근거)
  share_reason   — 공유할 이유 (1줄 — 독자가 RT 하는 동기)

설계 원칙:
- plain dict 반환. Pydantic 금지.
- Gemini 키 없으면 heuristic fallback 사용 (RuntimeError 금지).
- 호출 실패/JSON 파싱 실패 → heuristic fallback 으로 우회.
- orchestrator 는 이 pack 의 winner_angle 을 enriched_source / pack_context 에 주입.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ANGLE_PACK_KEYS: tuple[str, ...] = (
    "core_tension",
    "angle_options",
    "winner_angle",
    "series_type",
    "follow_reason",
    "share_reason",
)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """You are the angle strategist for @cheesesvav — an English-language X account that shares Korean perspectives with global readers.

Given a "source pack" (confirmed facts, conflicts/uncertainty, Korea angle, global angle, watch-next signals), decide the best angle to post.

Return ONLY valid JSON with this exact shape:
{
  "core_tension": "one-sentence description of the central tension or stake",
  "angle_options": [
    {"angle": "angle headline 1", "hook": "1-sentence hook", "risk": "low|medium|high"},
    {"angle": "angle headline 2", "hook": "1-sentence hook", "risk": "low|medium|high"},
    {"angle": "angle headline 3", "hook": "1-sentence hook", "risk": "low|medium|high"}
  ],
  "winner_angle": {
    "angle": "selected angle headline",
    "score": 0-100,
    "reason": "why this wins — tie to confirmed_facts or interpretation gap"
  },
  "series_type": "breaking|analysis|reaction|explainer|thread",
  "follow_reason": "one sentence: why a reader would follow after seeing this post",
  "share_reason": "one sentence: why a reader would share/RT this post"
}

Rules:
- Ground every angle in confirmed_facts or conflicts_or_uncertainty. Do not invent.
- Prefer angles that expose interpretation gaps (what Reuters/Bloomberg misses).
- Winner selection: highest marginal insight, lowest speculation risk.
- Do NOT include a safety verdict — Reviewer handles that downstream.
"""


def _heuristic_angle_pack(source_pack: dict) -> dict:
    """Gemini 키 없음 / 호출 실패 시 사용할 최소 각도 팩."""
    confirmed = source_pack.get("confirmed_facts") or []
    conflicts = source_pack.get("conflicts_or_uncertainty") or []
    korea = source_pack.get("korea_angle") or []
    global_ = source_pack.get("global_angle") or []
    watch = source_pack.get("watch_next") or []

    if conflicts:
        core = f"Uncertainty on record: {str(conflicts[0])[:160]}"
        series_type = "analysis"
    elif korea:
        core = f"Korean perspective: {str(korea[0])[:160]}"
        series_type = "explainer"
    elif confirmed:
        core = f"Confirmed: {str(confirmed[0])[:160]}"
        series_type = "breaking"
    else:
        core = "No strong signal — low-conviction post."
        series_type = "reaction"

    options: list[dict] = []
    if korea:
        options.append({
            "angle": f"Korea angle: {str(korea[0])[:120]}",
            "hook": str(korea[0])[:160],
            "risk": "low",
        })
    if global_:
        options.append({
            "angle": f"Global gap: {str(global_[0])[:120]}",
            "hook": str(global_[0])[:160],
            "risk": "medium",
        })
    if conflicts:
        options.append({
            "angle": f"Tension: {str(conflicts[0])[:120]}",
            "hook": str(conflicts[0])[:160],
            "risk": "medium",
        })
    if not options and confirmed:
        options.append({
            "angle": f"Fact-first: {str(confirmed[0])[:120]}",
            "hook": str(confirmed[0])[:160],
            "risk": "low",
        })
    if not options:
        options.append({"angle": "Status note", "hook": "No strong angle.", "risk": "low"})

    winner = {
        "angle": options[0]["angle"],
        "score": 50,
        "reason": "heuristic fallback (no Gemini call)",
    }

    follow_reason = (
        str(watch[0])[:160] if watch else "Korea-origin signal with follow-up coming."
    )
    share_reason = (
        str(global_[0])[:160] if global_
        else "Fills a gap English-language coverage misses."
    )

    return {
        "core_tension":  core[:300],
        "angle_options": options[:4],
        "winner_angle":  winner,
        "series_type":   series_type,
        "follow_reason": follow_reason[:200],
        "share_reason":  share_reason[:200],
    }


def _source_pack_to_prompt(source_pack: dict) -> str:
    def _block(label: str, items: list) -> str:
        if not items:
            return f"{label}: (none)\n"
        lines = "\n".join(f"  - {str(x)[:240]}" for x in items[:8])
        return f"{label}:\n{lines}\n"

    parts = [
        _block("CONFIRMED_FACTS", source_pack.get("confirmed_facts") or []),
        _block("CONFLICTS_OR_UNCERTAINTY", source_pack.get("conflicts_or_uncertainty") or []),
        _block("KOREA_ANGLE", source_pack.get("korea_angle") or []),
        _block("GLOBAL_ANGLE", source_pack.get("global_angle") or []),
        _block("WATCH_NEXT", source_pack.get("watch_next") or []),
    ]
    sq = source_pack.get("source_quality") or {}
    if isinstance(sq, dict):
        parts.append(
            f"SOURCE_QUALITY:\n"
            f"  - title: {str(sq.get('title', ''))[:200]}\n"
            f"  - url: {str(sq.get('url', ''))[:200]}\n"
            f"  - source_type: {sq.get('source_type', 'manual')}\n"
            f"  - factcheck_verified: {sq.get('factcheck_verified', False)}\n"
            f"  - factcheck_confidence: {sq.get('factcheck_confidence', 'low')}\n"
        )
    return "\n".join(parts)


async def _call_gemini_angle(source_pack: dict) -> dict:
    """Gemini HTTP 호출. 성공 시 JSON 파싱된 dict 반환."""
    url = GEMINI_API_URL.format(model=GEMINI_MODEL)
    user_msg = (
        "Choose the best angle for this Korean-origin story.\n\n"
        f"{_source_pack_to_prompt(source_pack)}\n"
        "Respond in JSON only."
    )

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
                "contents": [{"parts": [{"text": user_msg}]}],
                "generationConfig": {"temperature": 0.5},
            },
        )
        if resp.status_code >= 400:
            body = resp.text
            if settings.gemini_api_key:
                body = body.replace(settings.gemini_api_key, "***")
            raise RuntimeError(f"[AnglePack] Gemini {resp.status_code}: {body[:300]}")
        resp_data = resp.json()
        usage_meta = resp_data.get("usageMetadata", {})
        logger.info(
            f"[API-COST] gemini {GEMINI_MODEL} "
            f"in={usage_meta.get('promptTokenCount', '?')} "
            f"out={usage_meta.get('candidatesTokenCount', '?')} "
            f"think={usage_meta.get('thoughtsTokenCount', 0)} "
            f"caller=AnglePack"
        )
        try:
            from app.services.api_cost_tracker import record_usage
            record_usage(
                "gemini", GEMINI_MODEL, "AnglePack",
                usage_meta.get("promptTokenCount", 0),
                usage_meta.get("candidatesTokenCount", 0),
            )
        except Exception:
            pass
        raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]

    _t = raw_text.strip()
    if _t.startswith("```"):
        _t = _t.split("\n", 1)[1] if "\n" in _t else _t[3:]
        if _t.endswith("```"):
            _t = _t[:-3]
        _t = _t.strip()
    return json.loads(_t)


def _normalize_angle_pack(raw: Any, source_pack: dict) -> dict:
    """Gemini 반환 JSON 을 ANGLE_PACK_KEYS 스키마로 보정."""
    if not isinstance(raw, dict):
        return _heuristic_angle_pack(source_pack)

    core_tension = str(raw.get("core_tension", "")).strip()[:300]

    options_raw = raw.get("angle_options") or []
    options: list[dict] = []
    if isinstance(options_raw, list):
        for opt in options_raw[:4]:
            if isinstance(opt, dict):
                options.append({
                    "angle": str(opt.get("angle", "")).strip()[:160],
                    "hook":  str(opt.get("hook", "")).strip()[:200],
                    "risk":  str(opt.get("risk", "medium")).strip().lower()[:10],
                })
            elif isinstance(opt, str):
                options.append({"angle": opt.strip()[:160], "hook": "", "risk": "medium"})

    winner_raw = raw.get("winner_angle") or {}
    if isinstance(winner_raw, dict):
        try:
            score_val = int(winner_raw.get("score", 50))
        except (TypeError, ValueError):
            score_val = 50
        winner = {
            "angle":  str(winner_raw.get("angle", "")).strip()[:200],
            "score":  max(0, min(100, score_val)),
            "reason": str(winner_raw.get("reason", "")).strip()[:300],
        }
    else:
        winner = {"angle": str(winner_raw)[:200], "score": 50, "reason": ""}

    if not winner["angle"] and options:
        winner["angle"] = options[0]["angle"]
        winner["reason"] = winner["reason"] or "first option (auto-picked — missing winner)"

    series_type = str(raw.get("series_type", "analysis")).strip().lower()[:20] or "analysis"
    follow_reason = str(raw.get("follow_reason", "")).strip()[:200]
    share_reason = str(raw.get("share_reason", "")).strip()[:200]

    if not options or not winner["angle"] or not core_tension:
        # 치명적 누락 → heuristic 으로 우회
        return _heuristic_angle_pack(source_pack)

    return {
        "core_tension":  core_tension,
        "angle_options": options,
        "winner_angle":  winner,
        "series_type":   series_type,
        "follow_reason": follow_reason,
        "share_reason":  share_reason,
    }


async def build_angle_pack(source_pack: dict, ai_team=None) -> dict:
    """
    source_pack 기반 각도 팩 생성.

    Args:
        source_pack: build_source_pack() 결과 dict
        ai_team: (현재 미사용 — 시그니처 호환용. 향후 확장 대비)

    Gemini 키 없거나 호출 실패 → heuristic fallback (raise 하지 않음).
    """
    if not isinstance(source_pack, dict):
        raise ValueError("source_pack must be dict")

    if not settings.has_gemini:
        logger.info("[angle_pack] Gemini 키 없음 — heuristic fallback 사용")
        pack = _heuristic_angle_pack(source_pack)
        validate_angle_pack(pack)
        return pack

    try:
        raw = await _call_gemini_angle(source_pack)
        pack = _normalize_angle_pack(raw, source_pack)
    except Exception as e:
        safe_msg = str(e)
        if settings.gemini_api_key:
            safe_msg = safe_msg.replace(settings.gemini_api_key, "***")
        logger.warning(f"[angle_pack] Gemini 실패 → heuristic: {safe_msg}")
        pack = _heuristic_angle_pack(source_pack)

    validate_angle_pack(pack)
    return pack


def validate_angle_pack(pack: dict) -> None:
    """필수 키 + 타입 체크. 불일치 시 ValueError."""
    if not isinstance(pack, dict):
        raise ValueError("angle_pack must be dict")
    for k in ANGLE_PACK_KEYS:
        if k not in pack:
            raise ValueError(f"angle_pack missing key: {k}")
    if not isinstance(pack["angle_options"], list) or not pack["angle_options"]:
        raise ValueError("angle_pack.angle_options must be non-empty list")
    if not isinstance(pack["winner_angle"], dict) or not pack["winner_angle"].get("angle"):
        raise ValueError("angle_pack.winner_angle must be dict with angle")
    for str_key in ("core_tension", "series_type", "follow_reason", "share_reason"):
        if not isinstance(pack[str_key], str):
            raise ValueError(f"angle_pack.{str_key} must be str")
