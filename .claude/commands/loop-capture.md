---
description: Capture an idea, bug or request into the brain inbox. Frictionless — never solve.
argument-hint: <free text description>
allowed-tools: Write, Bash
---
# Capture Loop

Capture this into the brain inbox: **$ARGUMENTS**

1. Derive a kebab-case slug.
2. Write `brain/00-inbox/<slug>.md` from `brain/_templates/inbox.md`: `type: inbox`, `status: raw`,
   `created: <today>`, a one-line problem statement (the pain, not the solution), any context given,
   and `## Open questions`.
3. Link it from `brain/MOC.md` under `## Inbox`.

This loop is capture ONLY: no solution, no estimate, no code, nothing outside `brain/00-inbox/` and
`brain/MOC.md`. Confirm the slug and path in one line, then stop.
