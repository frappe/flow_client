---
description: Turn an inbox item into a rigorous, testable spec (spawns spec-writer)
argument-hint: <inbox-slug>
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---
# Spec Loop: $ARGUMENTS

Source: @brain/00-inbox/$ARGUMENTS.md

1. Read `brain/MOC.md`, related `brain/10-specs/`, and `brain/20-adr/`. For code questions, read the
   code: find every call site with grep, and show a positive control for any "no other callers" claim.
2. Spawn `spec-writer` to draft. It asks clarifying questions before writing.
3. Write `brain/10-specs/$ARGUMENTS.md` from `brain/_templates/spec.md`. Acceptance criteria must be
   testable assertions — they become the tests and the `features.json` entries.
4. If the change touches the write-confirmation path, what the model is sent, a whitelisted API, a
   doctype schema, or anything that must be offered upstream, say so and draft an ADR.
5. Write the acceptance criteria into `features.json` (all `passes: false`, `spec` set to the slug).

Then present the spec and **STOP**. Only a human sets `status: approved`.
