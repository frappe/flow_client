---
type: changelog
---
# Changelog
- 2026-09-19 — Fork created at upstream 4a3189b; `.gitattributes` pins LF; harness installed. [[20-adr/ADR-001-fork-flow]]
- 2026-09-19 — F3: the model is told the date, time, zone and who it is speaking with, every turn; and a run now persists only the messages it produced. [[10-specs/f3-turn-context]]
- 2026-09-19 — E2: a linked agent's instructions are rebuilt every turn, so editing an agent reaches conversations already open. [[10-specs/e2-instructions-per-turn]]
- 2026-09-19 — E5: approval questions can be written in plain language on the tool record, and name the tool the way a person would. [[10-specs/e5-confirm-prompt-field]]
- 2026-09-19 — E5 v2: the approval question is substituted, not evaluated, and the exact arguments are always shown beneath it. Replaces the template engine v1 put in the approval path. [[10-specs/e5-confirm-prompt-field-v2]]
- 2026-09-20 — S14: a denial in a group of approvals executes nothing; refusing one of several actions shown together now refuses all of them. [[10-specs/s14-deny-stops-batch]]
- 2026-09-20 — S15: a resume that cannot honour an approval says so instead of echoing it, and never executes on an answer to a question nobody was asked. [[10-specs/s15-resume-fails-closed]]
- 2026-09-20 — Evals: every proven defect has a scenario, and the runner tells an unfixed defect apart from a regression — a known defect that starts passing turns the gate red, because the record has gone stale.
- 2026-09-20 — S16a: a kept note is approved before it is kept, a conversation may keep notes only for the person in it, and notes are handed to the model as quoted data rather than in the instruction voice. [[10-specs/s16a-memory-is-data]]
- 2026-09-20 — S16b: the approval on a shipped tool that changes data cannot be unchecked on its record, and a hand-written tool is gated until its author says otherwise. [[10-specs/s16b-gates-cannot-be-unset]]
- 2026-09-20 — S16c: a run with nobody to answer cannot keep a note because of what its tool is, not because of a flag read at the moment it runs; a failed run stops asking; and a kept note is counted against the room a turn has for file text. [[10-specs/s16c-memory-by-construction]]
