# Project Status

## Current Phase: v7 — Operator Feedback & Hint Lifecycle Complete

### What Works Now

**Core Pipeline**
- [x] Source intake (manual input via API or Telegram)
- [x] Gemini Researcher — background research & interpretation gap detection
- [x] OpenAI DraftWriter — English post draft generation
- [x] Perplexity FactChecker — fact verification
- [x] Claude Reviewer — quality & risk judgment (2-framework: 5-criteria + safety)
- [x] Telegram approval cards (Approve / Reject / Defer / Regenerate)
- [x] X publishing (Mock + real API)

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
- [x] Daily rate limits (5 drafts / 5 telegrams / 3 posts)
- [x] Community input risk escalation
- [x] No publish without human approval

**Content Fetching**
- [x] 3-strategy URL fallback: Direct → Jina AI Reader → Google Cache
- [x] Handles JS-rendered pages, partial paywall bypass

**Growth Pipelines**
- [x] PostQueue — optimal-slot scheduler (KST: 9:00/10:30/12:00/13:30/15:00/19:00/21:00)
- [x] CommentHunter — trend detection + reply draft generation
- [x] ReplyMonitor — mention polling + re-reply drafts
- [x] WeeklyReporter — 7-day metrics + AI analysis + content-mix section + perf summary (Monday 9am KST)
- [x] TopicMemory — 30-day tag frequency tracking, overuse detection
- [x] ContentPack — multi-draft suite (3 mains + short + replies + quote + thread)

**Operator Tools**
- [x] `/note <draft_id> <메모>` — save manual note to Draft.manual_notes (최대 500자)
- [x] `/hint <draft_id> <메모>` — save long-term hint with `[HINT]` prefix (DraftWriter에 우선 반영)
- [x] `/hint clear <draft_id>` — remove `[HINT]` lines only; plain notes and `[PERF]` preserved
- [x] `/hints` — list active `[HINT]` lines across recent approved/published drafts (audit view)
- [x] `/perf <draft_id> <메모>` — save post-publish performance note (`[PERF]` prefix)
- [x] `/perf` — list recent published drafts with performance notes
- [x] ContentRequest.note validator (500자 max, field_validator)
- [x] `/start` help text includes all active commands

**Operator Feedback & Hint System (Layer 2)**
- [x] `get_recent_operator_hints()` — reads `[HINT]` lines first, falls back to plain notes; injected into DraftWriter as `[OPERATOR HINTS]` block (Layer 2, try/except)
- [x] `format_perf_summary()` — aggregates `[PERF]` notes by category / topic_tags / output_format; surfaces 3 recent note texts; appended to `/report` and weekly report
- [x] Pattern analysis (v2) — cross-references `[PERF]` tags vs all published tags → "늘릴 후보 / 줄일 후보" lines in perf summary
- [x] Hint lifecycle complete: write (`/hint`) → read (`/hints`) → delete (`/hint clear`)
- [x] `format_hint_impact_summary()` — [HINT]×[PERF] co-occurrence: 3-bucket summary (both / perf-only / hint-only); appended to `/report` and weekly report (Layer 2)

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

- No publish without human approval
- politics / policy / economy / society always require approval
- Auto-post feature flag OFF by default (`ENABLE_AUTO_POST_LOW_RISK=false`)
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
| v8 | Low-risk auto-posting (feature flag, explicit opt-in) | Planned |

### Next Candidates

**v8 — Low-risk auto-posting (feature flag)**
- `ENABLE_AUTO_POST_LOW_RISK=false` already in config
- Needs: time-window check + approval bypass guard scoped to low-risk category only
- Requires explicit operator opt-in; not building without instruction

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
