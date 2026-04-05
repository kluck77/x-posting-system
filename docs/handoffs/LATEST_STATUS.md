# Latest Status

## Current Phase
v8 complete. Awaiting operator instruction for v9.

---

## Closed (Done and Locked)

| Area | Status |
|------|--------|
| Orchestrator Steps 1–7 | Locked |
| Layer 1 core flow (ContentRequest → XPublisher) | Locked |
| Telegram approval callbacks (approve/reject/defer/regenerate) | Locked |
| PostQueue approval gate (notification-only, no auto-publish) | Locked |
| hint / perf / operator workflow (/hint, /hints, /hint clear, /perf, /note, /report) | Locked |
| 5-criteria quality framework | Locked |
| Provider integrations (Grok, Perplexity, Gemini, OpenAI, Anthropic) | Locked |
| /draft fast-path | Locked |
| Posting pack standardization (topic_tags, char warning) | Locked |
| /queue remove <n> | Locked |
| /queue clear | Locked |
| /monitor off/on/status | Locked |
| Idle pipeline reminder (activity_tracker.py) | Locked |
| /status improvements | Locked |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded; `ENABLE_AUTO_POST_LOW_RISK` flag exists but logic not built
- Image / video generation
- Web dashboard / analytics UI
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration

---

## Next Candidates (v9)

**A — Reply monitor inline approval button** *(recommended next)*
- Re-reply drafts currently go out as plain text with no action button
- All other paths have inline keyboard buttons; this is the one gap
- Risk: low (growth service only, Layer 2)

**B — `/queue view <n>` detail command** *(defer)*
- Queue listing shows 60-char truncates; no way to read full text before slot fires
- Risk: very low (read-only)

---

## Last Updated

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Commit: see `git log --oneline -1`
