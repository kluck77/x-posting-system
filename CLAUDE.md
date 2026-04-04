# Project Rules for Claude Code

This file contains permanent directives for all AI-assisted work on this project.
Read this before proposing any changes, features, or roadmap items.

---

## What This System Is

A **semi-manual X content operating system** for a Korea-focused English account.

Core workflow:
```
source input → AI draft suite → Telegram approval → X post → logs
```

All posting requires human approval. No exceptions.

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
ContentRequest → ContentPack → Telegram approval → X post → DB log
```
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

---

## Roadmap (confirmed directions)

### Done
- v1–v4: core pipeline, quality framework, growth pipelines
- criteria_signals → DraftWriter + Reviewer prompt injection

### Active (1-month plan)
- Week 3: topic memory, voice guard, RepetitionGuard wiring, content-mix weekly report
- Week 4: quality gate (advisory), prompt quality audit, manual note capture

### Future (text quality focus only)
- Low-risk auto-posting (feature flag, requires explicit approval)
- Content performance feedback loop (which posts performed → inform future drafts)
- Operator note → prompt improvement pipeline

---

## What Good Work Looks Like

- Minimal changes with maximum safety
- Backward-compatible parameters (`default=""`, `default=None`)
- Layer 2 always wrapped in `try/except`
- Every new feature has at least one test
- `pytest tests/ -q --tb=short` must pass before any commit
- No scope creep, no "nice to have" extras
- No new abstractions for one-time operations
