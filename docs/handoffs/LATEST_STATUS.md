# Latest Status

## Current Phase
Phase 12 Growth Intelligence Bundle complete. Advisory labels (우선/보통/보류) wired into news alerts and draft approval cards. Weekly report upgraded with patterns + angles + source directions.

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
| Reply monitor inline button (reply_use/reply_skip, _pending_reply_drafts) | Locked |
| /queue view <n> (get_pending_at, read-only) | Locked |
| Rate limiter settings externalization (max_drafts/telegram/posts_per_day in Settings + .env.example) | Locked |
| OpenAI SYSTEM_PROMPT refresh (audience, credibility>virality, expanded bans, no editorializing) | Locked |
| Reviewer quality_flags (ReviewResult field + REVIEW_SYSTEM_PROMPT checklist + parse) | Locked |
| Growth Intelligence Bundle (advisory.py, source/draft labels, weekly report upgrade) | Locked |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded; `ENABLE_AUTO_POST_LOW_RISK` flag exists but logic not built
- Image / video generation
- Web dashboard / analytics UI
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration

---

## Next Candidates

**Nothing urgent.** System is stable and well-tested (495 tests).
Growth advisory layer now active. Operator tools complete.

---

## Last Updated

- Date: 2026-04-05 (session 4 — Growth Intelligence Bundle)
- Branch: claude/extract-prediction-time-n82UK
- Commit: see `git log --oneline -1`
