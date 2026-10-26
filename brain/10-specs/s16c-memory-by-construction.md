---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 7 2026-09-20 — REVIEW BEFORE MERGE
created: 2026-09-20
implemented: 2026-09-20
upstreamable: yes
---
# Spec: S16c — an unattended run keeps no notes by construction, and a kept note is budgeted

## Problem
S16a decided that a run with nobody to answer an approval keeps no notes. The way that decision is
enforced is the problem.

Re-verified in this repository at `merge/flow-run6-2026-09-20` before a line was written:

1. **The refusal is a worker-global flag read at call time.** `bind_update_memory(agent,
   unattended=True)` builds the tool **without its gate** — deliberately, because a question in a
   run with nobody to answer parks the run in `Paused` forever (S16a D4). The resulting tool is
   ungated, and the only thing that stops it writing is
   `if from_conversation and frappe.flags.get("flow_unattended")` in `save_memory`
   (`flow/memory/memory.py`). So the safety of an **ungated write tool** depends on a flag on
   `frappe.flags` being correct at the moment the tool body runs.
2. **The flag and the tool are set by different statements.** `FlowSession.chat` calls
   `self._rebind_memory_tool(unattended)` and then `_set_active_run(run.name, unattended=unattended)`
   (`flow/flow/doctype/flow_session/flow_session.py`). Two statements, one derived value, and the
   dangerous half is the one that survives if the other is wrong: an ungated tool with the flag
   clear writes.
3. **`frappe.flags` is per-request worker state, and the engine already had to fix one leak of it.**
   `stream_with_persistence`'s `finally` clears both flags, with a comment saying why: leaving
   `flow_unattended` set would carry a trigger's "nobody is here" into the next request this worker
   serves. The same reasoning applies in the other direction and is not defended anywhere: a flag
   that fails to be set leaves an ungated memory tool writing in a run nobody is watching.

Separately, and named by S16a as its own Open question 2:

4. **A kept note is not counted in the file-injection budget.** `_file_injection_budget` sums the
   stored messages plus the instructions delta; the memory block is appended to the last user
   message *after* the budget has already been spent on files. A large set of notes and a large
   file are each individually inside the window and can cross it together.

## Goal
1. An unattended memory tool refuses because of **what it is**, not because of what a flag says.
2. The flags that carry "which run" and "is anybody there" do not outlive the run that set them, on
   the non-streaming path, whether the run returns or raises.
3. A kept note costs what it costs: it is counted against the same budget file text is.

## Non-goals
- Removing the flag check in `save_memory`. It stays. It is the only defence on any path that did
  not go through the rebinding, and two independent refusals are the point, not a redundancy to
  tidy away.
- Changing when a run counts as unattended. `source == "Trigger"` or `auto_approve`, unchanged.
- Gating the memory tool in an unattended run. S16a D4 settled that, for the reason it gives.
- Anything else in the budget. The turn-context block and the instructions delta are unchanged.

## Design

### D1 — the unattended tool's body refuses before it can read anything
`bind_update_memory`'s closure already knows, at bind time, whether this tool belongs to a run with
nobody to answer. So the refusal moves into the body's first statement, keyed on the **closure
variable**:

    if unattended:
        return dict(MEMORY_NOT_EXECUTED["unattended"])

It reads no flag, touches no database, and cannot be made to write by anything that happens between
binding and calling. The two objects `bind_update_memory` returns are now different in kind: one can
write and asks first, one cannot write at all. A caller holding the second one cannot get a write
out of it whatever the worker's state.

Why this and not "set the flag more carefully": a flag is a claim about the world that some other
code has to keep true. A closure variable is a property of the object in your hand. The write path
should not be reachable from an object that was built for a run that may not write.

### D2 — the same refusal, unchanged, in `save_memory`
Kept exactly as it is, for the caller D1 cannot see: **a session with no agent record is never
rebound** (`_rebind_memory_tool` returns early on `not self.agent`) while `chat` still marks the run
as having nobody in it, so the tool in hand is the writing one and the flag is the only thing left.
Any future caller that binds the tool the attended way inside an unattended run is covered the same
way. Two refusals, one for the object and one for the path.

**Neither refusal fires on a resume**, and the first version of this section said the flag covered it,
which is false: `resume` records its run with `unattended=False`, so the flag is clear throughout. It
is deliberate, not a gap — somebody has just answered a question in that run — and S16a R6 already
says so. Recording it wrongly here would have been worse than not recording it, because it is the
justification for keeping a defence: a maintainer who checks the resume path and finds the claim
false has reason to think the whole flag check is decorative. Found by review. See Open question 2.

### D3 — the flags do not outlive the run, on the non-streaming path either
`FlowSession.chat`'s non-streaming branch clears both in a `finally` via `_set_active_run(None)`,
which sets `flow_run = None` and, because `bool(None)` is false, `flow_unattended = False`. That is
already true and **nothing asserted it**. It is pinned here for a run that returns, one that raises,
and one that pauses, because the streaming path's equivalent was written only after the leak was
found once.

The pins assert the flags were **set** first, read from inside the model call, and then assert the
exact value `False` rather than mere falsiness. Both halves came from review: without the first, a
change that stopped setting the flags at all would leave every pin green, and that is the mutation
that matters most, because the flag is what still carries the rule on the one path D1 cannot reach.

### D4 — a kept note is counted in the file-injection budget
`_file_injection_budget` gains one keyword argument, `memory_chars`, added to the `dialogue` sum it
already computes. `_build_prompt_messages` builds the memory block **before** it spends the budget
and passes its length in, then uses the block it already has where it used to build one.

Building the block earlier changes nothing about the block: its inputs are the agent and the latest
stored user message, neither of which file injection touches.

For a turn with no notes the block is empty, `memory_chars` is 0, and the budget is the number it
was — asserted by a test that computes the budget with and without the argument on the same session.

### D5 — a run that failed does not keep asking
Added during the work, from a test written to find out what happens when the iteration budget runs
out with a memory approval pending.

The answer to the question as asked is that it cannot happen: a turn that raises a question RETURNS
from the loop, so the budget is never spent to nothing with something pending, and a resume resolves
every pending call before the loop starts again. An adversarial review traced both loops, both resume
paths and every write of the status and the questions, and could not break the claim.

Both halves are pinned, and the second only after review pointed out that the first version of this
sentence claimed a pin it did not have: the resume half is now asserted by the note existing after the
answer — a pending call that was never resolved could not have written it — and by the iteration count
being 2 on a run whose per-turn allowance is 1, which is the budget claim in one number.

What the test found instead is a real defect. A run pauses and stores its question; the loop later
runs out of iterations and the run goes **Failed** — and `mark_failed` did not clear `questions`,
while `apply_result` beside it always has. Only a Paused run can be resumed, so the question was one
**nobody could ever answer**, still shown as pending. `mark_failed` now clears it, which is the same
rule `apply_result` already applies, on the three paths that never reach it: a run that raised, a
stream cut short, and a person stopping a paused run deliberately. That last one is the clearest case
for it — a run somebody terminated must not go on asking — and it is the one a review found had no
test anywhere in the repository, so it has one now.

Where the question is actually shown, and the reason this is not a cosmetic field:
`flow/flow/doctype/flow_run/flow_run_detail.html` renders a **"Pending Questions"** heading from the
field with **no check on the run's status**, and the field's own description in the doctype already
claimed "Present only when status is Paused". The contract was written down and not enforced.

Nothing else about failure changes, and a Paused run still carries its question, pinned by a control.

## Acceptance criteria
See `s16c-memory-by-construction.features.json`.

## Open questions for the owner
1. **Should the file framing and the per-turn context block be budgeted too?** See R5. Counting them
   is a bigger change with a smaller payoff — the framing is tens of characters, the notes were
   thousands — and doing it silently inside this spec would have made "nothing else in the budget
   changes" untrue.
3. **Should a note set be capped in what it may take from file text, and should the person be told
   when a file arrives empty?** See R1. Today the model is told and the person is not, which is the
   wrong way round — but the fix is a message to a person, which is a product decision and a frontend
   change, and this branch touches no frontend file.
2. **Should a resume be able to tell that its run was unattended?** S16a R6 says a resume is always
   attended. D1 makes the binding the thing that refuses, and a resume never rebinds, so a trigger
   run resumed by its owner can keep notes for the rest of that call. That is a person answering, so
   it is the intended reading — but it is now the ONLY path where the flag is what decides, and the
   spec says so out loud rather than leaving it to be discovered.

## Risks
- **R1 — a big memory set now shrinks what a file may inject, and at the limit it takes all of it.**
  That is the point, and it is a behaviour change: a turn that used to inline a whole file may now
  clamp it. The alternative is the two crossing the window together, which fails the turn.
  At the extreme, found by review and now **pinned by a test rather than capped**, the room reaches
  zero and the file arrives as its framing with an empty body and a truncation marker — **the model
  is told and the person who attached the file is not.** Notes could not reach the file's room at all
  before this change, so that reachability is new. It takes a small context window as well as a large
  note set, because a note is capped at 500 characters and only so many are ever shown.
  **No cap on what a note may cost is built here**: capping it decides which of two things a turn
  should lose, and that is a product decision. **Open question 3.**
- **R2 — `build_memory_block` now runs one step earlier.** It runs exactly once either way, and its
  inputs do not depend on anything between the two positions. If a future change makes the block
  depend on injected content, this ordering becomes wrong; the test that pins the block's content
  unchanged is what would catch it.
- **R3 — the unattended tool is still ungated.** D1 makes it unable to write; it does not make it
  gated. An unattended run still offers the model a tool it may call, and still gets a sentence
  back saying nothing was kept. That is S16a D4's decision and this spec does not reopen it.
- **R4 — nothing here defends `save_memory` against a direct caller with `from_conversation=False`.**
  That is the desk's path and is supposed to write.
- **R5 — the file's own framing and the per-turn context block are still unbudgeted.** The budget is
  decremented by the file *text*, not by the markers around it or the "attached the following" line,
  and the turn-context block added to the system message is not counted at all. Both were true before
  this change and are unchanged by it; D4 makes the notes stop being free, not everything. The test
  asserts the **difference** between a turn with notes and the same turn without, so neither of those
  can hide inside it. **Open question 1.**
- **R6 — clearing a failed run's question loses more than the rendering, and both reviews said so.**
  The transcript still holds the tool call and the run still holds its error, so what was *proposed*
  is not lost. Three things are:
  the rendered question; **the fail-closed record** — `_asked_questions` reads this field, and with it
  empty `_prepare_resume` falls back to the tool's current gate, which makes S15's "the gate changed
  while the question was open" check structurally unable to fire; and **the ability to put the run
  back** — a Paused run must have a question, so a run failed by a *transient* error (a model
  timeout on resume) can no longer be returned to Paused for the person to answer. Nothing in the
  product offers that today, so it is a door closed rather than one broken, and a transient failure is
  now treated exactly like a deliberate stop. Judged the right trade — a question shown as pending
  that nobody can answer is worse — but it is three losses, not one.
- **R7 — the streamed loop's own pause is not pinned by this spec.** The claim about the iteration
  budget was traced through `_loop_stream` by review and holds there, but every new test drives
  `_loop`. Stated rather than implied.
- **R8 — two of `stream_with_persistence`'s lines cannot be reached from any test**, by construction:
  its two `frappe.db.commit()` calls are guarded by `not frappe.flags.in_test`. They are the reason
  the streamed path persists at all, and no suite can cover them. Pre-existing; recorded because the
  streamed pins might otherwise be read as covering that function whole.
