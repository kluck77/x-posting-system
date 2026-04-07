# Latest Status

## ⚠️ LAST COMPLETED PHASE: Pixel HUD Dashboard Refinement (S19)

**S19 — Refinement on top of S18 dashboard (`static/dashboard.html` only):**
- Full Korean UI localization (chrome / Home / AI / Intake / Ops, all operator-facing text)
- Mobile readability scale-up: base font 13→15px, KPI numbers 26→**46px**, Ops big 18→**30px**, AI runs 18→**30px**, Hero state 22→**34px**
- Lucky cat → system-aware state machine: `alert` (db down, ear twitch only) / `idle` (slow tail) / `coin-rush` (premium·b2b candidates → fast coin + gold glow) / `lean-weekly` (highlights → tilt toward weekly panel) / `healthy` (lucky-pulse + blink + tail)
- Removed decorative random patrol; cat now reflects real signals from `/control/status` + `/control/business-summary`
- No backend / schema / test changes

## ⚠️ PREVIOUS PHASE: Pixel HUD Dashboard Rebuild (S18)

**DO NOT re-implement premium/b2b/email/lead base services. They are built and tested.**
**DO NOT revert to portrait/Live2D dashboard — it has been replaced with a pixel HUD.**

Session 18 — Full dashboard rebuild from scratch:
- New `static/dashboard.html` (1128 lines) — pixel-digital control room, no images, no Live2D
- 4 rebuilt pages: Home / AI Workstations / Intake Flow / Ops Monitoring
- Lucky cat SVG mascot on Home (blink/tail/paw/patrol/lucky-pulse, prefers-reduced-motion safe)
- Backend: `/control/business-summary` aggregates premium/brief/b2b/newsletter/weekly/cta perf
- 5 AI workstation nodes with role-specific motion (typing/blink/scan/check/pulse)
- 6 Ops cards surface entire business stack with monetization-ready signals
- `static/live2d.js` deleted; old dashboard preserved as `dashboard.html.backup`

Session 15–17 (still locked):
- **B2B sample report** — `generate_sample_report()`, `/b2b report <id> [save|export]`
- **Brief offer layer** — `BriefOfferService`, `/brief` (8 subcommands), 3 new columns
- **Newsletter routine** — `NewsletterRoutineService`, `/newsletter` (7 subcommands)
- **Weekly report** — `WeeklyReportService`, `/weekly` (summary/view/export)
- **CTA copy library** — `CtaCopyService`, `CtaCopy` model, `/cta copy` (9 subcommands), draft linking
- **CTA copy perf tracking** — `get_copy_perf`, `get_all_perf`, `/cta perf` (3 subcommands)
- **Weekly CTA perf section** — `_cta_perf_summary()`, `/weekly view`·`/weekly export` 통합
- 896 tests passing, all flows protected

---

## Current Phase Detail

**Session 15–16 — Business Operating Layers + CTA Copy + Perf** (complete)

What was built:
1. `app/services/b2b_candidate_service.py` — `generate_sample_report`, `format_sample_report`, `save_report_to_note`
2. `app/services/brief_offer_service.py` — NEW (BriefOfferService)
3. `app/services/newsletter_routine_service.py` — NEW (NewsletterRoutineService)
4. `app/services/weekly_report_service.py` — NEW (WeeklyReportService)
5. `app/services/cta_copy_service.py` — NEW (CtaCopyService + perf tracking)
6. `app/models/content.py` — `CtaCopy` model + 4 columns (`brief_type`, `brief_price_tier`, `brief_summary_note`, `cta_copy_id`)
7. `app/db.py` — 4 migration entries
8. `app/telegram_bot.py` — `/b2b report`, `/brief`, `/newsletter`, `/weekly`, `/lead export`, `/cta copy`, `/cta link/unlink`, `/cta perf`
9. Tests: `test_cta_copy.py` (52), `test_brief_offer.py` (38), `test_newsletter_routine.py` (29), `test_weekly_report.py` (26), `test_b2b_candidate.py` (+20)

---

## Closed (Done and Locked)

| Phase | Area | Status |
|-------|------|--------|
| — | Orchestrator Steps 1–7 | Locked |
| — | Layer 1 core flow (ContentRequest → XPublisher) | Locked |
| — | Telegram approval callbacks (approve/reject/defer/regenerate) | Locked |
| — | PostQueue approval gate (notification-only, no auto-publish) | Locked |
| — | hint / perf / operator workflow | Locked |
| — | 5-criteria quality framework | Locked |
| — | Provider integrations (Grok, Perplexity, Gemini, OpenAI, Anthropic) | Locked |
| — | /draft fast-path | Locked |
| — | Posting pack standardization | Locked |
| — | /queue remove, /queue clear, /queue view | Locked |
| — | /monitor off/on/status | Locked |
| — | Idle pipeline reminder | Locked |
| — | /status improvements | Locked |
| — | Reply monitor inline button | Locked |
| — | Rate limiter settings externalization | Locked |
| — | OpenAI SYSTEM_PROMPT refresh | Locked |
| — | Reviewer quality_flags | Locked |
| 12 | Growth Intelligence Bundle | Locked |
| 13–17 | news_regen, hygiene, ops recovery, critical flows, release gate | Locked |
| **18** | **Control Room dashboard + /menu** | **Locked** |
| **18-I** | **Material rebuild: split-stage hero, standalone AI cards** | **Locked** |
| **S15** | **B2B sample report (/b2b report)** | **Locked** |
| **S15** | **Brief offer layer (/brief, BriefOfferService)** | **Locked** |
| **S15** | **Newsletter routine (/newsletter, NewsletterRoutineService)** | **Locked** |
| **S15** | **Weekly report (/weekly, WeeklyReportService)** | **Locked** |
| **S15** | **CTA copy library (/cta copy, CtaCopyService, CtaCopy model)** | **Locked** |
| **S16** | **CTA copy perf tracking (/cta perf)** | **Locked** |
| **S17** | **Weekly CTA perf section (/weekly view·export)** | **Locked** |
| **S18** | **Pixel HUD dashboard rebuild (4 pages + mascot + business-summary)** | **Locked** |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded
- Image / video generation
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration
- Payment flow / checkout
- Full email sender
- Dashboard analytics / BI charts
- A/B testing / page builder

---

## Next Candidates

**System is fully operator-ready. Nothing urgent is missing.**
896 tests passing, all flows protected.
Full operating layer stack: premium, B2B, brief, newsletter, lead, weekly report, CTA copy library + perf.

---

## Last Updated

- Date: 2026-04-07 (session 18 — Pixel HUD Dashboard Rebuild)
- Branch: claude/extract-prediction-time-n82UK (aligned to claude/premium-control-room-ui-LJFba)
- Key commits:
  - Pixel HUD dashboard rebuild (dashboard.html + lucky cat mascot)
  - `dd0190a` — /control/business-summary 단일 집계 엔드포인트
  - `8985b62` — Weekly CTA perf section (_cta_perf_summary + /weekly 통합)
  - `7cb6e21` — CTA copy perf tracking (/cta perf + tests)
  - `9e541e5` — CTA copy library (/cta copy + draft linking)
  - `70a186f` — Weekly operating report (/weekly)
  - `da09c92` — Newsletter/lead routine (/newsletter, /lead export)
  - `22e242a` — Brief offer layer (/brief)
  - `1563849` — B2B sample report (/b2b report)
- Run `git log --oneline -10` to see recent commits
