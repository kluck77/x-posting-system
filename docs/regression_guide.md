# Critical Flow Regression Guide

## What This Bundle Covers

`tests/test_critical_flows.py` contains scenario-level regression tests for the most
important operator-facing behaviors. These are the flows most likely to break silently
during future changes.

### Test classes

| Class | What it protects |
|-------|-----------------|
| `TestMonitorPausedGuard` | `/monitor off` must actually stop the scheduler from polling |
| `TestQueueLifecycleScenario` | Queue add → view → remove → clear works correctly as a sequence |
| `TestCrossFlowConsistency` | Approval card HTML, keyboard buttons, recovery summary structure, callback parser |
| `TestIdleReminderLifecycleScenario` | Idle reminder fires once, then respects cooldown |
| `TestRecoveryLifecycleScenario` | startup_check handles missing/valid/corrupt files without crashing |

---

## Quick Verification Command

Before any large change, run:

```bash
pytest -m critical -q --tb=short
```

This runs only the 17 critical-path tests and completes in under 1 second.

For the full suite:

```bash
pytest tests/ -q --tb=short
```

---

## What Must Pass Before Merging a Large Change

Any change that touches these areas must pass both commands above:

- `app/services/growth/reply_monitor.py` — monitor guard, reply inline buttons
- `app/services/growth/post_queue.py` — approval gate, queue operations
- `app/services/growth/activity_tracker.py` — idle reminder logic
- `app/services/growth/monitor_state.py` — pause/resume state
- `app/services/telegram_service.py` — approval card format, keyboard, callback parser
- `app/utils/startup_check.py` — state file inspection
- `app/telegram_bot.py` — command handlers

---

## Adding New Critical Tests

When a bug is fixed, add a regression test in `test_critical_flows.py` and mark it
`@pytest.mark.critical`. The test name should describe the original behavior, not the bug.

Example:
```python
@pytest.mark.critical
def test_paused_monitor_skips_poll_entirely(self):
    """is_paused=True → ReplyMonitor is never instantiated → no API calls."""
```

---

## Locked Areas

The following areas are locked and must not be reopened without explicit instruction.
Their tests live in the files listed — do not modify those test files without a matching
change to the locked area.

| Area | Test file |
|------|-----------|
| Orchestrator Steps 1–7 | `test_e2e.py` |
| Approval callbacks | `test_telegram_service.py` |
| PostQueue approval gate | `test_post_queue.py` |
| Reply monitor inline button | `test_reply_monitor.py` |
| Idle pipeline reminder | `test_activity_tracker.py` |
| Ops recovery | `test_startup_check.py` |
| Critical flows (all above combined) | `test_critical_flows.py` |
