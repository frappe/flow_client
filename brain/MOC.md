---
type: moc
---
# VEYQON Flow — Map of Content

The hub. If a note isn't linked from here, it's lost.

## Start here
- [[30-loops/dev-loops|The 7 development loops]] — how work gets done
- [[40-architecture/engine-overview|Engine overview]] — how a turn flows through the engine
- [[40-architecture/the-invisible-character-rule|The invisible-character rule]] — the one writing of a rule that exists in five copies, and what each copy must match
- [[70-runbooks/local-setup|Local setup]] — the bench, and how to rebuild it
- [[20-adr/ADR-001-fork-flow|ADR-001 Fork Flow]] — why this repo exists and its branch model

## Work in flight
- **Specs** → `10-specs/`
  - [[10-specs/f3-turn-context|F3 — per-turn context]] (implemented 2026-09-19, awaiting review)
  - [[10-specs/e2-instructions-per-turn|E2 — instructions per turn]] (implemented 2026-09-19, awaiting review)
  - [[10-specs/e5-confirm-prompt-field-v2|E5 v2 — an approval question a caller cannot steer]] (implemented 2026-09-19, awaiting review)
  - [[10-specs/e5-confirm-prompt-field|E5 v1]] (superseded by v2 — a template engine in the approval path)
  - [[10-specs/s14-deny-stops-batch|S14 — a Deny in a batch executes nothing]] (implemented 2026-09-20, awaiting review)
  - [[10-specs/s15-resume-fails-closed|S15 — an approval must never be silently swallowed]] (implemented 2026-09-20, awaiting review)
  - [[10-specs/s16a-memory-is-data|S16a — memory is data, and agent-wide memory is not writable from a conversation]] (implemented 2026-09-20, awaiting review)
  - [[10-specs/s16b-gates-cannot-be-unset|S16b — an approval switch cannot be turned off by accident]] (implemented 2026-09-20, awaiting review)
  - [[10-specs/s16c-memory-by-construction|S16c — an unattended run keeps no notes by construction, and a kept note is budgeted]] (implemented 2026-09-20, awaiting review)
  - [[10-specs/s18-knowledge-read-filter|S18 — knowledge search returns only what the asking user may read]] (implemented 2026-09-21, reviewed and followed up 2026-09-21 — one open item: the chunk doctype is still readable around the filter)
  - [[10-specs/s17-one-approval-one-action|S17 — one approval answers one action]] (implemented 2026-09-21, reviewed — **R7 needs an owner decision before merge**)
- **Inbox** → `00-inbox/`
  - [[00-inbox/instructions-frozen-at-first-turn]] (resolved by E2)
  - [[00-inbox/worded-refusal-reproposes]]
  - [[00-inbox/stream-disconnect-loses-output]]
  - [[00-inbox/trigger-runs-name-scheduler-as-the-person]]
  - [[00-inbox/prompt-prefix-is-inferred-not-declared]]
  - [[00-inbox/a-users-own-name-can-contain-a-vendor-word]]
  - [[00-inbox/approval-question-never-reaches-the-approver]]
  - [[00-inbox/a-model-can-drop-the-approval-sentence]]
  - [[00-inbox/a-deny-does-not-stop-the-batch]] (resolved by S14)
  - [[00-inbox/an-approval-is-swallowed-when-the-tool-is-gone]] (resolved by S15)
  - [[00-inbox/an-id-reused-in-a-later-turn-is-not-caught]] (S17's R3, captured not absorbed)
  - [[00-inbox/known-defects-ranking]] — the three unclaimed known defects, ranked, with a recommendation for S17

## Decisions
- **ADRs** → `20-adr/` — immutable. Supersede, never edit.

## Evidence
- `evals/` — scenarios run in-process against a scripted model. Every defect this project has
  proven has one. A scenario that describes an **unfixed** defect carries `known_defect:` and is
  reported in its own bucket, so it never makes the suite look green or red by accident.
  See `evals/README.md`.

## Operations
- [[changelog]] · **Daily** → `80-daily/` · **Retros** → `90-retro/`
