"""패턴 룰을 OpenAI / Grok 프롬프트에 동적 주입.

호출 시점에 활성 룰을 읽어 system prompt 끝에 append 하는 방식 — 정적
SYSTEM_PROMPT_KO 자체는 수정하지 않음 (기존 5-AI 흐름 불변).

Phase 4 (writing-os-v1):
- get_openai_system_addition 에 Editorial Constitution 7원칙 prepend
- GROK_AGENT_ADDITIONS 각 슬롯 앞에 SCENE_RULE_PREFIX prepend
"""
from __future__ import annotations

import logging

from app.editorial_constitution import get_constitution_prompt
from app.services.pattern_db import get_active_rules

logger = logging.getLogger(__name__)


SCENE_RULE_PREFIX = """
[장면화 원칙 — 모든 문장에 적용]
새 사실 추가 금지. 원문 팩트를 재배열할 것.
설명문 → 시간/장소 좌표 + 능동 동사로 변환.
비유는 "이해 보조" 라벨로 본문과 분리.
"""


def build_rules_block() -> str:
    """활성 룰을 프롬프트 삽입용 텍스트로 변환."""
    rules = get_active_rules()
    if not rules:
        return ""
    pos = [r for r in rules if r["kind"] == "positive"]
    neg = [r for r in rules if r["kind"] == "negative"]

    lines = ["[글쓰기 룰 — 가중치 절댓값 큰 순]", ""]
    if pos:
        lines.append("✅ 반드시 지킬 것:")
        for r in pos:
            lines.append(f"  [{r['weight']:+.1f}] {r['text']}")
    if neg:
        lines.append("")
        lines.append("❌ 절대 금지:")
        for r in neg:
            lines.append(f"  [{r['weight']:+.1f}] {r['text']}")
    return "\n".join(lines)


_OPENAI_RULES_TEMPLATE = """

{rules_block}

채점 기준:
- 14/14 = 95점 이상 목표
- 12/14 미만 = 재생성 요청
"""


def get_openai_system_addition() -> str:
    """OpenAI system prompt 끝에 추가할 통합 블록 — 호출 시점 동적 생성.

    구성 (Phase 4):
      ① Editorial Constitution v1 (7원칙 + 7패턴 + 3공식)
      ② 활성 룰 블록 (가중치 절댓값 큰 순)
      ③ 채점 기준 (14/14 = 95점, 12/14 미만 재생성)
    """
    constitution = get_constitution_prompt()
    block = build_rules_block()
    if not block:
        return constitution + "\n\n"
    return (
        constitution
        + "\n\n"
        + _OPENAI_RULES_TEMPLATE.format(rules_block=block)
    )


# Grok 4-agent 별 추가 지시 템플릿 (v2: 단순화 — 강제 아님)
GROK_AGENT_ADDITIONS = {
    "hook": """
[Hook]
소스에서 가장 강한 한 줄을 찾아라. 없으면 가장 중요한 사실을 짧게.
억지로 만들지 마라.
x_search(query="{keywords}", hours=24) 로 같은 주제 24시간 X 글 검색
→ 안 쓰인 각도 선택.
""",
    "context": """
[Context]
소스 사실을 재배열해서 보여줘라. 새 사실 추가 금지.
원문에 비유·사례 없을 때만 web_search(query="...") 로 보강.
""",
    "stakes": """
[Stakes]
"그래서 이게 나한테 왜 중요한가" — 소스에 있는 사실로만.
소스가 한국 관련일 때만 web_search(query="원달러 환율 오늘") 로
한국 시장 수치 확인.
""",
    "prediction": """
[Prediction]
예측 1개 + 반증조건 1개. 소스에 있는 사실 기반.
web_search(query="polymarket {keywords} odds") 로 관련 일정·odds 확인.
""",
}


def get_grok_agent_addition(agent_type: str, keywords: str = "") -> str:
    """Grok 4-agent 별 추가 지시 — 장면화 prefix + keywords 치환."""
    template = GROK_AGENT_ADDITIONS.get(agent_type, "")
    if not template:
        return ""
    return (
        SCENE_RULE_PREFIX
        + template.replace("{keywords}", keywords or "")
    )
