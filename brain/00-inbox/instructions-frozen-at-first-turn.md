---
type: inbox
status: resolved
created: 2026-09-19
---
# Agent instruction edits don't reach existing sessions

**Problem:** `_persist_turn` (`flow_session.py:209`) stores the agent's instructions as the session's
system message on the first turn. Editing an agent's instructions afterwards changes only new sessions.

## Evidence
Read in upstream 4a3189b, 19 Sep 2026. Directly affects rolling out the revised Agent Q prompt.

## Open questions
- Should the system message be rebuilt from the agent record each turn (ephemeral), like memory?
- What should happen to a long-running session when instructions change mid-conversation?

## Resolved
2026-09-19 by [[10-specs/e2-instructions-per-turn]] — a linked agent's instructions are
rebuilt ephemerally every turn; stored messages are not rewritten. The second open question
("what should happen to a long-running session when instructions change mid-conversation") was
answered by doing the simple thing: the new text applies from the next turn, and the spec records
the auditability cost of that under Risks.
