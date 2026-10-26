---
type: inbox
status: resolved
created: 2026-09-20
---
# A Deny beside an Approve does not stop the batch — the approved write runs

**Problem:** when one pause carries two questions and the person answers
`{"k1": "Approve", "k2": "Deny"}`, `k1`'s tool **executes** and only then does the Deny halt the
run. A person who denies one change in a group has not stopped the group.

## Evidence
Measured, not argued: `flow/tests/test_spike_two_questions_one_pause.py` at `83f5620` on
`loop/o1-agent-handoff-spike` (run 3, 19 Sep 2026), tests
`test_approve_plus_deny_executes_the_approved_one_and_then_halts_the_run` and
`test_deny_plus_approve_is_the_same_regardless_of_order`.
Mechanism: `Agent.resume` (`flow/lib/agent.py:164-166`) calls `_prepare_resume` — which resolves
**every** pending call, running each approved tool — and consults `_has_denial` only afterwards.

## Open questions
- Approve + free text: does the free text also stop the batch, or only a Deny?
