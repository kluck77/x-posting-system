# Current Session

## Session Info

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Phase: Phase 15 — Ops Recovery Bundle

---

## What This Session Did

Four small reliability improvements for post-restart confidence. No new features, no behavior redesign.

---

## Bundle Items Implemented

### 1. Startup self-check
**File:** `app/utils/startup_check.py` (new)

`run_startup_check()` inspects all four persistent state files on startup:
- `data/post_queue.json` — reports pending/total count
- `data/processed_replies.json` — reports processed ID count
- `data/activity.json` — reports last activity timestamp
- `data/monitor_state.json` — reports reply monitor on/off

Behavior:
- Missing file → "파일 없음 (정상)" — expected on fresh install, no warning
- Valid file → logs count/status
- Corrupt file → `valid_json: False`, logs WARNING with file name + hint to delete
- Never raises — startup always continues

Also exports `format_recovery_summary()` for Telegram output.

**File:** `app/main.py`

Added `run_startup_check()` call in `run_all()` after `init_db()`.

### 2. `/recover` command
**File:** `app/telegram_bot.py`

New command: `/recover`
- Calls `run_startup_check()` live
- Formats result as Telegram HTML
- Icons: ⚪ missing (normal) / ✅ valid / ❌ corrupt
- Shows corrupt file error snippet and instructions to delete

Registered in handler list. Added to `/start` help text.

### 3. Safe state/load handling audit
**File:** `app/services/growth/reply_monitor.py`

`_load_processed()` had a silent `except Exception: return set()` — if `processed_replies.json`
existed but was corrupt, it would silently start with an empty set and no log.

Fix: changed to `except Exception as e: logger.warning(...)` so operators see the issue.
(FileNotFoundError path unchanged — still silently returns empty set, which is correct.)

### 4. Recovery playbook
**File:** `docs/recovery_playbook.md` (new)

Short operator-facing reference covering:
- What each state file holds and what happens if deleted
- Common recovery scenarios (lost pending alerts, corrupt files, stuck monitor, idle reminder)
- Startup log format
- Data directory permissions check

---

## Files Changed

| File | Change |
|------|--------|
| `app/utils/startup_check.py` | New: `run_startup_check()`, `_check_file()`, `format_recovery_summary()` |
| `app/main.py` | +3 lines: call `run_startup_check()` after `init_db()` |
| `app/telegram_bot.py` | `recover_command()` function + handler registration + help text |
| `app/services/growth/reply_monitor.py` | Silent exception → logged warning in `_load_processed()` |
| `docs/recovery_playbook.md` | New: operator recovery reference |

---

## Tests Added

**`tests/test_startup_check.py`** — 15 tests in 3 classes:

`TestCheckFile`:
- `test_missing_file_returns_not_exists`
- `test_valid_post_queue` — pending count computed correctly
- `test_valid_processed_replies`
- `test_valid_activity`
- `test_activity_no_entry` — empty dict handled
- `test_valid_monitor_state_running`
- `test_valid_monitor_state_paused`
- `test_corrupt_file_returns_false`

`TestRunStartupCheck`:
- `test_returns_all_four_keys`
- `test_corrupt_file_triggers_warning`
- `test_all_missing_logs_info_not_warning`

`TestFormatRecoverySummary`:
- `test_all_missing_shows_white_circles`
- `test_corrupt_shows_red_x`
- `test_valid_shows_check`
- `test_includes_recovery_hint`

---

## Test Counts

- Before: 504 passed
- After: 519 passed (+15)
- 0 failures

---

## Risks Checked

- `run_startup_check()` never raises — all `_check_file()` paths are wrapped in try/except
- Only reads files, never modifies state
- `reply_monitor` fix: warning log only, no behavior change — corrupt file still starts empty
- No Layer 1 paths touched
- `docs/recovery_playbook.md` is reference-only, no code dependency
