# Project Status

## Current Phase: v10 — Internal Hardening Complete

### What Works Now

**Core Pipeline**
- [x] Source intake (manual input via API or Telegram)
- [x] Gemini Researcher — background research & interpretation gap detection
- [x] OpenAI DraftWriter — English post draft generation
- [x] Perplexity FactChecker — fact verification
- [x] Claude Reviewer — quality & risk judgment (2-framework: 5-criteria + safety)
- [x] Telegram approval cards (Approve / Reject / Defer / Regenerate)
- [x] X publishing — approval-gated only; no publish without operator tap (real + mock modes)

**Quality & Safety**
- [x] 5-Criteria quality scorer (expertise / marketability / consistency / follower_quality / repeat_consumption)
- [x] Auto-reject + regenerate on quality failure (score < 50/100)
- [x] Reviewer-triggered regenerate loop (max 2 retries, hint-required guard)
- [x] Interpretation gap injection: Gemini gaps → DraftWriter context
- [x] criteria_signals → DraftWriter + Reviewer prompt injection (Layer 2)
- [x] VoiceGuard — AI phrase detection (19 patterns), ContentPack + single-draft approval card
- [x] RepetitionGuard — Jaccard similarity check against recent approved drafts (ContentPack)
- [x] Quality advisory — score_draft < 40 → 경고 표시 in approval card (advisory only)
- [x] Prompt banned list sync — DraftWriter + Reviewer rewrite 금지어 통일 (13개)
- [x] Claude DraftWriter 5-criteria pre-draft gate (marketability + expertise compact check)
- [x] Duplicate prevention (URL + text hash)
- [x] Daily rate limits (5 drafts / 5 telegrams / 10 posts — configurable via .env)
- [x] Community input risk escalation
- [x] No publish without human approval

**Content Fetching**
- [x] 3-strategy URL fallback: Direct → Jina AI Reader → Google Cache
- [x] Handles JS-rendered pages, partial paywall bypass

**Growth Pipelines**
- [x] PostQueue — optimal-slot approval-notification scheduler (KST: 9:00/10:30/12:00/13:30/15:00/19:00/21:00); posting requires operator tap, no auto-publish
- [x] CommentHunter — trend detection + reply draft generation
- [x] ReplyMonitor — mention polling + re-reply drafts
- [x] WeeklyReporter — 7-day metrics + AI analysis + content-mix section + perf summary (Monday 9am KST)
- [x] TopicMemory — 30-day tag frequency tracking, overuse detection
- [x] ContentPack — multi-draft suite (3 mains + short + replies + quote + thread)

**Operator Tools**
- [x] `/draft [url/text]` — skip analysis card, go straight to pipeline (fast path)
- [x] `/note <draft_id> <메모>` — save manual note to Draft.manual_notes (최대 500자)
- [x] `/hint <draft_id> <메모>` — save long-term hint with `[HINT]` prefix (DraftWriter에 우선 반영)
- [x] `/hint clear <draft_id>` — remove `[HINT]` lines only; plain notes and `[PERF]` preserved
- [x] `/hints` — list active `[HINT]` lines across recent approved/published drafts (audit view)
- [x] `/perf <draft_id> <메모>` — save post-publish performance note (`[PERF]` prefix)
- [x] `/perf` — list recent published drafts with performance notes
- [x] ContentRequest.note validator (500자 max, field_validator)
- [x] `/queue remove <n>` — remove item n from pending queue (1-indexed, operator-visible order)
- [x] `/queue clear` — remove all pending queue items (published items preserved)
- [x] `/monitor off/on/status` — pause/resume reply monitor; state persists across restarts
- [x] `/status` — AI providers + monitor state + queue count + last activity + approval mode
- [x] Idle pipeline reminder — Telegram alert after 48h inactivity (24h spam guard)
- [x] Approval card: topic_tags as #hashtags, char-count warning if > 280
- [x] Queue listing: 🔔 marker for posts with approval notification already sent
- [x] `/start` help text includes all active commands

**Operator Feedback & Hint System (Layer 2)**
- [x] `get_recent_operator_hints()` — reads `[HINT]` lines first, falls back to plain notes; injected into DraftWriter as `[OPERATOR HINTS]` block (Layer 2, try/except)
- [x] `format_perf_summary()` — aggregates `[PERF]` notes by category / topic_tags / output_format; surfaces 3 recent note texts; appended to `/report` and weekly report
- [x] Pattern analysis (v2) — cross-references `[PERF]` tags vs all published tags → "늘릴 후보 / 줄일 후보" lines in perf summary
- [x] Hint lifecycle complete: write (`/hint`) → read (`/hints`) → delete (`/hint clear`)
- [x] `format_hint_impact_summary()` — [HINT]×[PERF] co-occurrence: 3-bucket summary (both / perf-only / hint-only); appended to `/report` and weekly report (Layer 2)

**Business Classification (Phase 5)**
- [x] BusinessClassifier — auto-tag content by business purpose (growth/newsletter/premium/B2B/lead_magnet/sponsor)
- [x] CTA type recommendation per draft (follow/reply/newsletter_signup/lead_magnet/premium_waitlist/b2b_inquiry)
- [x] Monetization score (0-100) per draft
- [x] Asset goal classification (x_only/newsletter_push/lead_magnet_push/premium_teaser/b2b_asset)
- [x] Premium Brief candidate detection + reason
- [x] B2B research candidate detection + target audience + use case
- [x] `/biz` Telegram command (summary/premium/b2b/newsletter views)
- [x] Business tags shown in Telegram approval cards
- [x] 26 business classifier tests

**Infrastructure**
- [x] News monitor (Naver API, 1-min interval, cross-verify ≥4 sources)
- [x] Morning digest (sleep-period top-5, 5am KST)
- [x] RSS fetcher (Yonhap, Chosun, Hankyung, etc.)
- [x] Publish time prediction (category + risk → optimal slot)
- [x] Vision service (Claude Vision OCR)
- [x] FastAPI admin API + Swagger docs
- [x] Full audit trail in SQLite
- [x] Mock mode (all providers, zero API keys required)

### Safety Rules (Enforced in Code)

- No publish without human approval — zero exceptions, enforced in XPublisher and PostQueue
- politics / policy / economy / society always require approval
- `ENABLE_AUTO_POST_LOW_RISK=false` — flag exists, logic intentionally not built; auto-posting is not the current direction
- Duplicate text detection
- Daily usage limits
- No auto-like / follow / DM / reply

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health check |
| GET | `/status` | AI provider status |
| POST | `/ingest` | Submit source + run pipeline |
| GET | `/drafts/pending` | List pending drafts |
| GET | `/drafts/approved` | List approved drafts |
| GET | `/drafts/failed` | List failed drafts |
| GET | `/drafts/{id}` | Draft detail |
| POST | `/drafts/{id}/approve` | Approve + publish |
| POST | `/drafts/{id}/reject` | Reject draft |
| POST | `/drafts/{id}/retry` | Retry failed post |
| GET | `/usage` | Daily usage summary |

### Roadmap

| Version | Feature | Status |
|---------|---------|--------|
| v1 | Mock MVP — full pipeline | Done |
| v2 | Real X API + OpenAI/Claude | Done |
| v3 | Gemini / Grok / Perplexity integration | Done |
| v4 | 5-Criteria quality framework | Done |
| v4 | URL 3-strategy fallback (Jina AI) | Done |
| v4 | Growth pipelines (Queue/Hunter/Monitor) | Done |
| v4 | ContentPack (multi-draft output suite) | Done |
| v4 | criteria_signals → DraftWriter + Reviewer prompt injection | Done |
| v5 | RSS auto-collection & news monitor | Done |
| v5 | Topic memory + content-mix advisor | Done |
| v5 | Voice guard (anti-AI phrase detection) | Done |
| v5 | RepetitionGuard wiring into ContentPack | Done |
| v6 | Quality gate advisory (score display in Telegram) | Done |
| v6 | Operator manual note capture (/note command) | Done |
| v6 | Prompt quality audit document | Done |
| v6 | Prompt banned list sync (DraftWriter + Reviewer, 13 expressions) | Done |
| v6 | Claude DraftWriter 5-criteria compact gate | Done |
| v6 | VoiceGuard wired into single-draft approval card | Done |
| v7 | Content performance feedback loop v1 (/perf command + perf summary) | Done |
| v7 | Content performance feedback loop v2 (pattern analysis — 늘릴/줄일 후보) | Done |
| v7 | Operator note → DraftWriter hint pipeline v1 (get_recent_operator_hints) | Done |
| v7 | Operator hint [HINT] prefix priority over plain notes (v2) | Done |
| v7 | Hint lifecycle — /hint (write) · /hints (read) · /hint clear (delete) | Done |
| v7 | Content performance feedback loop v3 ([HINT]×[PERF] co-occurrence summary) | Done |
| v7 | PostQueue approval gate — remove auto-publish, require operator tap | Done |
| v8 | `/draft` fast-path (skip analysis card), content pack pending key fix | Done |
| v8 | Approval card: topic_tags, char-limit warning (>280) | Done |
| v8 | News monitor draft format parity (topic_tags, ai_rationale, char count) | Done |
| v8 | `/queue remove <n>` — operator queue management | Done |
| v8 | `/queue clear` — remove all pending items | Done |
| v8 | `/monitor off/on/status` — reply monitor pause toggle | Done |
| v8 | Idle pipeline reminder (48h threshold, 24h spam guard) | Done |
| v8 | `/status` improvements (monitor + queue + last activity) | Done |
| v8 | Queue listing: 🔔 notified marker, improved footer | Done |
| v9 | Reply monitor inline approval button (reply_use/reply_skip) | Done |
| v9 | `/queue view <n>` — full text + metadata for queued item (read-only) | Done |
| v10 | Rate limiter settings externalization (max_drafts/telegram/posts_per_day in Settings) | Done |
| v10 | OpenAI DraftWriter prompt refresh (audience, credibility>virality, expanded bans) | Done |
| v10 | Reviewer quality_flags (ReviewResult field + checklist in REVIEW_SYSTEM_PROMPT) | Done |
| v11 | Business classification layer (Phase 1-2): auto-tagging, CTA, monetization score | Done |
| v11 | Premium/B2B/Newsletter candidate detection + `/biz` command | Done |
| v11 | Business tags in Telegram approval cards | Done |
| — | Low-risk auto-posting (feature flag) | Deferred — not building without explicit operator directive |

### Locked Areas — Do Not Reopen

The following are complete and must not be reopened without explicit operator instruction:

- **Orchestrator Steps 1–7** — core pipeline structure locked
- **Layer 1 core flow** — ContentRequest → ContentPack → Telegram approval → X publish (approval-gated) → DB log
- **Main Telegram approval flow** — Approve / Reject / Defer / Regenerate callbacks
- **X publisher** — approval status check enforced; no bypass logic
- **PostQueue approval gate** — auto-publish removed; `try_publish_next()` sends notification only
- **hint / perf / operator workflow** — `/hint`, `/hints`, `/hint clear`, `/perf`, `/note`, `/report` complete and stable
- **5-criteria quality framework** — all 5 providers integrated, Reviewer gate, regenerate loop
- **Provider integrations** — Grok, Perplexity, Gemini, OpenAI, Anthropic — all complete
- **`/draft` fast-path** — `draft_command()` direct pipeline route, no analysis card
- **Posting pack standardization** — topic_tags display, char-limit warning, news monitor parity
- **`/queue remove <n>` and `/queue clear`** — operator queue management commands
- **`/monitor off/on/status`** — reply monitor toggle and state persistence
- **Idle pipeline reminder** — `activity_tracker.py`, 48h threshold, scheduler wired in `main.py`
- **Reply monitor inline button** — `reply_use`/`reply_skip` callbacks, `_pending_reply_drafts`
- **`/queue view <n>`** — read-only queue item detail (`get_pending_at`, same 1-indexed mapping)
- **Rate limiter settings externalization** — `max_drafts/telegram/posts_per_day` in Settings + .env.example
- **OpenAI DraftWriter prompt refresh** — audience block, credibility>virality, expanded banned phrases
- **Reviewer quality_flags** — `ReviewResult.quality_flags`, checklist in `REVIEW_SYSTEM_PROMPT`, parser

### Next Candidates

**Nothing urgent.** System is stable and well-tested (481 tests, 0 failures).
Operator tooling is complete. Internal hardening pass done.

Future work requires explicit operator directive before building. See Permanent Exclusions below.

### Permanent Exclusions

The following are out of scope and will not be built:

- Image generation (DALL-E, Stable Diffusion, thumbnails, any visual generation)
- Video / multimedia generation
- Auto-posting without approval
- Auto-like / auto-follow / auto-reply
- Web dashboard / analytics UI
- ML fine-tuning / embedding store / RAG
- Multi-user support

See `CLAUDE.md` for full project rules.
