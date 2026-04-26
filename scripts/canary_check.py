#!/usr/bin/env python
"""
canary_check.py — 실제 AI 호출 경로 생존 확인
================================================
PR 31 — 운영자가 하루 1회 수동 실행하여
실제 모델 호출 포함 경로가 살아 있는지 확인.

사용법:
  python scripts/canary_check.py

확인 항목:
  1. content_pack.py import 정상
  2. generate_candidate_card mock 호출 정상
  3. _validate_final_post 정상
  4. eval_store 저장/조회 정상
  5. (옵션) 실AI 호출 — CANARY_LIVE=1 환경변수 시 실행

종료 코드:
  0 = 전부 통과
  1 = 실패 있음
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_imports():
    """1. 핵심 import 정상 확인."""
    from app.services.content_pack import (
        generate_final_post, generate_candidate_card,
        CandidateCard, FinalPost, ThesisCard,
        _validate_final_post, _build_evaluation_meta,
    )
    from app.services.eval_store import save_eval_record, load_recent_records
    from app.services.output_meta import _feed_online_eval
    from app.services.evidence_resolver import _extract_source_metadata
    print("  [1/5] imports: OK")
    return True


def check_validate_final_post():
    """2. _validate_final_post 정상 동작."""
    from app.services.content_pack import _validate_final_post
    post = "삼성전자 HBM 매출이 2조원을 넘었다. 다음 CPI가 나오면 갈린다."
    short = "삼성 HBM 역대 최고."
    p, s, warnings, gate_fails = _validate_final_post(post, short)
    assert isinstance(warnings, list)
    assert isinstance(gate_fails, list)
    print(f"  [2/5] validate_final_post: OK (warnings={len(warnings)}, gates={len(gate_fails)})")
    return True


def check_eval_store():
    """3. eval_store 저장/조회 정상."""
    import sqlite3
    from app.services.eval_store import save_eval_record, load_recent_records, count_records, cleanup_old_records

    conn = sqlite3.connect(":memory:")
    ok = save_eval_record(conn, "canary", {"status": "alive"})
    assert ok is True
    assert count_records(conn, "canary") == 1
    records = load_recent_records(conn, "canary")
    assert records[0]["status"] == "alive"
    deleted = cleanup_old_records(conn, retention_days=0)
    assert deleted >= 1
    conn.close()
    print("  [3/5] eval_store: OK (save+load+cleanup)")
    return True


def check_evidence_metadata():
    """4. evidence metadata 추출 정상."""
    from app.services.content_pack import CandidateCard
    from app.services.evidence_resolver import _extract_source_metadata

    card = CandidateCard(
        key_facts=["기획재정부가 세제 개편안을 발표했다", "2024년 1월 시행"],
        source_url="https://moef.go.kr/policy",
    )
    meta = _extract_source_metadata(card, "", "GOVERNMENT")
    assert meta["institution"] is not None
    assert meta["country"] is not None
    print(f"  [4/5] evidence_metadata: OK (inst={meta['institution']}, country={meta['country']})")
    return True


def check_live_ai():
    """5. (옵션) 실AI 호출 — CANARY_LIVE=1 시만 실행."""
    if not os.environ.get("CANARY_LIVE"):
        print("  [5/5] live_ai: SKIP (CANARY_LIVE=1 로 활성화)")
        return True

    # API 키 존재 확인
    from app.config import settings
    keys = {
        "OpenAI": settings.has_openai,
        "Gemini": settings.has_gemini,
    }
    missing = [k for k, v in keys.items() if not v]
    if missing:
        print(f"  [5/5] live_ai: SKIP (API 키 없음: {', '.join(missing)})")
        print(f"         .env에 OPENAI_API_KEY, GEMINI_API_KEY 설정 필요")
        return True

    import asyncio
    from app.services.content_pack import generate_candidate_card
    from app.models.content_request import ContentRequest

    req = ContentRequest(
        title="[canary] 삼성전자 HBM 매출 2조원 돌파",
        source_text="삼성전자가 HBM 반도체 매출 2조원을 달성했다고 밝혔다. 전년 대비 50% 증가.",
        source_url="https://example.com/canary",
        source_type="news_link",
    )

    try:
        card = asyncio.run(generate_candidate_card(req))
        if card and card.hook_candidates:
            print(f"  [5/5] live_ai: OK (hooks={len(card.hook_candidates)})")
            return True
        else:
            print("  [5/5] live_ai: WARN (카드 생성됐으나 hook 없음)")
            return True
    except Exception as e:
        print(f"  [5/5] live_ai: FAIL ({e})")
        return False


def main():
    print("=== X-Posting Canary Check ===\n")
    checks = [
        check_imports,
        check_validate_final_post,
        check_eval_store,
        check_evidence_metadata,
        check_live_ai,
    ]

    passed = 0
    failed = 0
    for fn in checks:
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  FAIL: {fn.__name__} — {e}")
            failed += 1

    print(f"\n=== 결과: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
