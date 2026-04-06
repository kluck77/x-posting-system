# Pre-Run Verification Guide

Run these checks before starting the bot for the first time or after any significant change.
Each check takes under 1 minute.

---

## Check 1 — Critical Flow Tests

```bash
pytest -m critical -q --tb=short
```

| Result | What It Means |
|--------|--------------|
| `17 passed` | All critical flows verified — safe to start |
| Any failure | Something regressed — do not start until fixed |

**Time:** ~0.3 seconds

---

## Check 2 — Start the Bot

```bash
python run.py
```

### Expected startup log (within 10 seconds)

```
X Posting System 시작
AI 프로바이더 상태: {...}
데이터베이스 초기화 완료
[Startup] 상태 파일 점검 완료 — post_queue: N개 대기 / M개 전체, ...
FastAPI 서버 시작: http://localhost:8000
텔레그램 봇 시작...
```

### Acceptable warnings — not blocking

| Log message | Meaning | Action needed |
|-------------|---------|---------------|
| `AI 프로바이더: mock` | No AI key for this role | Add key when ready; mock works fine |
| `뉴스 모니터 비활성` | `MONITOR_ENABLED=false` | Normal if monitor is off |
| `Growth 파이프라인 스케줄러 등록 실패` | apscheduler not installed | `pip install apscheduler` |

### Blocking errors — fix before continuing

| Log message | What to do |
|-------------|-----------|
| `[Startup] 상태 파일 손상 감지: ['post_queue']` | Delete `data/post_queue.json`, restart |
| `[Startup] 상태 파일 손상 감지: ['processed_replies']` | Delete `data/processed_replies.json`, restart |
| `Invalid token` or `Unauthorized` (Telegram) | Re-check `TELEGRAM_BOT_TOKEN` in `.env` |
| `Telegram bot token not set` | Add `TELEGRAM_BOT_TOKEN` to `.env` |

---

## Check 3 — Telegram Smoke Test

Send these commands and confirm the expected response arrives within 30 seconds:

| Command | Expected response |
|---------|------------------|
| `/status` | Status card: AI providers · queue count · monitor state |
| `/recover` | File check: ✅ valid · ⚪ missing (normal on first run) · ❌ corrupt (fix needed) |

**Blocking:** No response within 30 seconds → Telegram credentials wrong or bot not running

---

## Check 4 — Draft Test

```
/draft test
```

**Success:** Approval card arrives with 4 buttons (Approve · Reject · Defer · Regenerate)

**What you'll see in Mock mode:** Placeholder draft text — this is normal without AI keys

**Blocking:** No card arrives, bot crashes, or error message appears

---

## What to Do If Something Fails

| Failure | First step |
|---------|-----------|
| Tests fail | Read the failure output. Check recent changes to files in the error. |
| Bot won't start | Read the full terminal output for the specific error line. |
| Telegram not responding | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. |
| `/recover` shows ❌ | Delete the named file from `data/` directory and restart. |
| Draft card never arrives | Check logs for AI provider errors. Mock mode should always work. |

For state-file issues, see [recovery_playbook.md](recovery_playbook.md).

---

## Full Test Suite (optional, ~2 seconds)

Run the full suite when making code changes:

```bash
pytest tests/ -q --tb=short
```

Expected: `536 passed, 2 warnings`
