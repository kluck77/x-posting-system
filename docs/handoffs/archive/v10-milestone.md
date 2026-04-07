# v10 Milestone Archive

**Date:** 2026-04-05
**Branch:** claude/extract-prediction-time-n82UK
**Tests at freeze:** 481 passed, 0 failures

---

## What v10 Completed

### v9 (operator features, prior phase)
- **Reply monitor inline approval button** — `run_reply_monitor()` now sends Telegram messages
  with inline keyboard buttons (`reply_use` / `reply_skip`). `_pending_reply_drafts` dict holds
  drafts in memory for callback lookup. `_handle_reply_callback()` added to `telegram_bot.py`.
- **`/queue view <n>`** — read-only queue item detail. `PostQueue.get_pending_at(position)` uses
  same `list_pending()[n-1]` mapping as `remove_pending()`. Shows full text, added_at KST,
  notification status, char count with X-limit warning.

### v10 (internal hardening)
- **Rate limiter settings externalization** — `Settings` now has `max_drafts_per_day=5`,
  `max_telegram_per_day=5`, `max_posts_per_day=10`. `RateLimiter.__init__` reads from settings
  when no explicit override is passed (`is not None` check). Dead `DEFAULT_MAX_*` module-level
  constants removed. `.env.example` updated with `RATE LIMITS` section.
- **OpenAI DraftWriter prompt refresh** — `SYSTEM_PROMPT` updated with explicit `AUDIENCE` and
  `EDITORIAL STANDARD` (credibility>virality) blocks. Expanded banned phrase list (+10). Added
  no-sensationalize, no-editorializing, plain-English rules. JSON output schema unchanged.
- **Reviewer quality_flags** — `ReviewResult` dataclass now has `quality_flags: dict` (default `{}`).
  `REVIEW_SYSTEM_PROMPT` has a `QUALITY FLAGS CHECKLIST` section (5 flags: `hook_strong`,
  `specific_fact_present`, `international_context_clear`, `sounds_human`, `tone_clean`).
  `AnthropicReviewer` parses `data.get("quality_flags", {})`. Backward-compatible: old API
  responses without the field degrade gracefully to `{}`.

---

## Locked Areas (complete — do not reopen)

| Area | File(s) |
|------|---------|
| Orchestrator Steps 1–7 | app/orchestrator.py |
| Layer 1 core flow | orchestrator.py, x_publisher.py |
| Telegram approval callbacks | app/telegram_bot.py |
| PostQueue approval gate | app/services/growth/post_queue.py |
| hint / perf / operator workflow | telegram_bot.py, draft_service.py |
| 5-criteria quality framework | app/services/quality_scorer.py, all providers |
| Provider integrations | app/providers/*.py |
| /draft fast-path | telegram_bot.py |
| Posting pack standardization | content_pack, telegram_service.py |
| /queue remove + clear + view | telegram_bot.py, post_queue.py |
| /monitor off/on/status | telegram_bot.py, monitor_state.py |
| Idle pipeline reminder | activity_tracker.py, main.py |
| Reply monitor inline button | reply_monitor.py, telegram_bot.py |
| Rate limiter externalization | config.py, rate_limiter.py, .env.example |
| OpenAI prompt refresh | app/providers/openai_provider.py |
| Reviewer quality_flags | app/providers/base.py, anthropic_provider.py |

---

## Deferred (do not build without explicit operator directive)

- Auto-posting of any kind
- Image / video generation
- Web dashboard / analytics UI
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration

---

## System State at Freeze

- **481 tests, 0 failures**
- All operator tools complete
- Internal hardening pass done
- No urgent next feature required
- `ENABLE_AUTO_POST_LOW_RISK=false` — flag exists, logic intentionally not built
