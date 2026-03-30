"""
샘플 소스 입력 스크립트
========================
테스트용 샘플 소스를 입력하고 전체 파이프라인을 실행합니다.

사용법:
    python scripts/ingest_sample.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.db import init_db
from app.models.content import SourceItemCreate
from app.orchestrator import Orchestrator
from app.utils.logging_config import setup_logging


SAMPLE_SOURCES = [
    {
        "title": "한국 합계출산율 0.72명으로 세계 최저 기록 경신",
        "url": "https://example.com/korea-birth-rate-2024",
        "source_text": (
            "한국의 합계출산율이 0.72명으로 다시 한 번 세계 최저를 기록했다. "
            "이는 OECD 평균 1.5명의 절반에도 못 미치는 수치다. "
            "정부는 저출산 대책으로 육아휴직 확대, 주거 지원, 보육비 지원 등을 "
            "발표했지만 효과가 미미하다는 평가가 나온다. "
            "전문가들은 높은 주거비, 교육비, 그리고 변화하는 가치관이 "
            "주요 원인이라고 분석한다. 이 추세가 계속되면 한국의 인구는 "
            "2070년까지 현재의 절반 수준으로 감소할 것으로 전망된다."
        ),
        "source_type": "manual",
        "language": "ko",
    },
    {
        "title": "한국 반도체 수출 역대 최고 기록 - AI 수요 급증",
        "url": "https://example.com/korea-semiconductor-export",
        "source_text": (
            "한국의 반도체 수출이 AI 반도체 수요 급증에 힘입어 역대 최고 기록을 "
            "달성했다. 삼성전자와 SK하이닉스의 HBM(고대역폭 메모리) 생산이 "
            "핵심 동력이다. 글로벌 AI 투자 확대로 데이터센터용 반도체 수요가 "
            "폭발적으로 증가하면서 한국 반도체 산업이 최대 호황기를 맞고 있다."
        ),
        "source_type": "manual",
        "language": "ko",
    },
]


async def main():
    setup_logging()
    init_db()

    print("=" * 50)
    print("📥 샘플 소스 입력 & 파이프라인 실행")
    print("=" * 50)

    orchestrator = Orchestrator()

    try:
        for i, sample in enumerate(SAMPLE_SOURCES, 1):
            print(f"\n--- 샘플 {i}/{len(SAMPLE_SOURCES)}: {sample['title'][:40]}... ---")

            data = SourceItemCreate(**sample)
            result = await orchestrator.full_pipeline(data)

            if result.get("success"):
                print(f"  ✅ 성공!")
                print(f"  Draft ID: {result['draft_id']}")
                print(f"  카테고리: {result['category']}")
                print(f"  위험도: {result['risk_level']}")
                print(f"  텔레그램: {'전송됨' if result['telegram_sent'] else 'Mock'}")
                print(f"  훅: {result['hook'][:80]}...")
            else:
                print(f"  ❌ 실패: {result.get('error')}")

    finally:
        orchestrator.close()

    print("\n" + "=" * 50)
    print("완료! 텔레그램에서 승인 카드를 확인하세요.")
    print("또는 http://localhost:8000/docs 에서 /drafts/pending 을 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
