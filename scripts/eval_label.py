#!/usr/bin/env python
"""
eval_label.py — Gold Eval / Pairwise Review 수동 라벨링 CLI
=============================================================
PR 29 — 운영자가 터미널에서 직접 호출하여 gold/pairwise 레코드를
eval_store 에 저장한다. 텔레그램 UI 불필요.

사용법:
  # Gold Eval (단일 포스트 품질 판정)
  python scripts/eval_label.py gold \\
    --post "삼성전자 HBM 매출 2조원 돌파." \\
    --short "삼성 HBM 역대 최고." \\
    --mode EXPLAIN \\
    --quality GOOD \\
    --reasons MORE_FINDABLE,BETTER_REWARD \\
    --note "검색어 잘 박혀있음"

  # Pairwise Review (A/B 비교)
  python scripts/eval_label.py pairwise \\
    --post-a "A안 본문." --short-a "A안 짧은." \\
    --post-b "B안 본문." --short-b "B안 짧은." \\
    --mode EXPLAIN \\
    --verdict A_BETTER \\
    --reasons MORE_FINDABLE \\
    --source-id src_001 \\
    --note "A가 검색 잘 됨"
"""

import argparse
import json
import sys
import os

# 프로젝트 루트를 path 에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_db():
    """SQLite DB 커넥션."""
    from app.db import get_db
    return get_db()


def cmd_gold(args):
    """Gold Eval 레코드 저장."""
    from app.services.output_meta import _build_gold_eval_record
    from app.services.eval_store import save_eval_record

    reasons = [r.strip() for r in args.reasons.split(",") if r.strip()]

    record = _build_gold_eval_record(
        args.post,
        args.short or "",
        args.mode,
        quality=args.quality,
        reasons=reasons,
        evaluator_note=args.note or "",
    )

    db = _get_db()
    ok = save_eval_record(db, "gold_eval", record, source_id=args.source_id or "")
    if ok:
        print(f"✅ Gold Eval 저장 완료: quality={args.quality}")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print("❌ 저장 실패")
        sys.exit(1)


def cmd_pairwise(args):
    """Pairwise Review 레코드 저장."""
    from app.services.output_meta import _build_pairwise_review_record
    from app.services.eval_store import save_eval_record

    reasons = [r.strip() for r in args.reasons.split(",") if r.strip()]

    record = _build_pairwise_review_record(
        args.post_a,
        args.short_a or "",
        args.post_b,
        args.short_b or "",
        args.mode,
        verdict=args.verdict,
        reasons=reasons,
        evaluator_note=args.note or "",
        source_id=args.source_id or "",
    )

    db = _get_db()
    ok = save_eval_record(db, "pairwise_review", record, source_id=args.source_id or "")
    if ok:
        print(f"✅ Pairwise Review 저장 완료: verdict={args.verdict}")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print("❌ 저장 실패")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Gold Eval / Pairwise Review CLI")
    sub = parser.add_subparsers(dest="command")

    # gold
    g = sub.add_parser("gold", help="Gold Eval 레코드 저장")
    g.add_argument("--post", required=True)
    g.add_argument("--short", default="")
    g.add_argument("--mode", default="EXPLAIN", choices=["EXPLAIN", "JUDGMENT", "VERIFY"])
    g.add_argument("--quality", required=True, choices=["GOOD", "BAD", "BORDERLINE"])
    g.add_argument("--reasons", required=True, help="쉼표 구분: MORE_FINDABLE,BETTER_REWARD")
    g.add_argument("--source-id", default="")
    g.add_argument("--note", default="")

    # pairwise
    p = sub.add_parser("pairwise", help="Pairwise Review 레코드 저장")
    p.add_argument("--post-a", required=True)
    p.add_argument("--short-a", default="")
    p.add_argument("--post-b", required=True)
    p.add_argument("--short-b", default="")
    p.add_argument("--mode", default="EXPLAIN", choices=["EXPLAIN", "JUDGMENT", "VERIFY"])
    p.add_argument("--verdict", required=True, choices=["A_BETTER", "B_BETTER", "TIE"])
    p.add_argument("--reasons", default="", help="쉼표 구분")
    p.add_argument("--source-id", default="")
    p.add_argument("--note", default="")

    args = parser.parse_args()
    if args.command == "gold":
        cmd_gold(args)
    elif args.command == "pairwise":
        cmd_pairwise(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
