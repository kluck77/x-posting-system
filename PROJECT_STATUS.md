# Project Status

## Current Phase: v4 — Quality Framework Complete

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
- [x] Reviewer-triggered regenerate loop (max 1 retry)
- [x] Interpretation gap injection: Gemini gaps → DraftWriter context
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
- [x] WeeklyReporter — 7-day metrics + AI analysis (Monday 9am KST)

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
| v5 | RSS auto-collection & news monitor | In progress |
| v6 | Low-risk auto-posting (feature flag) | Planned |
| v7 | Analytics dashboard | Planned |
