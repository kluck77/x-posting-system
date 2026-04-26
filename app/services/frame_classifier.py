"""프레임 분류기 (CONSTITUTION v2 섹션 4 — 12 프레임).

오케스트레이터 Step 2.7 용 하이브리드 분류:
  1) angle_pack.frame_type (있으면) → 매핑
  2) Claude Haiku LLM 분류 (fail-soft)
  3) 전부 실패 시 DEFAULT_FRAME_ID=3 (신호 vs 노이즈 — 가장 안전한 해석 프레임)

DraftWriter 로 [FRAME: N.프레임명] 블록을 주입해 본문 구조를 고정한다.
Provider 시그니처 / pack_chain / DB 스키마 건드리지 않음.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# CONSTITUTION.md 섹션 4 — 12 프레임 정의 (id, kr_name, description)
FRAME_DEFINITIONS: dict[int, dict[str, str]] = {
    1: {
        "name": "권력 다툼",
        "desc": "[A]가 [B]와 [자원/규칙]을 놓고 싸운다. 이기는 쪽이 [하위 결과]를 통제한다. "
                "규제기관·거래소·정당·대기업·은행 간 감독권·지분·정책 대립.",
    },
    2: {
        "name": "타임라인 붕괴",
        "desc": "[연도]에는 가설이었다. 오늘 가동 조건이 됐다. 언제 일어날까가 지금 일어났다로 "
                "바뀌는 전환점.",
    },
    3: {
        "name": "신호 vs 노이즈",
        "desc": "언론은 [잘못된 프레임]으로 읽는다. 1차 소스는 [실제 의미]를 말한다. "
                "매체 오독·과대·과소평가된 데이터.",
    },
    4: {
        "name": "누적 베팅",
        "desc": "단독으로 보면 사소하지만 이전 사건들과 쌓이면 [구조적 변화]의 N번째 데이터 포인트. "
                "하나의 이벤트가 12~24개월 뒤 무엇을 만드는지 축적되는 소재.",
    },
    5: {
        "name": "배관 공개",
        "desc": "가격/정책이 X를 한 이유는 내러티브가 아니라 [결제/준비금/제도 메커닉]. "
                "시장이 왜를 틀리게 읽고 있을 때.",
    },
    6: {
        "name": "규칙 교체",
        "desc": "[이전 시대]의 규칙은 [X]였다. [메커니즘] 때문에 더 이상 유효하지 않다. "
                "법·정책·구조가 바뀌어 과거 플레이북이 틀려지는 순간.",
    },
    7: {
        "name": "인센티브 추적",
        "desc": "모두가 [표면적 이유]를 논쟁한다. [정책/설계]가 통과될 때 누가 돈을 버는지 보라. "
                "공식 이유와 실제 인센티브 구조가 다를 때.",
    },
    8: {
        "name": "역사의 반복",
        "desc": "새것처럼 보이지만 [이전 사례]의 거의 복사판. 그때 해결책은 [Y], 지금 다른 점: [Z]. "
                "현재 이벤트가 과거 패턴을 반복할 때.",
    },
    9: {
        "name": "컨센서스 역전",
        "desc": "컨센서스는 [X]라 말하지만 포지션·플로우·정책 데이터는 [Y]를 말한다. "
                "시장·미디어 컨센서스와 실제 데이터가 어긋날 때.",
    },
    10: {
        "name": "집계 vs 분해",
        "desc": "[기존 강자]가 [공급/유통]을 통제했다. [새 행위자]가 이제 사용자 관계를 소유한다. "
                "플랫폼·앱·프로토콜이 기존 강자를 중개 제거할 때.",
    },
    11: {
        "name": "내부자 플로우",
        "desc": "헤드라인은 [X]를 말한다. 온체인/거래소/공시 데이터는 [특정 집단]이 [Y]를 하고 있음을 "
                "보여준다. 시장이 아직 가격에 반영 안 한 플로우.",
    },
    12: {
        "name": "스테이크 상승",
        "desc": "과거 [같은 유형 사건]은 [조건 A] 때문에 봉쇄됐다. 이번엔 [A가 깨졌거나 B가 새로 생겨서] "
                "다르다. 비슷해 보이지만 이번엔 진짜 다를 때.",
    },
}

# angle_pack.frame_type (4 heuristic 값) → 12 프레임 id 매핑
# parallel → 역사의 반복(8)
# contrast → 권력 다툼(1) — 두 포지션 충돌
# hidden_signal → 내부자 플로우(11) — 시장이 못 본 데이터
# underreported_angle → 신호 vs 노이즈(3) — 매체 오독
ANGLE_PACK_FRAME_MAP: dict[str, int] = {
    "parallel": 8,
    "contrast": 1,
    "hidden_signal": 11,
    "underreported_angle": 3,
}

DEFAULT_FRAME_ID = 3  # 신호 vs 노이즈 — 불확실할 때 가장 안전한 해석 프레임

HAIKU_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class FrameSelection:
    """Step 2.7 프레임 선택 결과."""
    frame_id: int
    frame_name: str
    source: str  # "angle_pack" | "llm" | "default"
    reasoning: str = ""

    def to_context_block(self) -> str:
        """DraftWriter criteria_context 주입용 텍스트 블록."""
        return f"[FRAME: {self.frame_id}.{self.frame_name}]"


def _map_from_angle_pack(angle_pack: Optional[dict]) -> Optional[FrameSelection]:
    """angle_pack.frame_type 에서 12 프레임 id 매핑. 매핑 실패 시 None."""
    if not isinstance(angle_pack, dict):
        return None
    ft = angle_pack.get("frame_type")
    if not isinstance(ft, str):
        return None
    fid = ANGLE_PACK_FRAME_MAP.get(ft.strip().lower())
    if fid is None:
        return None
    return FrameSelection(
        frame_id=fid,
        frame_name=FRAME_DEFINITIONS[fid]["name"],
        source="angle_pack",
        reasoning=f"angle_pack.frame_type={ft}",
    )


def _build_llm_system_prompt() -> str:
    lines = [
        "당신은 @sskorea02 의 편집장이다.",
        "주어진 뉴스를 CONSTITUTION 섹션 4의 12 프레임 중 하나로 분류한다.",
        "",
        "12 프레임:",
    ]
    for fid, meta in FRAME_DEFINITIONS.items():
        lines.append(f"- Frame {fid} ({meta['name']}): {meta['desc']}")
    lines.extend([
        "",
        "판단 규칙:",
        "1. 가장 잘 맞는 프레임 하나만 선택한다.",
        "2. 단순 뉴스 요약밖에 안 나오는 소재면 3(신호 vs 노이즈)로 한다.",
        "3. 확실치 않으면 3(신호 vs 노이즈)로 한다.",
        "",
        "JSON 으로만 응답 (마크다운 펜스 금지):",
        '{"frame_id": <1-12>, "reasoning": "<한 문장>"}',
    ])
    return "\n".join(lines)


async def _classify_via_llm(title: str, source_text: str) -> Optional[FrameSelection]:
    """Claude Haiku 로 프레임 분류. 실패 시 None 반환."""
    if not settings.has_anthropic:
        return None
    system_prompt = _build_llm_system_prompt()
    user_msg = (
        f"제목: {title[:200]}\n\n"
        f"본문:\n{(source_text or '')[:1500]}\n\n"
        f"JSON 으로만 응답."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": HAIKU_MODEL,
                    "max_tokens": 200,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            if resp.status_code >= 400:
                logger.warning(
                    f"[frame_classifier] LLM API {resp.status_code}: {resp.text[:200]}"
                )
                return None
            resp_data = resp.json()
            usage = resp_data.get("usage", {})
            logger.info(
                f"[API-COST] anthropic {HAIKU_MODEL} "
                f"in={usage.get('input_tokens', '?')} "
                f"out={usage.get('output_tokens', '?')} "
                f"caller=FrameClassifier"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage("anthropic", HAIKU_MODEL, "FrameClassifier",
                             usage.get("input_tokens", 0),
                             usage.get("output_tokens", 0))
            except Exception:
                pass
            text = resp_data["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        data = json.loads(text)
        fid = int(data.get("frame_id", 0))
        if fid not in FRAME_DEFINITIONS:
            logger.warning(f"[frame_classifier] LLM 이 잘못된 frame_id 반환: {fid}")
            return None
        return FrameSelection(
            frame_id=fid,
            frame_name=FRAME_DEFINITIONS[fid]["name"],
            source="llm",
            reasoning=str(data.get("reasoning", ""))[:200],
        )
    except Exception as e:
        logger.warning(f"[frame_classifier] LLM 분류 실패 (무시): {e}")
        return None


async def select_frame(
    title: str,
    source_text: str,
    angle_pack: Optional[dict] = None,
) -> FrameSelection:
    """하이브리드 프레임 선택.

    순서: angle_pack 매핑 → LLM 분류 → default(3).
    어떤 경로든 반드시 FrameSelection 을 반환한다 (raise 없음).
    """
    # 1) angle_pack 매핑 우선
    sel = _map_from_angle_pack(angle_pack)
    if sel is not None:
        logger.info(
            f"[frame_classifier] angle_pack → Frame {sel.frame_id}.{sel.frame_name}"
        )
        return sel

    # 2) LLM 분류
    sel = await _classify_via_llm(title, source_text)
    if sel is not None:
        logger.info(
            f"[frame_classifier] LLM → Frame {sel.frame_id}.{sel.frame_name} "
            f"({sel.reasoning[:80]})"
        )
        return sel

    # 3) default fallback
    logger.info(
        f"[frame_classifier] default → Frame {DEFAULT_FRAME_ID}."
        f"{FRAME_DEFINITIONS[DEFAULT_FRAME_ID]['name']}"
    )
    return FrameSelection(
        frame_id=DEFAULT_FRAME_ID,
        frame_name=FRAME_DEFINITIONS[DEFAULT_FRAME_ID]["name"],
        source="default",
        reasoning="angle_pack/LLM 모두 미가용",
    )
