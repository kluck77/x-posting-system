"""Haiku Soft Rule Judge (L2 — 정성 평가).

Claude Haiku 4.5 로 13개 규칙에 대해 0~10점 평가.
각 항목 ≥7 AND total ≥91/130 일 때 pass=true.

httpx 직접 사용 (anthropic SDK 미도입).
cache_control=ephemeral 로 JUDGE_SYSTEM 캐시.
실패 시 JudgeResult(passed=True, total=0) 반환 — 파이프라인 중단 없음.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

JUDGE_SYSTEM = """당신은 한국어 X(Twitter) 포스트 품질 검증관입니다.
아래 13개 규칙을 0~10점으로 평가하세요.
각 항목 score ≥ 7 AND total ≥ 91/130일 때만 pass=true.
위반 1~2개: targeted_fixes만 반환.
위반 3개 이상: must_regenerate_ids를 채우세요.

13개 규칙:
1. 말투_일관성: 존댓말/반말/음슴체 중 하나만. 혼용 시 0점.
2. 1인칭_시점: "내가 보기엔", "~로 보임", "틀리면 정정함" 등 1인칭 존재.
3. 해석_깊이: 뉴스 요약 아닌 2~3차 파급 효과 해석인가.
4. 갈등_구조: A vs B, 이기는 쪽/지는 쪽 명확한가.
5. 스테이크_구체성: "판도가 갈린다" 추상 vs "카카오페이가 먼저 움직인다" 구체.
6. 시점_고정: "이번 주", "N일 만에" 등 현재 시점 앵커 존재.
7. 단정성: "~할 수 있다" 회피형 vs "~이다" 단정형 비율.
8. AI티_종합: hedging·meta-discourse·열거 남발 없는가.
9. 호흡_리듬: 짧은 문장(5어절↓)과 긴 문장(15어절↑) 혼재.
10. 훅_강도: 첫 문장이 숫자/기관명/충돌 구조로 시작하는가.
11. 엔딩_강도: 마지막 줄이 단정 선언 ("지켜봐야 한다" = 0점).
12. 한자어_과용: 유의미한, 괄목할, 귀추, 이목 등 남발.
13. 2026_컨텍스트: BTC 6.5만~7만, 원/달러 1,475원, 이란 전쟁 등 반영.

pass 판정 기준: 각 항목 ≥7 AND total ≥91/130

## 평가 예시

[PASS — 105/130]
원화 스테이블코인 판이 지금 네 개로 갈라짐.
1) 신한+하나+삼성 컨소 2) 네이버+두나무 3) 토스+빗썸 4) 카카오 단독.
⚠️ 은행 과반 조항이 통과하면 2·3·4는 재편 불가피.
📌 핀테크 진영이 민주당 TF랑 붙는 이유가 이거.
→ 말투통일 9 / 1인칭 7 / 해석깊이 9 / 갈등구조 10 / 스테이크 10

[FAIL — 61/130]
금융당국이 원화 스테이블코인 논의를 도입 여부에서 설계 방향으로 전환했다.
이는 다양한 이해관계자들의 의견을 종합한 결과로 볼 수 있습니다.
향후 행보가 주목됩니다.
→ 말투통일 5 / 1인칭 2 / 해석깊이 3 / 갈등구조 2 / 스테이크 1

[PASS — 98/130]
온체인 상으로 아직 진짜 바닥 아님.
손실확정 물량은 쏟아졌는데 고래 누적은 안 보임.
2017, 2022 바닥 때는 고래가 먼저 샀다. 이번엔 아직.
⚠️ 한 달은 더 본다.
📌 다음 신호: 1000BTC+ 지갑 순매집 전환.
→ 1인칭 10 / 단정성 9 / 해석깊이 8 / 2026컨텍스트 7

[PASS — 102/130]
원/달러 1,475원. 숫자만 보면 위기지만 구조를 보면 파동이다.
트럼프 관세 대법 판결(2Q 예상)이 변수.
⚠️ 2026 키워드는 변동성, 금리 양극화.
📌 환헤지 안 된 해외주식 ETF는 역환차손 구간 진입.
→ 시점고정 10 / 갈등구조 9 / 스테이크구체 9

[FAIL — 54/130]
Fed가 금리를 인하했습니다. 이는 글로벌 시장에 큰 영향을 미칠 것으로 보입니다.
향후 추이를 지켜봐야 할 것 같습니다.
→ AI티종합 1 / 단정성 1 / 엔딩강도 0 / 1인칭시점 2

JSON만 반환. 다른 텍스트 금지."""

JUDGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {str(i): {"type": "integer"} for i in range(1, 14)},
        },
        "total":    {"type": "integer"},
        "pass":     {"type": "boolean"},
        "violations":         {"type": "array"},
        "targeted_fixes":     {"type": "array", "items": {"type": "string"}},
        "must_regenerate_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "scores", "total", "pass", "violations",
        "targeted_fixes", "must_regenerate_ids",
    ],
}


@dataclass
class JudgeResult:
    passed: bool
    total: int
    scores: dict = field(default_factory=dict)
    violations: list[dict] = field(default_factory=list)
    targeted_fixes: list[str] = field(default_factory=list)
    must_regenerate_ids: list[str] = field(default_factory=list)
    cached_tokens: int = 0
    duration_ms: float = 0.0


async def judge(post_text: str) -> JudgeResult:
    """포스트 텍스트를 Haiku 로 평가. fail-soft."""
    api_key = settings.anthropic_api_key
    if not api_key or not post_text:
        logger.warning("[HaikuJudge] API 키 또는 텍스트 없음 — 패스 처리")
        return JudgeResult(passed=True, total=0, scores={})

    t0 = time.perf_counter()
    payload = {
        "model": HAIKU_MODEL,
        "max_tokens": 1500,
        "system": [
            {
                "type": "text",
                "text": JUDGE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": (
                    f"<post>{post_text}</post>\n\n"
                    f"위 포스트를 평가하라. JSON schema:\n"
                    f"{json.dumps(JUDGE_RESPONSE_SCHEMA, ensure_ascii=False)}"
                ),
            }
        ],
        "temperature": 0.1,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    "anthropic-beta": "prompt-caching-2024-07-31",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[HaikuJudge] API 호출 실패 (패스 처리): {e}")
        return JudgeResult(passed=True, total=0, scores={})

    try:
        cached = (data.get("usage") or {}).get("cache_read_input_tokens", 0)
        raw = data["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        return JudgeResult(
            passed=bool(parsed.get("pass", False)),
            total=int(parsed.get("total", 0)),
            scores=parsed.get("scores") or {},
            violations=parsed.get("violations") or [],
            targeted_fixes=parsed.get("targeted_fixes") or [],
            must_regenerate_ids=parsed.get("must_regenerate_ids") or [],
            cached_tokens=int(cached),
            duration_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        logger.warning(f"[HaikuJudge] 응답 파싱 실패 (패스 처리): {e}")
        return JudgeResult(passed=True, total=0, scores={})
