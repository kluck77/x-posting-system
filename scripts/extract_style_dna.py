"""아키타입별 스타일 DNA 자동 추출 (일회성).

Claude Sonnet 4.6 에 7 아키타입 샘플을 던져 5축 스타일 DNA 추출.
결과는 editorial/style_dna.yaml 로 저장.

실행:
    python -m scripts.extract_style_dna

의존:
    httpx (기존 프로젝트 내장)
    PyYAML
"""
from __future__ import annotations

import json
import sys

import httpx
import yaml

from app.config import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

ARCHETYPES_SAMPLES = {
    "onchain_1person": [
        "온체인 상으로 아직 진짜 바닥 아님.\n손실확정 물량은 쏟아졌는데 고래 누적은 안 보임.\n"
        "2017, 2022 바닥 때는 고래가 먼저 샀다. 이번엔 아직.\n"
        "⚠️ 한 달은 더 본다.\n📌 다음 신호: 1000BTC+ 지갑 순매집 전환."
    ],
    "breaking_news": [
        "📉 미국 BTC 현물 ETF 12종, 하루 4억1,057만달러 순유출.\n"
        "IBIT 단일 기준 2.8억달러 최대 유출.\n이틀 연속 마이너스. 원화 BTC는 1억 선 붕괴.\n"
        "⚠️ 한국 개미가 받친 1억 선이 깨졌다는 게 진짜 신호.\n"
        "📌 다음 봐야 할 것: 업비트 KRW 거래량 24시간 기준 회복 여부."
    ],
    "researcher": [
        "디지털자산기본법 정부안 이번 주 국회 발의 예정.\n핵심은 3개.\n"
        "1) 원화 스테이블코인 발행 주체\n2) 해외 스테이블코인 유통 요건\n"
        "3) 국내 ICO 재개방 조건.\n⚠️ 은행 컨소시엄 우세지만 민주당 TF가 반대 중.\n"
        "📌 신한+하나+삼성 컨소가 가장 먼저 라이선스 받을 가능성 높음."
    ],
    "policy_definitive": [
        "부동산 투기 억제는 실패할 것 같나요?\n이번이 마지막 기회입니다.\n"
        "2026년 5월 9일이 지나면 매물이 잠길 것이라는 말, 정부의 권위와 일관성을 시험하는 말이죠.\n"
        "⚠️ 버티면 불이익뿐입니다.\n📌 5월 9일 이후 다주택자 양도세 중과 연장 여부가 분기점."
    ],
    "macro_contrast": [
        "원/달러 1,475원. 숫자만 보면 위기지만 구조를 보면 파동이다.\n"
        "트럼프 관세 대법 판결(2Q 예상)이 변수.\n판결 후행적이면 하반기 원화 강세 가능.\n"
        "⚠️ 2026 키워드는 변동성, 금리 양극화.\n"
        "📌 환헤지 안 된 해외주식 ETF는 역환차손 구간 진입."
    ],
    "semiconductor": [
        "젠슨 황은 이제 Physical AI 기업 말고는 관심 없음.\n치맥 회동의 본질은 로봇.\n"
        "HBM4는 SK하이닉스 54%, 삼성 17% 갈 듯.\n"
        "⚠️ 2026 영업익 컨센 SK 91조, 삼성 110조.\n📌 마이크론 18% 점유율 유지 여부."
    ],
    "builder": [
        "원화 스테이블코인 판이 지금 네 개로 갈라짐.\n"
        "1) 신한+하나+삼성 컨소\n2) 네이버+두나무\n3) 토스+빗썸\n4) 카카오 단독.\n"
        "⚠️ 은행 과반 조항이 통과하면 2·3·4는 재편 불가피.\n"
        "📌 핀테크 진영이 민주당 TF랑 붙는 이유가 이거."
    ],
}

DNA_PROMPT = (
    "아래 한국어 X 포스트를 분석해서 이 아키타입의 글쓰기 스타일 DNA를 "
    "5축으로 추출하라.\n\n"
    "5축:\n"
    "1. 문장_구조: 평균 문장 길이, 끊는 패턴, 행 바꿈 빈도\n"
    "2. 어휘_선호: 자주 쓰는 단어, 기피 단어, 고유어 vs 한자어 비율\n"
    "3. 시점: 1인칭/3인칭/무인칭, 독자 호출 방식\n"
    "4. 호흡: 빠름/느림, 단문/장문 믹스 패턴\n"
    "5. 해석_깊이: 1차 팩트/2차 구조/3차 파급 중 어느 층에서 멈추는가\n\n"
    "JSON 형식으로 출력. 각 축은 2~3문장. 마크다운 펜스 없음."
)


def extract_all() -> None:
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY 없음 — 중단", file=sys.stderr)
        sys.exit(1)

    dna_table: dict[str, object] = {}
    for archetype, samples in ARCHETYPES_SAMPLES.items():
        posts_text = "\n---\n".join(samples)
        payload = {
            "model": MODEL,
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"아키타입: {archetype}\n\n"
                        f"포스트:\n{posts_text}\n\n{DNA_PROMPT}"
                    ),
                }
            ],
            "temperature": 0.3,
        }
        try:
            resp = httpx.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            dna_table[archetype] = json.loads(text)
            print(f"✓ {archetype}")
        except Exception as e:
            print(f"✗ {archetype}: {e}", file=sys.stderr)
            dna_table[archetype] = {}

    out_path = "editorial/style_dna.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(dna_table, f, allow_unicode=True, default_flow_style=False)
    print(f"\n{out_path} 생성 완료: {list(dna_table.keys())}")


if __name__ == "__main__":
    extract_all()
