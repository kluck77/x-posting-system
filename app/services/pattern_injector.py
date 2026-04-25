"""패턴 룰을 OpenAI / Grok 프롬프트에 동적 주입.

호출 시점에 활성 룰을 읽어 system prompt 끝에 append 하는 방식 — 정적
SYSTEM_PROMPT_KO 자체는 수정하지 않음 (기존 5-AI 흐름 불변).
"""
from __future__ import annotations

import logging

from app.services.pattern_db import get_active_rules

logger = logging.getLogger(__name__)


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
    """OpenAI system prompt 끝에 추가할 룰 블록 — 호출 시점에 동적 생성."""
    block = build_rules_block()
    if not block:
        return ""
    return _OPENAI_RULES_TEMPLATE.format(rules_block=block)


# Grok 4-agent 별 추가 지시 템플릿
GROK_AGENT_ADDITIONS = {
    "hook": """
[Hook 에이전트 추가 지시]
X firehose 에서 같은 주제 최근 24시간 글을 검색하라.
이미 쓰인 hook 유형을 확인하고 다른 각도를 선택하라.
검색 방법: x_search(query="{keywords}", hours=24)
안 쓰인 훅 유형 우선순위:
1. 충격 수치 → 2. 시점 못박기 → 3. 반전 → 4. 모순 노출
""",
    "context": """
[Context 에이전트 추가 지시]
웹 검색으로 다음을 보강하라:
1. 처음 보는 사람을 위한 비유 1개 (일상 연결)
2. 역사적 유사 사례 1개 (24개월 이내)
3. 한국 시장 추가 수치 1개
검색 방법: web_search(query="...")
검색 결과를 그대로 쓰지 말고 내 말로 소화해서 1줄로 압축.
""",
    "stakes": """
[Stakes 에이전트 추가 지시]
웹 검색으로 한국 시장 최신 수치를 확인하라.
- 원/달러 환율 (한국은행 기준)
- 코스피/코스닥 종가
- 비트코인 김치프리미엄
위 수치 중 이 글과 관련된 것 1개 이상 실시간 확인 후 인용.
검색 방법: web_search(query="원달러 환율 오늘")
""",
    "prediction": """
[Prediction 에이전트 추가 지시]
Polymarket 에서 이 주제 관련 시장을 검색하라.
- 관련 odds 실시간 확인
- 24시간 변화량 확인
- 없으면 가장 가까운 매크로 시장(FOMC/금리/선거)
검색 방법: web_search(query="polymarket {keywords} odds")
예측 구조: "[시한] [조건]이면 [결과]. 반증: [반대 조건]."
""",
}


def get_grok_agent_addition(agent_type: str, keywords: str = "") -> str:
    """Grok 4-agent 별 추가 지시 — keywords 치환."""
    template = GROK_AGENT_ADDITIONS.get(agent_type, "")
    return template.replace("{keywords}", keywords or "")
