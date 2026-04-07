# Control Room — Operator Guide

## Opening the Dashboard

Start the server, then open in browser:

```
http://localhost:8000/control/
```

Auto-refreshes every 30 seconds. No login required.

---

## Panels

### System Health
Five indicator dots — green = OK, red = problem.

| Dot | What it means |
|-----|--------------|
| DB | SQLite database readable |
| Telegram | Bot token + chat ID configured |
| X/Twitter | All 4 X API credentials set |
| Mock Mode | ON = no real API calls (safe for testing) |
| Auto-Post | Should always show OFF — manual approval is the only path |

**Action required:** Any red dot except Auto-Post means a missing credential. Check `.env`.

---

### Queue
Pending items waiting for operator approval. Numbers only — the queue never self-publishes.

- **Pending** — drafts queued but not yet reviewed
- **Total** — all items ever added this session
- **Last Published** — timestamp of most recent approved post

> If pending count grows and you haven't reviewed in a while, check Telegram for unread approval cards.

---

### Daily Quota
Three gauge bars showing today's usage vs configured limits.

| Bar | Limit source |
|-----|-------------|
| Drafts | `MAX_DRAFTS_PER_DAY` in `.env` |
| Telegram | `MAX_TELEGRAM_PER_DAY` in `.env` |
| Posts | `MAX_POSTS_PER_DAY` in `.env` |

**Caution (yellow):** 50–79% used. **Warning (red):** 80%+ used. Posting is blocked at 100%.

---

### AI Providers
One card per pipeline role. Shows which provider is active and whether it is configured (API key present).

| Role | Default Provider |
|------|-----------------|
| DraftWriter | OpenAI |
| Reviewer | Anthropic (Claude) |
| Researcher | Gemini |
| FactChecker | Perplexity |
| TrendHunter | Grok (manual `/trends` only) |

**Runs Today** is the number of drafts created today — used as a proxy since per-provider call counts are not tracked individually.

---

### News / Reply Monitor
- **Reply Monitor** — paused/active status. Use `/monitor off` in Telegram to pause.
- **Pending Reply Drafts** — reply drafts waiting for inline approval in Telegram.
- **News Monitor** — counts of pending articles, story clusters, alerted stories, overnight buffer.

> High overnight buffer (10+) means many articles arrived while you were away. They will be processed in the next news monitor cycle.

---

### Naver Quota
Estimated Naver Open API calls today (25,000/day limit).

| Level | Meaning |
|-------|---------|
| idle | No calls yet today |
| ok | Under 50% |
| caution | 50–79% |
| warning | 80%+ — consider reducing search frequency |

**Note:** Counter resets on server restart. Treat as an estimate, not an exact count.

---

### Flow Trace
Recent drafts in reverse-chronological order. Shows each draft's journey through the pipeline.

| Column | Meaning |
|--------|---------|
| ID | Draft database ID |
| Hook | First line of the draft (truncated) |
| Category | Content category |
| Risk | low / medium / high |
| Status | Current approval state |
| Created | KST creation time |
| Published | KST publish time (if posted) |

**Status badge colors:**
- Gray: `pending`
- Blue: `approved`
- Green: `published`
- Red: `rejected` / `failed`
- Orange: `deferred`
- Purple: `regenerate`

---

## What Requires Action vs What Is Advisory

### Actionable (requires operator response)
- Red health dot for DB, Telegram, or X — fix credentials
- Daily quota bar at 100% — no new drafts/posts until tomorrow
- Pending queue count growing — review Telegram approval cards
- Reply monitor paused and you've forgotten — run `/monitor on`

### Advisory (informational only)
- AI provider configured status — shows current setup, no action needed unless wrong
- Naver quota level "caution" — monitor, but no action until "warning"
- Flow trace statuses — historical record, not a to-do list
- Overnight buffer count — clears automatically on next cycle

---

## Raw API Endpoints

If you prefer JSON over the dashboard UI:

| Endpoint | Description |
|----------|-------------|
| `GET /control/status` | Full system snapshot |
| `GET /control/flow-trace?limit=20` | Recent N drafts |
| `GET /control/providers` | AI provider details |
| `GET /control/naver` | Naver quota only |
| `GET /health` | Simple health check |
| `GET /status` | AI provider config summary |
| `GET /usage` | Rate limiter daily summary |
