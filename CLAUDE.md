# Project Rules for Claude Code

This file contains permanent directives for all AI-assisted work on this project.
Read this before proposing any changes, features, or roadmap items.

---

## What This System Is

A **semi-manual, approval-first content operating system** for a Korea-focused English account.

The system generates draft content and prepares it for the operator to review and post.
The operator makes every posting decision. The system never posts without an explicit tap.

Core workflow:
```
source input → AI draft suite → Telegram approval card → [operator taps Approve] → X post → logs
```

All posting requires human approval. No exceptions. This is not a scheduled auto-poster.

---

## Permanent Scope

### Supported output types
- main posts (up to 3 drafts)
- short versions
- reply drafts
- quote-post drafts
- thread options
- risk warnings
- topic tags
- "why it matters" framing
- style / voice / repetition warnings

### Supported input types
- news link (URL)
- X post link
- screenshot reference (manual text extraction only — no OCR automation)
- short manual note
- daily-life observation
- account example

---

## Permanent Exclusions

The following are **out of scope permanently**. Do NOT build, suggest, scaffold,
or leave placeholders for any of these. Do not include them in roadmap suggestions
unless this section is explicitly updated.

### Image / Visual generation
- DALL-E integration
- Stable Diffusion integration
- automatic image generation of any kind
- image prompt generation
- thumbnail generation
- image attachment automation
- any "visual generation" module
- video generation
- multimedia rendering pipeline

### Automation safety boundaries
- auto-posting without approval
- auto-like / auto-follow / auto-DM / auto-reply
- spam automation
- fake engagement features
- engagement pod logic
- viral pattern targeting

### Infrastructure complexity (this phase)
- multi-user support
- Redis / task queue
- cloud deployment config
- Postgres migration
- web dashboard / analytics UI
- ML fine-tuning pipeline
- embedding store / RAG system
- new AI providers (beyond current 5)

---

## Architecture Rules

### Layer 1 — Operating Core (must never break)
```
ContentRequest → ContentPack → Telegram approval card → [operator tap] → X post → DB log
```
"X post" here means: XPublisher called only after `ApprovalStatus.APPROVED` is set by an
explicit operator action. There is no auto-posting path in Layer 1.
Layer 1 must work without Layer 2. Test this explicitly.

### Layer 2 — Growth Support (advisory only, never blocking)
- criteria_signals → prompt context injection
- topic memory / content-mix tracking
- voice consistency hints
- weekly guidance
- quality scoring (advisory, not auto-reject)

Layer 2 rule: every Layer 2 call is wrapped in `try/except`. Failures degrade
silently. Layer 1 continues unaffected.

### Hard constraints
- Do NOT change orchestrator Steps 1–7 structure without explicit instruction
- Do NOT add new DB tables without explicit instruction (use existing columns)
- Do NOT modify the Telegram approval flow without explicit instruction
- Do NOT modify the X publisher without explicit instruction
- Do NOT modify PostQueue to auto-publish without approval
- Do NOT add any approval bypass, regardless of risk level or category

### Locked Areas (complete — do not reopen)
- orchestrator Steps 1–7
- Layer 1 core flow (ContentRequest → XPublisher)
- Telegram approval callbacks (approve/reject/defer/regenerate)
- PostQueue approval gate (try_publish_next → notification only)
- hint / perf / operator workflow (/hint, /hints, /hint clear, /perf, /note, /report)
- 5-criteria quality framework (all providers, Reviewer gate, regenerate loop)
- Provider integrations (Grok, Perplexity, Gemini, OpenAI, Anthropic)

---

## Roadmap (confirmed directions)

### Done
- v1–v4: core pipeline, quality framework, growth pipelines
- criteria_signals → DraftWriter + Reviewer prompt injection
- v5: topic memory, voice guard, RepetitionGuard wiring, content-mix weekly report
- v6: quality gate (advisory), prompt quality audit, manual note capture (/note)
- v6: prompt banned list sync, DraftWriter 5-criteria compact gate, VoiceGuard wiring
- v7: content performance feedback loop (/perf), pattern analysis, hint lifecycle (/hint · /hints · /hint clear)
- v7: operator hint → DraftWriter injection ([OPERATOR HINTS] block, Layer 2)
- v7: [HINT]×[PERF] co-occurrence summary (format_hint_impact_summary)
- v7: operational stability patch (session close, log commit guard, reply error handling)
- v7: operator command reliability bundle (_parse_draft_id helper, /hint clear UX, /report session guard)

### Active
- None. v7 complete. Awaiting operator instruction for v8.

### Future (requires explicit operator opt-in before building)
- **Auto-posting of any kind** — permanently deferred; the current direction is manual-posting-first.
  `ENABLE_AUTO_POST_LOW_RISK` flag exists in config but logic will NOT be built without an explicit
  operator directive to reverse the manual-posting-first decision.
- Content performance feedback loop — already done in v7; no further action
- Operator note → prompt improvement pipeline — already done in v7; no further action

### Next Candidates (v8)
See PROJECT_STATUS.md "Next Candidates" for full descriptions.

- **A — `/queue remove <n>`**: operator queue management command. Recommended next.
- **B — Idle pipeline reminder**: daily Telegram ping when pipeline has been silent 48h. Defer.
- **C — `/monitor off/on`**: reply monitor pause toggle. Defer.

---

## What Good Work Looks Like

- Minimal changes with maximum safety
- Backward-compatible parameters (`default=""`, `default=None`)
- Layer 2 always wrapped in `try/except`
- Every new feature has at least one test
- `pytest tests/ -q --tb=short` must pass before any commit
- No scope creep, no "nice to have" extras
- No new abstractions for one-time operations
