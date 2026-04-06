# Release Readiness Summary

A plain-language summary of what this system can do, what it won't do, and what is your responsibility as the operator.

---

## System State

| Metric | Value |
|--------|-------|
| Automated tests | 536 passing, 0 failing |
| Critical-flow tests | 17 (run with `pytest -m critical -q`) |
| Auto-posting | Disabled — flag exists in config, logic intentionally not built |
| Mock mode | Fully functional without any API keys |
| Last locked version | v10 + Phases 11–16 |

---

## What Is Locked and Stable

These areas are production-grade. They are protected by automated tests and will not change without explicit decision.

| Area | What It Does |
|------|-------------|
| Draft pipeline | News/text → AI research → English draft → fact-check → quality review → Telegram card |
| Approval gate | No tweet is posted without your tap. No exceptions, no bypass. |
| Post queue | Posts wait for your approval notification. No automatic release. |
| Quality framework | 5 criteria scored automatically. Weak drafts are regenerated, not sent. |
| Reply monitor | Monitors your X mentions. Shows draft replies for you to use or skip. |
| Rate limits | Max drafts, approvals, and posts per day — configurable in `.env`. |
| Operator commands | `/draft`, `/queue`, `/monitor`, `/hint`, `/perf`, `/report`, `/recover` — all stable. |
| Startup self-check | On startup, all state files are validated. Corruption is detected and logged. |

---

## What Is Permanently Excluded

These will never be part of this system:

- Posting without your approval
- Auto-like, auto-follow, auto-DM, auto-reply
- Image or video generation of any kind
- A web analytics dashboard
- Multi-user support
- Any spam or engagement manipulation

---

## What Requires Your Judgment

The system prepares drafts. You decide what gets posted.

| Decision | You decide |
|----------|-----------|
| Is this draft accurate? | Read every draft before tapping Approve. |
| Is the tone right for your brand? | Use `/hint <id> <rule>` to teach the AI your preferences over time. |
| Is this news story worth covering? | News alerts arrive automatically — you choose whether to draft. |
| Should I respond to this mention? | Reply monitor shows draft suggestions — you tap Use or Skip. |
| Is timing right for this post? | Queue for an optimal slot or post immediately. Your call. |

---

## Documents

| Document | Purpose |
|----------|---------|
| [go_live_checklist.md](go_live_checklist.md) | Step-by-step before first live post |
| [pre_run_guide.md](pre_run_guide.md) | Startup verification and what success looks like |
| [OPERATOR_WORKFLOW.md](OPERATOR_WORKFLOW.md) | Daily command guide |
| [recovery_playbook.md](recovery_playbook.md) | When something goes wrong |
| [regression_guide.md](regression_guide.md) | Test coverage reference (for developers) |

---

## What to Check Before Each Session

1. Is the bot running? (`python run.py` if not)
2. Any errors in the terminal? (look for `[Startup] 손상 감지`)
3. `/status` in Telegram → queue and monitor state look right?

That's it. The system handles the rest automatically.
