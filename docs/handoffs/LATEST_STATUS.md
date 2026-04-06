# Latest Status

## ⚠️ LAST COMPLETED PHASE: 18-G (premium visual reconstruction)

**DO NOT re-implement the dashboard or control room. It is already built and locked.**

Phase 18-G (visual reconstruction) complete:
- **Hero card:** portrait-stage left column, `char-live` animation (translateY+rotate+scale), gradient headline, mini-stat row, worker pills strip
- **AI tab:** workstation cards — `worker-portrait` left column (currentColor bg + dark overlay + glow), each AI role has visual desk presence
- **Atmosphere:** 4-layer `body::before` radial gradients; deeper card glass (`backdrop-filter:blur(16px)`)
- **Pipeline:** larger nodes (48px), stronger pulse (scale + glow), wider connectors, faster flow animation
- **Naver card:** status strip banner with level color coding (ok/caution/warning/idle)
- **News items:** arrow bullet prefix
- **Ops:** section group headers, accent color on non-zero values
- **Safari fix:** hero-ring-pulse keyframes include `translateX(-50%)` to prevent centering regression
- 579 tests passing, 23 critical flows protected
- Commit: `d5e906a`

---

## Current Phase Detail

**Phase 18 — Mobile Control Room Bundle** (complete + production-deployed)

What was built in Phase 18:
1. `app/services/naver_usage.py` — Naver API daily call counter
2. `app/api/control_room.py` — `/control/status`, `/control/providers`, `/control/flow-trace`, `/control/naver`, `/control/recent-news` endpoints
3. `static/dashboard.html` — mobile-first 4-tab dashboard (Status / AI / Intake / Ops), Safari-optimized, safe-area insets, 30s auto-refresh
4. `app/telegram_bot.py` — `/menu` command with InlineKeyboard (✍️초안 / 📋큐 / 📊상태 / 👀모니터 / 🛟복구)
5. `tests/test_control_room.py` — 37 tests for all control room endpoints
6. `tests/test_critical_flows.py` — 6 new critical tests for quick menu
7. `deploy_dashboard.sh` — VPS deployment script (systemd service, port 8000)

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
| **18** | **Control Room dashboard (naver_usage, control_room.py, dashboard.html, 37 tests, docs/control_room.md)** | **Locked** |
| **18** | **Telegram /menu quick-action buttons (_handle_quick_callback, 6 critical tests)** | **Locked** |
| **18-C** | **Premium Polish: card shadows, mascot/dot animations, role taglines, Naver context, Telegram UX** | **Locked** |
| **18-C fix** | **Safari transform conflict fix (mascot-idle keyframe), deploy_dashboard.sh** | **Locked** |
| **18-G** | **Premium visual reconstruction (portrait hero, workstation AI cards, atmosphere, pipeline, Naver status strip)** | **Locked** |

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

**Optional next: Phase 18-E (visual premium pass)**
The dashboard is functional and correct. A cinematic premium redesign was scoped but not yet built:
- Atmospheric `body::before` radial gradient bg
- Glass card morphism (`backdrop-filter: blur(12px)`, rgba surface, inset highlight)
- Hero card with integrated stat strip + worker pills strip
- AI worker cards: left `::before` accent bar
- Naver SVG circular arc gauge (r=32, circ≈201.1)
- Flowing pipeline connector animation
This is purely visual — no API or logic changes required. Operator can request it explicitly.

---

## Last Updated

- Date: 2026-04-06 (session 14 — Phase 18-G visual reconstruction)
- Branch: claude/extract-prediction-time-n82UK
- Key commits:
  - `d5e906a` — Phase 18-G (portrait hero, workstation AI cards, atmosphere, pipeline, Naver strip)
  - `0979853` — Phase 18-F (visual reconstruction base)
  - `b04da8e` — Phase 18-E (cinematic premium pass)
  - `f1304e5` — Phase 18-C fix (Safari mascot animation + card depth)
  - `776dd92` — deploy_dashboard.sh
- Run `git log --oneline -8` to see recent commits
