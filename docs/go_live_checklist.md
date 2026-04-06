# Go-Live Checklist

Use this before the first real post. Work through each section in order.

---

## 1. Environment Setup

- [ ] Copied `.env.example` → `.env` (do not edit `.env.example` directly)
- [ ] Set `TELEGRAM_BOT_TOKEN` — create a bot via @BotFather on Telegram, send `/newbot`
- [ ] Set `TELEGRAM_CHAT_ID` — run `python scripts/get_telegram_chat_id.py` to find yours
- [ ] Set `X_USERNAME` to your X account name (no @ symbol)
- [ ] Set all five X API credentials from [developer.x.com](https://developer.x.com):
  - `X_BEARER_TOKEN`
  - `X_API_KEY`
  - `X_API_SECRET`
  - `X_ACCESS_TOKEN`
  - `X_ACCESS_TOKEN_SECRET`
- [ ] X app has **"Read and Write"** permissions (not Read-only)
- [ ] AI keys are **optional** — the system works in Mock mode without them

> **Tip:** You need exactly 7 keys to go fully live (2 Telegram + 5 X API). Everything else is optional.

---

## 2. Quick Verification (before first start)

```bash
# Run critical flow tests — takes under 1 second
pytest -m critical -q --tb=short
```

- [ ] Output shows `17 passed` with 0 failures
- [ ] No errors about missing imports

If any test fails, do not proceed — check `docs/regression_guide.md`.

---

## 3. First Startup

```bash
python run.py
```

Within 10 seconds you should see all of:

- [ ] `[Startup] 상태 파일 점검 완료 — ...`
- [ ] `FastAPI 서버 시작: http://localhost:8000`
- [ ] `텔레그램 봇 시작...`

**Acceptable** at startup (not blocking):
- `AI 프로바이더: mock` — normal if you haven't set AI keys yet
- `뉴스 모니터 비활성` — normal if `MONITOR_ENABLED=false`

**Blocking** — fix before continuing:
- `[Startup] 상태 파일 손상 감지: ['...']` → delete the named file from `data/` and restart
- Bot token or chat ID errors → re-check `.env` values

---

## 4. Telegram Smoke Test

With the bot running, send these commands from Telegram:

- [ ] `/status` → reply shows AI providers, queue count, monitor state
- [ ] `/recover` → reply shows ✅ or ⚪ for each state file (no ❌)
- [ ] `/draft test post` → approval card arrives with 4 buttons: **Approve · Reject · Defer · Regenerate**
- [ ] Tap **Reject** on the test card → bot acknowledges

---

## 5. First Real Draft (Mock Mode)

- [ ] Sent `/draft <real news URL>` → approval card arrived
- [ ] Card contains a readable English draft
- [ ] Tapping **Reject** removes the card cleanly

> If AI keys are not yet set, the draft text will be a mock placeholder. That is expected and safe.

---

## 6. First Live Post

- [ ] AI keys are configured and provider shows as live in `/status`
- [ ] Sent `/draft <news URL>` → approval card arrived with real AI content
- [ ] **Read the draft carefully** — you are responsible for what gets posted
- [ ] Tapped **Approve** → tweet appeared on your X account within a few seconds

---

## 7. Ongoing Operation

- [ ] Read [OPERATOR_WORKFLOW.md](OPERATOR_WORKFLOW.md) — command guide for daily use
- [ ] Know the `/recover` command — run it anytime the system seems off
- [ ] `ENABLE_AUTO_POST_LOW_RISK=false` in `.env` — **never change this**
- [ ] Rate limits in `.env` match your posting budget (`MAX_DRAFTS_PER_DAY`, `MAX_POSTS_PER_DAY`)

---

## What "Ready to Go Live" Means

The system is safe to use when:

- ✅ All 17 critical tests pass (`pytest -m critical -q`)
- ✅ Startup log shows no corruption warnings
- ✅ `/status` returns the correct state
- ✅ You received and tapped at least one test approval card
- ✅ You understand that **Approve is the only way a tweet gets posted**
