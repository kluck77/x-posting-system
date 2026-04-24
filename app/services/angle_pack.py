"""
Angle Pack
==========
source_pack 을 입력으로 받아 "어느 각도로 쓸지" 를 결정하는 층.
Gemini 1회만 호출 (safety pass 없음 — safety 는 Reviewer 단 전담).

키 (11):
  core_tension      — 이 스토리의 핵심 긴장/대립 한 문장
  angle_options     — 후보 각도 리스트 (3~4개)
  winner_angle      — Gemini 가 선택한 최적 각도 (dict: {angle, score, reason})
  series_type       — breaking / analysis / reaction / explainer / thread
  follow_reason     — 팔로우할 이유 (1줄 — 게시 후 팔로업 근거)
  share_reason      — 공유할 이유 (1줄 — 독자가 RT 하는 동기)
  frame_type        — parallel / contrast / hidden_signal / underreported_angle  (Phase 1.1)
  story_spine       — 글의 뼈대 순서 (list of phase keys)                         (Phase 1.1)
  readability_risk  — low / medium / high                                         (Phase 1.1)
  share_trigger     — 공유 트리거 한 줄 (짧고 구체)                                (Phase 1.1)
  scan_pattern      — 모바일 스캔 패턴 힌트 (짧은 문장)                            (Phase 1.1)

설계 원칙:
- plain dict 반환. Pydantic 금지.
- Gemini 키 없으면 heuristic fallback 사용 (RuntimeError 금지).
- 호출 실패/JSON 파싱 실패 → heuristic fallback 으로 우회.
- Gemini 호출 수 유지 (1회). Phase 1.1 은 스키마만 확장.
- orchestrator 는 이 pack 의 winner_angle 을 enriched_source / pack_context 에 주입.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Korean enforcement (handoff 영어 누출 방지) ──────────────────────
_KO_CHAR_RE = re.compile(r"[가-힣]")
_EN_ALPHA_RE = re.compile(r"[A-Za-z]")


def _korean_dominant(text: str) -> bool:
    """한국어 지배적이면 True. 알파벳 글자만 비교 (숫자/기호 무시)."""
    if not text:
        return True
    ko = len(_KO_CHAR_RE.findall(text))
    en = len(_EN_ALPHA_RE.findall(text))
    return ko >= en  # 한국어 동률 이상이면 통과


def _ensure_korean(text: str, *, max_chars: int = 200) -> str:
    """영어 비율 50%+ 이면 Haiku 로 한국어 번역. 실패/키 없음 → 원문 유지.

    handoff angle_pack 에 영어 fallback / Gemini 영어 응답 누출 방지.
    """
    if not text or _korean_dominant(text):
        return text
    api_key = getattr(settings, "anthropic_api_key", "")
    if not api_key:
        return text
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"아래 영어 문장을 한국어로 자연스럽게 번역하세요. "
                    f"번역문만 반환 (다른 설명 금지):\n\n{text[:max_chars * 4]}"
                ),
            }],
        )
        out = resp.content[0].text.strip()
        return out[:max_chars] if out else text
    except Exception as e:
        logger.warning(f"[angle_pack] Haiku 번역 실패 (원문 유지): {e}")
        return text

# Phase 3b — 상류 완화 정책 상수 (source_pack.py 와 동일값 유지).
# 상류 느슨 / 하류 handoff_quality_guard(=0.3) 엄격의 2단 필터.
ENGLISH_RATIO_THRESHOLD_SOURCE = 0.4

_ALPHA_ONLY_RE = re.compile(r"[A-Za-z]")
_WORD_ONLY_RE = re.compile(r"[\w가-힣]")


def _english_ratio(text: str) -> float:
    """ASCII 알파벳 / (공백·구두점 제외 실제 문자) 비율."""
    if not isinstance(text, str) or not text:
        return 0.0
    alpha = len(_ALPHA_ONLY_RE.findall(text))
    total = len(_WORD_ONLY_RE.findall(text))
    return (alpha / total) if total else 0.0

ANGLE_PACK_KEYS: tuple[str, ...] = (
    "core_tension",
    "angle_options",
    "winner_angle",
    "series_type",
    "follow_reason",
    "share_reason",
    # Phase 1.1 구조 강화
    "frame_type",
    "story_spine",
    "readability_risk",
    "share_trigger",
    "scan_pattern",
)

_FRAME_TYPES = ("parallel", "contrast", "hidden_signal", "underreported_angle")
_READABILITY_LEVELS = ("low", "medium", "high")
_DEFAULT_STORY_SPINE: tuple[str, ...] = ("hook", "explain", "evidence", "contrast", "close")
_VALID_SPINE_PHASES = {"hook", "explain", "evidence", "contrast", "close", "signal", "twist"}

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """You are the angle strategist for @cheesesvav — an English-language X account that shares Korean perspectives with global readers.

Given a "source pack" (confirmed facts, conflicts/uncertainty, Korea angle, global angle, watch-next signals, plus optional historical_parallel / concept_translation / evidence_pack / closing_signal), decide the best angle to post.

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
  "share_reason": "one sentence: why a reader would share/RT this post",
  "frame_type": "parallel|contrast|hidden_signal|underreported_angle",
  "story_spine": ["hook","explain","evidence","contrast","close"],
  "readability_risk": "low|medium|high",
  "share_trigger": "one short, concrete line that makes the reader want to share",
  "scan_pattern": "one short hint on how the post should scan on mobile (e.g. 'short lines, one number per line')"
}

Rules:
- Ground every angle in confirmed_facts or conflicts_or_uncertainty. Do not invent.
- Prefer angles that expose interpretation gaps (what Reuters/Bloomberg misses).
- Winner selection: highest marginal insight, lowest speculation risk.
- frame_type: pick "parallel" when a historical/cross-case parallel exists; "contrast" when two positions clash; "hidden_signal" when a small confirmed fact hints at a bigger move; "underreported_angle" when global media is missing the Korea/Asia read.
- story_spine: pick 4~5 phases from ["hook","explain","evidence","contrast","close","signal","twist"], in the order the post should flow. No duplicates.
- readability_risk: "high" if the topic is dense / jargon-heavy / requires prior context; "low" if it is a clean one-beat story.
- scan_pattern: imagine a phone screen — tell the writer what shape to give the post.
- Do NOT include a safety verdict — Reviewer handles that downstream.
"""


def _pick_frame_type_heuristic(source_pack: dict) -> str:
    if source_pack.get("historical_parallel"):
        return "parallel"
    if source_pack.get("conflicts_or_uncertainty"):
        return "contrast"
    if source_pack.get("korea_angle") or source_pack.get("global_angle"):
        return "underreported_angle"
    if source_pack.get("watch_next"):
        return "hidden_signal"
    return "underreported_angle"


def _pick_readability_risk_heuristic(source_pack: dict) -> str:
    if source_pack.get("concept_translation"):
        return "high"
    confirmed = source_pack.get("confirmed_facts") or []
    if len(confirmed) >= 6:
        return "medium"
    return "low"


def _heuristic_angle_pack(source_pack: dict) -> dict:
    """Gemini 키 없음 / 호출 실패 시 사용할 최소 각도 팩."""
    confirmed = source_pack.get("confirmed_facts") or []
    conflicts = source_pack.get("conflicts_or_uncertainty") or []
    korea = source_pack.get("korea_angle") or []
    global_ = source_pack.get("global_angle") or []
    watch = source_pack.get("watch_next") or []
    closing = source_pack.get("closing_signal") or ""

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

    # Phase 3b: options[0] 의 angle 이 영어 비율 > 0.4 면 winner 를 placeholder
    # 로 대체. source_pack 의 영어 원문이 그대로 angle 로 통과하는 경로 차단.
    top_angle_text = str(options[0]["angle"]) if options else ""
    english_blocked = _english_ratio(top_angle_text) > ENGLISH_RATIO_THRESHOLD_SOURCE
    if english_blocked:
        winner = {
            "angle": "[angle 재작성 필요 - 영어 source 감지]",
            "score": 0,
            # Phase 1.5a detect_angle_pack_heuristic 의 winner_angle.reason
            # substring 매칭 ("heuristic" or "fallback") 조건을 만족해야 한다.
            "reason": "heuristic fallback 차단 (영어 소스 감지)",
        }
        method_value = "heuristic_en_blocked"
    else:
        winner = {
            "angle": options[0]["angle"],
            "score": 50,
            "reason": "heuristic fallback (Gemini 미호출)",
        }
        method_value = "heuristic"

    follow_reason = (
        str(watch[0])[:160] if watch else "한국발 신호 — 후속 전개 예상."
    )
    share_reason = (
        str(global_[0])[:160] if global_
        else "영문 매체에서 다루지 않는 한국 시각."
    )

    frame_type = _pick_frame_type_heuristic(source_pack)
    readability_risk = _pick_readability_risk_heuristic(source_pack)

    share_trigger = ""
    if closing:
        share_trigger = str(closing)[:200]
    elif global_:
        share_trigger = f"영문 독자가 못 보는 한 줄: {str(global_[0])[:160]}"
    elif confirmed:
        share_trigger = f"한 줄로 옮길 가치: {str(confirmed[0])[:160]}"
    else:
        share_trigger = share_reason[:200]

    scan_pattern = (
        "짧은 줄 · 한 줄에 숫자 하나 · 대조는 한 줄로."
        if frame_type == "contrast"
        else "짧은 줄 · 사실 먼저 · 마지막에 신호."
    )

    return {
        "core_tension":    core[:300],
        "angle_options":   options[:4],
        "winner_angle":    winner,
        "series_type":     series_type,
        "follow_reason":   follow_reason[:200],
        "share_reason":    share_reason[:200],
        "frame_type":      frame_type,
        "story_spine":     list(_DEFAULT_STORY_SPINE),
        "readability_risk": readability_risk,
        "share_trigger":   share_trigger[:200],
        "scan_pattern":    scan_pattern[:200],
        # Phase 3b: top-level method 필드 명시.
        # "gemini" | "heuristic" | "heuristic_en_blocked" 세 값.
        # handoff_quality_guard.detect_angle_pack_heuristic 가 이 필드를 우선 체크.
        "method":          method_value,
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

    hp = source_pack.get("historical_parallel") or ""
    if hp:
        parts.append(f"HISTORICAL_PARALLEL:\n  - {str(hp)[:240]}\n")
    ct = source_pack.get("concept_translation") or ""
    if ct:
        parts.append(f"CONCEPT_TRANSLATION:\n  - {str(ct)[:240]}\n")
    ep = source_pack.get("evidence_pack") or []
    if isinstance(ep, list) and ep:
        lines = "\n".join(f"  - {str(x)[:240]}" for x in ep[:5])
        parts.append(f"EVIDENCE_PACK:\n{lines}\n")
    cs = source_pack.get("closing_signal") or ""
    if cs:
        parts.append(f"CLOSING_SIGNAL:\n  - {str(cs)[:240]}\n")

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


def _normalize_story_spine(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return list(_DEFAULT_STORY_SPINE)
    out: list[str] = []
    seen: set = set()
    for p in raw:
        key = str(p).strip().lower()[:20]
        if key and key in _VALID_SPINE_PHASES and key not in seen:
            out.append(key)
            seen.add(key)
        if len(out) >= 6:
            break
    if len(out) < 3:
        return list(_DEFAULT_STORY_SPINE)
    return out


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
        winner["reason"] = winner["reason"] or "첫 옵션 자동 선택 (winner 누락)"

    series_type = str(raw.get("series_type", "analysis")).strip().lower()[:20] or "analysis"
    follow_reason = str(raw.get("follow_reason", "")).strip()[:200]
    share_reason = str(raw.get("share_reason", "")).strip()[:200]

    frame_type = str(raw.get("frame_type", "")).strip().lower()[:32]
    if frame_type not in _FRAME_TYPES:
        frame_type = _pick_frame_type_heuristic(source_pack)

    story_spine = _normalize_story_spine(raw.get("story_spine"))

    readability_risk = str(raw.get("readability_risk", "")).strip().lower()[:10]
    if readability_risk not in _READABILITY_LEVELS:
        readability_risk = _pick_readability_risk_heuristic(source_pack)

    share_trigger = str(raw.get("share_trigger", "")).strip()[:200]
    scan_pattern = str(raw.get("scan_pattern", "")).strip()[:200]

    if not share_trigger:
        share_trigger = share_reason or "영문 매체에서 다루지 않는 한국 시각."
    if not scan_pattern:
        scan_pattern = "짧은 줄 · 사실 먼저 · 마지막에 신호."

    if not options or not winner["angle"] or not core_tension:
        # 치명적 누락 → heuristic 으로 우회
        return _heuristic_angle_pack(source_pack)

    # 영어 누출 차단 — handoff 한국어 강제 (fail-open: 키 없으면 원문)
    core_tension  = _ensure_korean(core_tension)
    follow_reason = _ensure_korean(follow_reason)
    share_reason  = _ensure_korean(share_reason)
    share_trigger = _ensure_korean(share_trigger)
    if isinstance(winner, dict):
        if winner.get("angle"):
            winner["angle"] = _ensure_korean(winner["angle"])
        if winner.get("reason"):
            winner["reason"] = _ensure_korean(winner["reason"])

    return {
        "core_tension":     core_tension,
        "angle_options":    options,
        "winner_angle":     winner,
        "series_type":      series_type,
        "follow_reason":    follow_reason,
        "share_reason":     share_reason,
        "frame_type":       frame_type,
        "story_spine":      story_spine,
        "readability_risk": readability_risk,
        "share_trigger":    share_trigger,
        "scan_pattern":     scan_pattern,
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
        # Phase 3b: Gemini 성공 경로에서도 method 를 명시적으로 세팅.
        # _heuristic_angle_pack 은 자체 경로에서 method 를 넣으므로 여기선 gemini 만.
        pack["method"] = "gemini"
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
    for str_key in ("core_tension", "series_type", "follow_reason", "share_reason",
                    "frame_type", "readability_risk", "share_trigger", "scan_pattern"):
        if not isinstance(pack[str_key], str):
            raise ValueError(f"angle_pack.{str_key} must be str")
    if pack["frame_type"] not in _FRAME_TYPES:
        raise ValueError(f"angle_pack.frame_type invalid: {pack['frame_type']}")
    if pack["readability_risk"] not in _READABILITY_LEVELS:
        raise ValueError(f"angle_pack.readability_risk invalid: {pack['readability_risk']}")
    if not isinstance(pack["story_spine"], list) or not pack["story_spine"]:
        raise ValueError("angle_pack.story_spine must be non-empty list")
