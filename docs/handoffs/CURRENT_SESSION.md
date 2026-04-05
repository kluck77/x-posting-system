# Current Session

## Session Info

- Date: 2026-04-05
- Branch: claude/extract-prediction-time-n82UK
- Phase: v10 — internal quality hardening

---

## What This Session Did

Phase 10 internal hardening pass: rate-limiter externalization, OpenAI prompt refresh,
Reviewer quality_flags. No operator-facing features, no locked areas touched.

---

## TASK-01 — Rate Limiter Settings Externalization

**Problem found:** `rate_limiter.py` had three module-level `DEFAULT_MAX_*` constants
(50/50/30) that were never used. `__init__` derived limits from `settings.daily_post_target * 2`
(=60/60) instead, contradicting the file's own docstring ("하루 5회").

**Changes:**
- `app/config.py`: Added `max_drafts_per_day=5`, `max_telegram_per_day=5`, `max_posts_per_day=10`
  under new `# --- 일일 사용량 제한 ---` section
- `app/services/rate_limiter.py`: Removed dead `DEFAULT_MAX_*` constants. Updated `__init__`
  to use `max_drafts if max_drafts is not None else settings.max_drafts_per_day` (explicit
  `is not None` check preserves explicit-zero override safety)
- `.env.example`: Added `RATE LIMITS` section with `MAX_DRAFTS_PER_DAY`, `MAX_TELEGRAM_PER_DAY`,
  `MAX_POSTS_PER_DAY` (all commented-out defaults)
- `tests/test_config.py`: Added `test_rate_limit_defaults` and `test_rate_limit_env_override`

**Backward compat:** All existing tests pass explicit override args (`max_drafts=5`, etc.)
— behavior unchanged.

---

## TASK-02 — OpenAI DraftWriter Prompt Refresh

**Changes to `app/providers/openai_provider.py` SYSTEM_PROMPT:**
- Added `AUDIENCE` paragraph: non-Korean, globally-minded English readers; assume zero background
- Added `EDITORIAL STANDARD`: credibility over virality explicit statement
- BLOCK 2: added "If no specific fact or number available, do not write the post"
- BLOCK 4: added "for the international reader" to be explicit about audience
- STRICT RULES additions:
  - Expanded banned phrase list (added: in conclusion, it goes without saying, it is important to note,
    as we all know, needless to say, at the end of the day, touch base, synergy, leverage as verb,
    empower, utilize)
  - `NEVER sensationalize or use outrage framing — credibility beats virality`
  - `NEVER editorialize on domestic political parties, politicians, or election results`
  - `ALWAYS write in plain English — short sentences, common words, no jargon`

**JSON output schema: unchanged.** Same 8 keys. No compatibility break.

---

## TASK-03 — Reviewer quality_flags Enhancement

**`app/providers/base.py`:**
- Added `quality_flags: dict = field(default_factory=dict)` to `ReviewResult`
  (backward-compatible; missing = {})

**`app/providers/anthropic_provider.py` REVIEW_SYSTEM_PROMPT:**
- Added `QUALITY FLAGS CHECKLIST` section before JSON response block with 5 flags:
  `hook_strong`, `specific_fact_present`, `international_context_clear`,
  `sounds_human`, `tone_clean`
- Added `quality_flags` object to JSON output schema

**`AnthropicReviewer.review_and_refine`:**
- Added `quality_flags=data.get("quality_flags", {})` to `ReviewResult` constructor

**`tests/test_providers.py`:** Added `TestReviewResultQualityFlags` (3 tests):
- `quality_flags` defaults to `{}`
- `quality_flags` can be explicitly set
- `MockReviewer` returns `isinstance(quality_flags, dict)` (backward compat)

---

## TASK-04 — topic_memory / voice_guard Audit

Both files inspected. Both are solid, complete Layer 2 implementations:
- `topic_memory.py`: pure SQLite read, Counter-based, full try/except, no AI calls
- `voice_guard.py`: pure regex, 20 patterns, try/except, compiled cache

No changes made. No compatibility issues with TASK-02/03.

---

## Files Changed

| File | Change |
|------|--------|
| app/config.py | Added max_drafts_per_day, max_telegram_per_day, max_posts_per_day fields |
| app/services/rate_limiter.py | Removed dead DEFAULT_MAX_* constants; __init__ now reads from settings |
| .env.example | Added RATE LIMITS section |
| app/providers/openai_provider.py | SYSTEM_PROMPT: AUDIENCE + EDITORIAL STANDARD + expanded bans |
| app/providers/base.py | ReviewResult: added quality_flags field (default={}) |
| app/providers/anthropic_provider.py | REVIEW_SYSTEM_PROMPT: quality_flags checklist + JSON; parse in reviewer |
| tests/test_config.py | +2 tests for new rate limit settings fields |
| tests/test_providers.py | +3 tests (TestReviewResultQualityFlags) |

---

## Tests

- Before: 476 passed
- After: 481 passed (+5)
- 0 failures

---

## Risks Checked

- Rate limiter: all existing tests pass explicit overrides → not affected by default change
- OpenAI prompt: JSON output schema unchanged → no parsing breaks
- ReviewResult quality_flags: `default_factory=dict` → old callers (MockReviewer) unchanged
- REVIEW_SYSTEM_PROMPT JSON: quality_flags parsed via `data.get("quality_flags", {})` → old
  API responses without the field gracefully degrade to {}
- No orchestrator, queue, monitor, or publisher files touched
- No DB schema changes

---

## Recommended Next Candidates

Nothing urgent. System is stable and well-tested (481 tests).
