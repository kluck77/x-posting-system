# Current Session

## Session Info

- Date: 2026-04-06
- Branch: claude/extract-prediction-time-n82UK
- Phase: Phase 16 — Critical Flows Regression Bundle

---

## What This Session Did

Added scenario-level regression tests for the most important operator-facing flows.
No new product features. No behavior changes. Pure test/verification leverage.

---

## Coverage Gaps Filled

Before this session, the following critical behaviors had no scenario-level regression coverage:

| Gap | Risk |
|-----|------|
| `run_reply_monitor()` paused guard | `/monitor off` could silently stop working |
| Queue sequential lifecycle | Position shifts after remove not verified end-to-end |
| Approval card HTML structure | Markup regressions would go unnoticed |
| Inline keyboard button completeness | Missing button caught only at runtime |
| Recovery summary labels | Dropped section caught only by operator |
| Idle reminder cooldown lifecycle | Double-send scenario only tested piecemeal |
| Startup check safety guarantee | No test that `run_startup_check()` never raises |

---

## Bundle Items Implemented

### 1. `tests/test_critical_flows.py` (new, 17 tests in 5 classes)

**TestMonitorPausedGuard** (3 tests)
- `test_paused_monitor_skips_poll_entirely` — is_paused=True → ReplyMonitor never instantiated
- `test_unpaused_monitor_instantiates_monitor_class` — is_paused=False → ReplyMonitor used
- `test_pause_resume_cycle_restores_expected_state` — off → on cycle has correct values

**TestQueueLifecycleScenario** (3 tests)
- `test_full_add_view_remove_clear_lifecycle` — sequential: add 3 → view(2) → remove(1) → positions shift → clear → empty
- `test_published_item_invisible_throughout_lifecycle` — published posts excluded from all operations
- `test_notified_post_not_re_notified_on_next_scheduler_run` — notified_at prevents double notification

**TestCrossFlowConsistency** (5 tests)
- `test_approval_card_always_contains_required_html_elements` — `<b>` tags always present
- `test_approval_keyboard_always_has_all_four_action_buttons` — approve/reject/defer/regenerate always present
- `test_recovery_summary_always_contains_all_four_state_labels` — all 4 file labels always in output
- `test_status_and_monitor_commands_both_use_is_paused` — source-level check via file read (avoids telegram lib import)
- `test_callback_parser_rejects_non_allowlisted_actions` — unknown actions (delete, auto_post, bypass) always rejected

**TestIdleReminderLifecycleScenario** (2 tests)
- `test_full_lifecycle_sequential` — record → 50h idle → send → cooldown → activity resets clock
- `test_fresh_install_never_triggers_reminder` — no file → no spam

**TestRecoveryLifecycleScenario** (4 tests)
- `test_all_missing_files_produce_no_errors` — fresh install safe
- `test_valid_post_queue_reports_pending_count` — valid file parsed correctly
- `test_corrupt_file_detected_startup_continues` — corrupt file → detected, no crash
- `test_run_startup_check_never_raises` — startup_check() never throws

### 2. `pytest.ini` — `critical` marker registered

```
markers =
    critical: Critical operator-flow regression tests — run before any large change
```

Command: `pytest -m critical -q --tb=short` (17 tests, ~0.3s)

### 3. `docs/regression_guide.md` (new)

Short operator/dev reference:
- What each test class protects
- Quick verification command
- What must pass before merging a large change
- Guidance for adding new critical tests
- Cross-reference table of locked areas → test files

---

## Files Changed

| File | Change |
|------|--------|
| `tests/test_critical_flows.py` | New: 5 classes, 17 tests |
| `pytest.ini` | +3 lines: `markers = critical: ...` |
| `docs/regression_guide.md` | New: operator/dev regression reference |

---

## Test Counts

- Before: 519 passed
- After: 536 passed (+17)
- 0 failures
- Critical-marked tests: 17 (`pytest -m critical` → 17 selected)

---

## Notes on Approach

- `test_status_and_monitor_commands_both_use_is_paused` reads `telegram_bot.py` as a text
  file rather than importing the module, to avoid the `cryptography/cffi` issue that
  affects all tests that `import app.telegram_bot`.
  (Same pattern as `test_intake_fast_path.py`'s inline copy approach.)

- All tests are pure logic tests — no external API calls, no DB writes, no file I/O
  outside `tmp_path`.

- No Layer 1 code was changed. All tests are additive.
