# Writing Workflow

This document describes the end-to-end workflow for producing posts in the x-posting-system.

## 1. Ideation
- Capture raw ideas in a scratch note (title + 1–2 sentence hook).
- Tag each idea with its target audience and intended thread length.
- Promote an idea to a draft only when both the hook and the angle are clear.

## 2. Drafting
- Create the draft in the standard draft location used by the pipeline.
- Write the opening post first; it must stand on its own.
- Keep each post under the platform character limit; do not rely on auto-splitting.
- Mark unresolved facts with `TODO:` so review can catch them.

## 3. Self-Review
- Read the draft out loud once.
- Check: hook strength, claim accuracy, link validity, CTA presence.
- Resolve every `TODO:` before requesting external review.

## 4. Review
- Request review from one reviewer at a time to keep feedback focused.
- Reviewer leaves comments inline; author resolves or replies, never silently overwrites.
- A draft is review-complete only when all threads are resolved.

## 5. Scheduling
- Move the approved draft into the scheduling queue.
- Set the publish time based on the audience timezone, not the author's.
- Confirm there is no collision with another scheduled post in the same 2-hour window.

## 6. Publishing
- The publisher picks up the scheduled item automatically.
- On success, the item is marked `published` with the live URL recorded.
- On failure, the item is moved to `needs_attention` and the error is logged — it is not retried automatically.

## 7. Post-Publish
- Monitor engagement for the first 60 minutes.
- Capture lessons (what worked / what did not) into the ideation backlog so the next cycle benefits.

## States
A post moves through these states in order, never backwards:
`idea → draft → in_review → approved → scheduled → published`
Plus the terminal off-ramp: `needs_attention`.

## Roles
- **Author** — owns ideation, drafting, and addressing review feedback.
- **Reviewer** — owns review comments and final approval.
- **Operator** — owns scheduling, publishing health, and `needs_attention` triage.
