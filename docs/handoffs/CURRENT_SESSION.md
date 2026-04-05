# Current Session

## Session Info

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Phase: Phase 13 — Real-world scenario reliability audit

---

## What This Session Did

Scenario-based reliability audit across queue, reply, monitor, idle reminder,
draft, and cross-flow consistency. Found and fixed one real bug (news_regen always failing).
No new features added.

---

## Audit Scope

**Files inspected (14):**
- docs/handoffs/LATEST_STATUS.md + CURRENT_SESSION.md + archive/v10-milestone.md
- app/telegram_bot.py (full, ~1600 lines)
- app/services/telegram_service.py
- app/services/growth/post_queue.py
- app/services/growth/reply_monitor.py
- app/services/growth/activity_tracker.py
- app/services/growth/monitor_state.py
- app/services/growth/_tg_helper.py
- tests/test_post_queue.py
- tests/test_reply_monitor.py
- tests/test_activity_tracker.py
- tests/test_monitor_state.py

---

## Scenario Audit Findings

**Queue lifecycle (add → list → view → remove → clear → approval tap):**
- All paths correct. Duplicate-tap after approval returns "already published" message. ✓
- Remove-then-tap-old-button returns "not found" message. ✓
- `/queue` listing uses `published_at is None` filter — published items excluded. ✓
- KST conversion via `+ timedelta(hours=9)` is correct for single-operator use. ✓
- Corrupted JSON on load silently starts with empty queue (known trade-off, logged). ✓

**Reply lifecycle (draft → use/skip → expiry/restart):**
- `mark_processed()` called after sending, independent of operator action. ✓
- `reply_skip` callback does not double-remove. ✓
- Bot restart wipes `_pending_reply_drafts` (in-memory); "초안 정보가 만료됐습니다" message handles it. ✓
- 100-entry overflow cap tested. ✓

**Monitor lifecycle (/monitor off/on/status + scheduler):**
- `run_reply_monitor()` checks `is_paused()` at top; early return when off. ✓
- Queue scheduler unaffected by monitor state. ✓
- `/monitor off` when already off, `/monitor on` when already on: correct idempotent messages. ✓

**Idle reminder lifecycle (silence → reminder → resumed → spam guard):**
- 48h threshold, 24h cooldown: tested and correct. ✓
- No-activity-record → False (prevents first-run over-alerting). ✓
- `record_activity()` called in `/draft` and `/queue add`. ✓

**Draft lifecycle (/draft fast-path → approval card → operator action):**
- Fast-path pipeline, approval callbacks: locked and well-tested. ✓
- HTML formatting in `_tg_helper.tg_send_with_keyboard` uses parse_mode="HTML". ✓

**Cross-flow consistency:**
- HTML tags consistent across reply_monitor, news_monitor, post_queue outputs. ✓

---

## Real Issue Found and Fixed

### BUG: `news_regen` callback always fails with "기사 정보 만료"

**Location:** `app/telegram_bot.py`, `_handle_news_callback()`

**Root cause:**
`remove_pending_article(article_hash)` was called on line 670 *before* showing
the "🔄 재생성" keyboard on line 711–712. When operator tapped regen,
`get_pending_article(article_hash)` returned `None`, causing the "기사 정보 만료" error.
The comment on line 715 even said "재생성용으로 기사 정보 유지" — the intent was correct,
but the deletion contradicted it.

**Fix:** Removed the premature `remove_pending_article(article_hash)` call.
The article now survives in `_pending_articles` (in-memory, no size cap needed
for single-operator use) until bot restarts or operator skips. Skip path
still calls `remove_pending_article` at line 612 (unchanged).

**Files changed:**
- `app/telegram_bot.py`: removed 1 line (`remove_pending_article(article_hash)`),
  added clarifying comment

**Test added:**
- `tests/test_telegram_commands.py`: `TestNewsRegenArticleState`
  - `test_pending_article_survives_after_draft_generation` — regression guard
  - `test_skip_removes_pending_article` — skip path still cleans up

---

## Tests

- Before: 495 passed
- After: 497 passed (+2)
- 0 failures

---

## Ranked Future Candidates (max 3)

1. **`processed_replies.json` unbounded growth** — low value, low risk.
   `ReplyMonitor._load_processed()` could trim to last 1000 IDs on load.
   Single line fix when desired.

2. **`MY_USERNAME = "sskorea02"` hardcoded in `reply_monitor.py`** — low value, low risk.
   Move to `Settings.x_username`. No behavior change.

3. **`_pending_articles` (news_monitor) has no size cap** — very low risk for single operator.
   Could add a 200-entry LRU if bot runs long-lived without restarts. Not urgent.
