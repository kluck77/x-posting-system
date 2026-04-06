# Latest Status

## Current Phase
Phase 18 complete (Mobile Control Room + Telegram Quick Menu). 4-tab mobile dashboard at `http://localhost:8000/control/`. `/menu` command added with 5 quick-action inline buttons. 579 tests passing.

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
| Phase 13 news_regen fix (article retained for regen button) | Locked |
| Phase 14 hygiene bundle (processed_replies cap, x_username config, pending_articles cap) | Locked |
| Phase 15 ops recovery bundle (startup_check, /recover command, corrupt-file warning, recovery_playbook.md) | Locked |
| Phase 16 critical flows regression bundle (test_critical_flows.py, pytest -m critical, regression_guide.md) | Locked |
| Phase 17 release gate bundle (go_live_checklist.md, pre_run_guide.md, release_readiness.md, README links fixed) | Locked |
| Phase 17 Control Room Bundle (naver_usage.py, control_room.py, dashboard.html, test_control_room.py, docs/control_room.md) | Locked |
| Phase 18 Mobile Control Room Bundle (mobile-first 4-tab dashboard rewrite, /control/recent-news endpoint) | Locked |
| Phase 18 Telegram Quick Menu (/menu command, _handle_quick_callback, 5 quick-action buttons, 6 critical tests) | Locked |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded; `ENABLE_AUTO_POST_LOW_RISK` flag exists but logic not built
- Image / video generation
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration

---

## Next Candidates

**System is operator-ready.** 579 tests passing, 23 critical flows protected, go-live docs in place.
Control Room dashboard: `http://localhost:8000/control/` — mobile-first, 4-tab, Safari-optimized.
Telegram quick menu: `/menu` → 5 inline buttons (초안/큐/상태/모니터/복구).
No open feature gaps. Next actions are entirely operator-driven.

---

## Last Updated

- Date: 2026-04-06 (session 11 — Phase 18 Telegram Quick Menu)
- Branch: claude/extract-prediction-time-n82UK
- Commit: see `git log --oneline -1`
