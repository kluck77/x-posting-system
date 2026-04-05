# Current Session

## Session Info

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Phase: Phase 14 — Reliability Hygiene Bundle

---

## What This Session Did

Three small operational hygiene fixes. No new features, no behavior redesign.

---

## Bundle Items Implemented

### 1. `processed_replies.json` growth control
**File:** `app/services/growth/reply_monitor.py`

`_load_processed()` now trims the loaded list to `_PROCESSED_IDS_MAX = 1000` entries.
Trim strategy: sort numeric IDs descending (snowflake = newer = larger number) → keep top N.
Non-numeric IDs (mock mode) are sorted after numeric, included if space remains.
Log message emitted when trim occurs.

No change to `_save_processed()` — the trimmed set is naturally smaller on next save.

### 2. `MY_USERNAME` de-hardcoding
**Files:** `app/config.py`, `app/services/growth/reply_monitor.py`, `.env.example`

Added `x_username: str = Field(default="sskorea02", ...)` to Settings.
Removed `MY_USERNAME = "sskorea02"` module-level constant from `reply_monitor.py`.
Two usage sites updated:
- `_get_my_user_id()` API URL now uses `settings.x_username`
- `generate_rereply_draft()` prompt now uses `settings.x_username`

Backward-compatible: default `"sskorea02"` means no `.env` change needed for existing deployments.
`.env.example` updated with `X_USERNAME=sskorea02` comment.

### 3. `_pending_articles` memory cap
**File:** `app/services/news_monitor.py`

Added `_PENDING_ARTICLES_MAX = 200` constant.
In `_send_news_alert()`, before adding a new entry to `_pending_articles`, evicts the
oldest entry (Python 3.7+ dict insertion-order) when the dict hits 200 entries.
Simple, one-line eviction — no LRU complexity needed for single-operator use.

---

## Files Changed

| File | Change |
|------|--------|
| `app/config.py` | +1 field: `x_username` (default `"sskorea02"`) |
| `app/services/growth/reply_monitor.py` | Removed `MY_USERNAME` constant; trim in `_load_processed()`; two `settings.x_username` references |
| `app/services/news_monitor.py` | `_PENDING_ARTICLES_MAX = 200`; eviction before insert in `_send_news_alert()` |
| `.env.example` | Added `X_USERNAME=sskorea02` line |

---

## Tests Added

**`tests/test_reply_monitor.py`** — 7 new tests in 2 new classes:

`TestProcessedIdsTrim`:
- `test_under_limit_loads_all` — no trim when < 1000
- `test_over_limit_trims_to_max` — 1001 → 1000
- `test_trim_keeps_largest_numeric_ids` — newest (largest) ID preserved
- `test_non_numeric_ids_survive` — mock IDs included when space allows

`TestXUsernameConfig`:
- `test_default_username` — default is `"sskorea02"`
- `test_override_username` — env override works
- `test_reply_monitor_uses_settings_username` — source-level verification

---

## Test Counts

- Before: 497 passed
- After: 504 passed (+7)
- 0 failures

---

## Risks Checked

- `_PROCESSED_IDS_MAX = 1000` is well above practical usage (30 posts/day × 30 days = 900 replies max). No operational data loss.
- Trim on load (not save) — existing oversized files are silently cleaned up on next `ReplyMonitor()` init.
- `x_username` default `"sskorea02"` means zero operator action needed on existing deployments.
- `_PENDING_ARTICLES_MAX = 200` is well above the ~5 articles per news cycle that typically trigger alerts. No practical impact.
- All Layer 1 flows untouched.

---

## Future Candidates (updated — all addressed or low priority)

1. ~~`processed_replies.json` unbounded growth~~ — **done**
2. ~~`MY_USERNAME` hardcoded~~ — **done**
3. ~~`_pending_articles` no size cap~~ — **done**

No remaining urgent hygiene items.
