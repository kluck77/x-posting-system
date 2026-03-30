# Project Status

## Current Phase: v1.0 MVP Complete

### What Works Now
- [x] Source intake (manual input)
- [x] AI draft generation (Mock + OpenAI + Claude)
- [x] Category classification (6 categories)
- [x] Risk scoring (low/medium/high)
- [x] Telegram approval cards (Approve/Reject/Defer/Regenerate)
- [x] X publishing (Mock + real API)
- [x] Duplicate prevention (URL + text)
- [x] Daily rate limits (5 drafts, 5 telegrams, 3 posts)
- [x] Full audit trail in SQLite
- [x] 76 automated tests passing
- [x] FastAPI admin API with Swagger docs

### Safety Rules (Enforced in Code)
- No publish without human approval
- politics/policy/economy/society always require approval
- Auto-post feature flag OFF by default
- Duplicate text detection
- Daily usage limits
- No auto-like/follow/DM/reply

### API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | /health | System health check |
| GET | /status | AI provider status |
| POST | /ingest | Submit source + run pipeline |
| GET | /drafts/pending | List pending drafts |
| GET | /drafts/approved | List approved drafts |
| GET | /drafts/failed | List failed drafts |
| GET | /drafts/{id} | Draft detail |
| POST | /drafts/{id}/approve | Approve + publish |
| POST | /drafts/{id}/reject | Reject draft |
| POST | /drafts/{id}/retry | Retry failed post |
| GET | /usage | Daily usage summary |

### Not Yet Implemented (Future)
- [ ] Gemini research integration
- [ ] Grok trend detection
- [ ] Perplexity fact-checking
- [ ] RSS/API auto-collection
- [ ] Low-risk auto-posting
- [ ] Scheduled posting
- [ ] Analytics
