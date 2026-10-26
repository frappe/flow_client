---
description: Retro — convert mistakes into permanent harness improvements
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---
# Retro Loop

This week: !`git log --oneline --since="7 days ago" | head -30`
Daily notes: !`ls brain/80-daily/ | tail -7`

1. Read the week's daily notes, verify tables, and any failed or re-planned loop.
2. Answer: where did it go wrong and what was the ROOT cause? What had to be explained twice?
   Which guardrail was missing? Which loop was friction?
3. Write `brain/90-retro/<date>.md`.

A retro that produces no artifact is wasted. Propose at least one concrete change — a `## Lessons`
line in CLAUDE.md, a tightened loop command, or a new guard. Harness files (hooks, settings, the test
gate) are protected: write the proposed change as a diff in the retro note for a human to apply.
