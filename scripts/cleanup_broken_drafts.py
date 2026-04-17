"""
깨진 초안 일괄 정리
===================
body에 [AI 실패]/[Gemini실패]/[Mock] 등이 포함된 초안을 FAILED로 변경.
일회성 또는 정기 실행 가능.

사용법:
  cd /root/x-posting-system
  venv/bin/python scripts/cleanup_broken_drafts.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TESTING", "1")

from app.db import get_db
from app.models.content import Draft, ApprovalStatus
from app.services.draft_service import is_broken_draft, broken_reason

db = get_db()
try:
    drafts = db.query(Draft).filter(
        Draft.approval_status.in_([ApprovalStatus.PENDING, ApprovalStatus.APPROVED])
    ).all()
    fixed = 0
    for d in drafts:
        if is_broken_draft(d.body):
            reason = broken_reason(d.body)
            print(f"  [{d.id}] {(d.hook or '')[:50]}... → FAILED ({reason})")
            d.approval_status = ApprovalStatus.FAILED
            fixed += 1
    if fixed:
        db.commit()
    print(f"\n정리 완료: {fixed}건 FAILED 처리 (전체 {len(drafts)}건 중)")
finally:
    db.close()
