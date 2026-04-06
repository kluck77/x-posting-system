# Latest Status

## ⚠️ LAST COMPLETED PHASE: 18-I (material dashboard rebuild + real character assets)

**DO NOT re-implement the dashboard or control room. It is already built and locked.**

Phase 18-I complete:
- **Hero — split-stage layout:** white character stage (160px) + dark info panel
  `mix-blend-mode: multiply` on white bg = character colors preserved, white areas disappear
  Strong right-fade gradient bridges portrait→panel. min-height 230px. 3-stat grid tiles.
- **AI page — standalone profile cards:** outer `.card` wrapper removed entirely.
  Each worker is an independent card (border-radius 18px, own shadow, own glass bg, own glow).
  Portrait 100px wide. Left role-color accent bar. Card entrance animation with stagger.
- **Naver arc gauge:** enlarged to 130×130px (r=52, circ=326.7), centered column layout.
- **In-dashboard asset upload:** `POST /control/upload-asset` (Ops tab) — operator uploads
  character PNGs from phone without SSH. Whitelist enforced. 10MB limit.
- **Real image paths wired:**
  `/static/hero_blonde_assistant.png`, `draftwriter.png`, `reviewer.png`,
  `researcher.png`, `trendhunter_black.png` — all with onerror emoji fallbacks.
- 579 tests passing, 23 critical flows protected
- Commits: `291fc3c` (18-I), `3d93b96` (18-H assets+upload), `d5e906a` (18-G)

---

## Current Phase Detail

**Phase 18 — Mobile Control Room Bundle** (complete + production-deployed)

What was built in Phase 18 through 18-I:
1. `app/services/naver_usage.py` — Naver API daily call counter
2. `app/api/control_room.py` — `/control/status`, `/control/providers`, `/control/flow-trace`,
   `/control/naver`, `/control/recent-news`, `POST /control/upload-asset`
3. `static/dashboard.html` — mobile-first 4-tab dashboard, Safari-optimized, split-stage hero,
   standalone AI profile cards, real character image assets, 30s auto-refresh
4. `app/telegram_bot.py` — `/menu` command with InlineKeyboard
5. `tests/test_control_room.py` — 37 tests
6. `tests/test_critical_flows.py` — 6 critical tests
7. `deploy_dashboard.sh` — VPS deployment script

---

## Closed (Done and Locked)

| Phase | Area | Status |
|-------|------|--------|
| — | Orchestrator Steps 1–7 | Locked |
| — | Layer 1 core flow (ContentRequest → XPublisher) | Locked |
| — | Telegram approval callbacks (approve/reject/defer/regenerate) | Locked |
| — | PostQueue approval gate (notification-only, no auto-publish) | Locked |
| — | hint / perf / operator workflow (/hint, /hints, /hint clear, /perf, /note, /report) | Locked |
| — | 5-criteria quality framework | Locked |
| — | Provider integrations (Grok, Perplexity, Gemini, OpenAI, Anthropic) | Locked |
| — | /draft fast-path | Locked |
| — | Posting pack standardization (topic_tags, char warning) | Locked |
| — | /queue remove, /queue clear, /queue view | Locked |
| — | /monitor off/on/status | Locked |
| — | Idle pipeline reminder (activity_tracker.py) | Locked |
| — | /status improvements | Locked |
| — | Reply monitor inline button (reply_use/reply_skip) | Locked |
| — | Rate limiter settings externalization | Locked |
| — | OpenAI SYSTEM_PROMPT refresh | Locked |
| — | Reviewer quality_flags | Locked |
| 12 | Growth Intelligence Bundle (advisory.py, source/draft labels, weekly report) | Locked |
| 13 | news_regen fix (article retained for regen button) | Locked |
| 14 | Hygiene bundle (processed_replies cap, x_username, pending_articles cap) | Locked |
| 15 | Ops recovery bundle (startup_check, /recover, recovery_playbook.md) | Locked |
| 16 | Critical flows regression bundle (test_critical_flows.py, pytest -m critical) | Locked |
| 17 | Release gate bundle (go_live_checklist.md, pre_run_guide.md, release_readiness.md) | Locked |
| **18** | **Control Room dashboard (naver_usage, control_room.py, dashboard.html, 37 tests)** | **Locked** |
| **18** | **Telegram /menu quick-action buttons (_handle_quick_callback, 6 critical tests)** | **Locked** |
| **18-C** | **Premium Polish: card shadows, mascot animations, role taglines, Naver context** | **Locked** |
| **18-C fix** | **Safari transform conflict fix (mascot-idle keyframe), deploy_dashboard.sh** | **Locked** |
| **18-G** | **Visual reconstruction (portrait hero, workstation AI cards, atmosphere, pipeline)** | **Locked** |
| **18-H** | **Real character image assets + in-dashboard upload UI (POST /control/upload-asset)** | **Locked** |
| **18-I** | **Material rebuild: split-stage hero, standalone AI cards, large Naver gauge** | **Locked** |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded; `ENABLE_AUTO_POST_LOW_RISK` flag exists but logic not built
- Image / video generation
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration

---

## Next Candidates

**System is fully operator-ready. Nothing urgent is missing.**
579 tests passing, 23 critical flows protected, go-live docs in place.
VPS deployed at 107.191.61.190:8000/control/ via deploy_dashboard.sh.

Character images on VPS: hero_blonde_assistant.png, draftwriter.png, reviewer.png,
researcher.png, trendhunter_black.png — uploaded via Ops tab upload UI.

---

## Last Updated

- Date: 2026-04-06 (session 14 — Phases 18-G / 18-H / 18-I)
- Branch: claude/extract-prediction-time-n82UK
- Key commits:
  - `291fc3c` — Phase 18-I (split-stage hero, standalone AI cards, large Naver gauge)
  - `3d93b96` — Phase 18-H (real character assets + upload UI)
  - `d5e906a` — Phase 18-G (portrait hero, workstation cards, atmosphere)
  - `f1304e5` — Phase 18-C fix (Safari animation)
  - `776dd92` — deploy_dashboard.sh
- Run `git log --oneline -8` to see recent commits
