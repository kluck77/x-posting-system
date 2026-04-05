# Current Session

## Session Info

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Phase: post-v10 audit (Phase 12)

---

## What This Session Did

Audit-only pass with two tiny doc fixes. No logic changes.

---

## Audit Findings

**Files inspected:** LATEST_STATUS.md, CURRENT_SESSION.md, archive/v10-milestone.md, README.md,
PROJECT_STATUS.md, CLAUDE.md, OPERATOR_WORKFLOW.md, telegram_bot.py, reply_monitor.py,
post_queue.py, activity_tracker.py, monitor_state.py, _tg_helper.py, test_reply_monitor.py,
test_telegram_commands.py

**No logic bugs found.** Two stale doc lines found and fixed.

---

## Fixes Made

### Fix 1 — reply_monitor.py docstring (line 15)
- **Was:** "5. 승인 후 자동 게시" — contradicted the system's core no-auto-posting principle
- **Now:** "5. 운영자가 X에서 직접 답글 입력 (자동 게시 없음)"
- Risk: zero (comment only)

### Fix 2 — telegram_bot.py /start help text (line 794)
- **Was:** `/queue — 게시 큐 · /queue remove <n> · /queue clear`
- **Now:** `/queue — 게시 큐 · /queue view <n> · /queue remove <n> · /queue clear`
- Risk: zero (display text only); `/queue view` was added in v9-B but was missing from /start

---

## Test Gaps Noted (not fixed — acceptable)

- `_handle_reply_callback` Telegram handler not unit-tested directly.
  Acceptable: PTB handler testing requires complex mock setup; the underlying
  `get_pending_draft` / `store_pending_draft` logic is tested via TestPendingReplyDrafts.
- `_handle_queue_callback` likewise not unit-tested — acceptable for the same reason.

---

## Tests

481 passed, 0 failures — unchanged

---

## Ranked Future Candidates

### Candidate 1 — Hardcoded `MY_USERNAME = "sskorea02"` config risk
- Where: reply_monitor.py and telegram_bot.py
- Why it matters: account username is in source code, not .env. If the operator changes
  account or runs on a different account, a code edit is required.
- Operator value: low-medium
- Risk: low (Settings field + .env.example update, no logic change)
- Why not now: not blocking; system is stable

### Candidate 2 — `processed_replies.json` grows unbounded
- Where: reply_monitor.py `_processed_ids` saved to `data/processed_replies.json`
- Why it matters: the set of processed reply IDs is never trimmed. After months of
  operation it could grow to tens of thousands of entries. Load is fast now; may slow
  cold start over time.
- Operator value: low
- Risk: low (trim to last N on load)
- Why not now: not urgent at current scale

### Candidate 3 — Queue re-notification not possible
- Where: post_queue.py `try_publish_next()` — once `notified_at` is set, the notification
  is never re-sent, even if the operator lost it (bot restart, delivery failure)
- Why it matters: if Telegram delivery fails silently, the post is stuck: queued but
  never re-triggered without remove + re-add.
- Operator value: medium (edge case but real friction)
- Risk: low-medium (requires extending try_publish_next logic, locked area)
- Why not now: locked area (PostQueue); requires explicit operator direction
