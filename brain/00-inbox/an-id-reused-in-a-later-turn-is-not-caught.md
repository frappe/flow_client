---
type: inbox
status: open
created: 2026-09-21
---
# A tool-call reference reused in a LATER assistant turn is not caught

**Problem:** S17 refuses a turn whose own calls cannot be told apart. The rule is applied **per
assistant turn**. Nothing checks a reference reused across two *different* assistant messages in the
same transcript, and the bookkeeping that decides what is still pending is **transcript-wide**.

Captured here rather than widened into S17, which is the owner's decision recorded as that spec's
non-goal and its risk R3.

## Evidence
`flow/lib/agent.py:452` builds `has_result` over the **whole** transcript, so once a reference has
any tool result, every call carrying it reads as answered — including one in a later turn that was
never run. `_indistinguishable_tool_call`'s `seen` set is local to one call, and S17's
`_validate_messages` check sits **inside** the per-message loop, so two assistant messages each
carrying `"c1"` pass unchanged.

The build review traced the downstream behaviour at `veyqon` and at the S17 branch and found it
**identical**: reaching a double execution needs two *pending* calls sharing a reference across two
turns, and the loop's "append a tool message for every non-Question call" invariant prevents that.
The reachable outcome is `_prepare_resume`'s *"No questions awaiting an answer"* raise, not an
execution. So this is **pre-existing, unchanged by S17, and not currently known to be exploitable** —
which is why it is an inbox note and not a spec.

## Why it is still worth writing down
The invariant that protects it is incidental, not stated: nothing asserts that a reference is never
reused across turns, and nothing would notice if a future change to the loop stopped appending a
tool message for every executed call. The fix, if it is ever wanted, is a transcript-wide uniqueness
rule — which would put a new constraint on every historical transcript the engine loads, and that is
exactly why S17 did not take it on.

## Not this
- Two calls in ONE turn sharing a reference, or carrying none — closed by
  [[10-specs/s17-one-approval-one-action|S17]].
- A single call with no reference — S17's explicit non-goal, and still unrefused.
