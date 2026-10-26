---
type: spec
status: approved  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner, run 10
amended-by: owner, run 11 — AT17's leak, found by REVIEW-FLOW-10 (M1)
amended-by: owner, run 11 — Part B also covers the OTHER way a run pauses, a question a tool's own
  body returns (REVIEW-FLOW-10 M2). See the amendment at the end of Part B.
notes-on-approval: |
  Two things the v2 draft could not know, settled by the owner for run 10:
  1. The exception IS extended to `flow/tests/test_ai_triggers.py:393-400` (and the rename at
     :381). The "DO-NOT-BUILD" build gate on Part B and Open question 3 are therefore CLOSED.
     The exception the draft hands back unused (`test_ai_agent.py` around :714) stays withdrawn.
  2. S17 HAS landed at `veyqon` since this was written, so "What must not change" item 8 is live
     after all: S17's duplicate-id refusal runs above the classification pass and must be
     asserted unchanged, not dropped as not-applicable.
  Built in run 10 on ONE branch (`loop/s19-unattended-refuses`, cut from S20's head) rather than
  the two the draft proposes: the two-branch argument is a byte-pin conflict between A and B,
  which does not arise when they share a branch and re-baseline `_invoke` once.
created: 2026-09-21
supersedes: /home/thivs/agent-proposals/research-2026-09-21-j/S19-spec.md
revised-by: adversarial review r10, 21 Sep 2026 (/home/thivs/agent-proposals/review-2026-09-21-r10/FINDINGS.md)
upstreamable: Part A yes; Part B no
base: veyqon = 04f4eabe50dadded5739ba0da052b9f369601547
note: read-only review. Nothing below was executed; every file:line was read at `veyqon`.
---
# Spec: S19 (v2) — a batch is one decision, and an unattended run refuses every gate

v1 is corrected in four places, three of them load-bearing. Read **"What changed from v1"** first.

--------------------------------------------------------------------------------------------------
## What changed from v1
--------------------------------------------------------------------------------------------------
1. **The owner's rule replaces the classification.** In ANY unattended run, EVERY tool with
   `requires_confirmation` is refused — it does not run and does not pause. `Tool.write_capable`,
   the resolver forwarding, the builtin flags, the evals `write_capable` key and acceptance tests
   AT10/AT11 are **deleted**. v1's Open question 1 is answered by the rule; v1's R3 and R7 close.
2. **"Unattended" is not `auto_approve`.** `flow/flow/doctype/flow_session/flow_session.py:192`
   already computes `unattended = bool(auto_approve) or source == "Trigger"`, and the Agent never
   learns it. v1 keyed the refusal on `self.auto_approve` alone, so a trigger with the flag **off**
   still paused forever — the exact outcome the rule forbids. D1/D2 fix this.
3. **The upstream edit to `flow/tests/test_ai_agent.py:714` is dropped.** That test is not a batch:
   `_tool_call` (`test_ai_agent.py:56-62`) returns a one-call `ChatResponse` and `FakeModel.chat`
   (`:30-38`) pops one per call, so `:722-727` is two sequential turns. `:731` stays true after
   Part A, and v1's proposed replacement would be **red**. The owner's exception for `:714` is not
   needed and must not be used.
4. **A new blocker.** The rule turns `flow/tests/test_ai_triggers.py:393-400` red, and that file is
   upstream's and byte-identical in the fork. It is not in the exception. **Part B cannot be built
   until the owner extends the exception to it.** See "Exceptions required".

--------------------------------------------------------------------------------------------------
## Problem
--------------------------------------------------------------------------------------------------

### Part A — an ungated call beside a gated one runs before anyone is asked
`flow/lib/agent.py:345-351` (non-streaming) and `:410-420` (streaming) iterate the model's whole
batch calling `_invoke` per call (`:347`, `:415`). A call needing approval comes back as a
`Question` and is `continue`d (`:348-351`, `:416-420`), not `break`ed; the pause is decided only
after the loop (`:362`, `:427`). So every ungated call in a pausing turn has already executed by the
time the person sees the question. If they Deny, nothing undoes it and nothing tells them.

Recorded at `evals/scenarios/ungated_call_beside_a_gated_one.yaml` (`known_defect`, `:3-8`). It is
the only one of the fork's approval defects with **live instances today**: one ordinary chat turn in
which the model batches a read with a gated write.

Upstream's `test_other_tools_run_while_a_question_pauses` (`flow/tests/test_ai_agent.py:411-438`) is
a genuine batch (`ChatResponse` hand-built with two `ToolCall`s at `:422-428`) and asserts the
current behaviour for a **tool-authored** question. Part A must leave it green; see D3 and AT5.

### Part B — an unattended run has nobody to ask, and today it either skips the gate or stalls
`flow/lib/agent.py:485`:

```
485		if tool.requires_confirmation and not self.auto_approve:
486			return _confirmation_question(call, tool)
487		return self._run_tool(call)
```

Two failures, not one:
- **`auto_approve` on** makes every gate inert: the condition short-circuits before
  `_confirmation_question` is built, and every gated write executes with nobody asked. The shipped
  assistant tells the model to set it (`flow/assistant/assistant.py:36-38`), so the first trigger a
  user ever asks for is created with the flag on.
- **`auto_approve` off, in a trigger** raises a question nobody can answer and parks the run in
  `Paused`, holding its session. Upstream pins this at `flow/tests/test_ai_triggers.py:393-400`.

The engine already knows which runs have nobody in them: `flow_session.py:192`,
`unattended = bool(auto_approve) or source == "Trigger"`, used for the memory-tool rebind (`:193`)
and for `frappe.flags.flow_unattended` (`:194`, read at `flow/memory/memory.py:105`). It is simply
never told to the runtime — `flow_session.py:188` hands over `auto_approve` and nothing else.

**Owner input, taken as given:** production has no Flow Triggers on either site, so Part B has zero
live instances and is armed rather than firing.

--------------------------------------------------------------------------------------------------
## Contract
--------------------------------------------------------------------------------------------------
**A.** *Nothing in a turn executes if anything in that turn will ask a person for approval.* A batch
is one decision. When any call in the batch raises an approval question, no call in that batch runs;
the calls nobody was asked about run on resume, in their original order, after the answers are in.

**B (the owner's rule).** *In an unattended run, every tool that requires confirmation is refused.*
It does not run. It does not pause. The call returns a fixed, literal not-executed result and the
run continues, exactly as S16a's memory tool already does. "Unattended" is
`bool(auto_approve) or source == "Trigger"` — the expression the engine already computes.

Contract A extends S14 ("a Deny stops the others") from the resume side to the forward side.
Contract B says `auto_approve` answers the wrong question: it asks *may questions be skipped in this
run*, when the only answerable question is *may this tool run unasked in this run*, and the answer
is no.

--------------------------------------------------------------------------------------------------
## Non-goals
--------------------------------------------------------------------------------------------------
- **A per-trigger allow-list of writes an administrator wants unattended.** With zero triggers in
  production, refusing every unattended gated call breaks nothing that exists. Deferred to a spec
  written when a real trigger needs it and can say what it needs. **Open question 1.**
- **Classifying what a tool does.** The owner's rule makes classification unnecessary: the gate is
  the declaration. v1's `write_capable` field is deleted.
- **Anything inside `execute`'s sandbox.** `execute` is gated, so it is refused unattended; what an
  approved `execute` does in an attended run is unchanged.
- **Changing what `resume_run` accepts or what the web apps send.** Nothing touches `Question.key`
  (`agent.py:74`), `CONFIRM_ANSWER_OPTIONS` (`:42`), or `flow/api/api.py`'s signature.
- **Fixing `assistant.py:36-38`.** After B that sentence is narrower than the behaviour but not
  false. Separate one-file change. **Open question 2.**

--------------------------------------------------------------------------------------------------
## Design
--------------------------------------------------------------------------------------------------

### D1 — the runtime is told a run is unattended (`flow/lib/agent.py:126-141`, `flow/flow/doctype/flow_session/flow_session.py:186-194`)
`Agent.__init__` gains `unattended: bool = False`, stored beside `auto_approve` at
`flow/lib/agent.py:141`. `auto_approve` is kept unchanged so no existing caller breaks.

`FlowSession.chat` sets it where it already computes it:

```python
# flow_session.py, replacing :186-194
unattended = bool(auto_approve) or source == "Trigger"
# A run with nobody in it cannot be asked anything. The runtime decides to ask from the tool's
# flag alone, before any tool body runs, so this is the only place that can tell it.
self._runtime.unattended = unattended
self._runtime.auto_approve = auto_approve
self._rebind_memory_tool(unattended)
_set_active_run(run.name, unattended=unattended)
```

`FlowSession.resume` (`:358-397`) sets neither, and must not: a resume is a person answering. Its
runtime is rebuilt from the record, so both default False. **AT17** pins that.

> **Amended, run 11 (REVIEW-FLOW-10 M1).** "Its runtime is rebuilt from the record" is true of the
> request path and only of the request path. `flow/lib/session.py:78-79` hands back the CALLER'S OWN
> `Agent` when one was passed in, and `FlowSession.chat` mutates `unattended` on that object every
> turn — so an in-process caller (a code agent, `evals/run.py`) that ran one unattended turn and then
> resumed carried `unattended=True` into a run a person was answering. The approval itself still ran
> (`_resolve_confirmation` never consults `_disposition`), but the model's next gated call in that
> same resumed run was refused as having nobody to approve it. The invariant is now stated rather
> than inherited, once, in `Agent.resume`: `self.unattended = False`, because every resume means the
> same thing whatever object it is on. `auto_approve` is deliberately untouched. AT17 is now two
> tests — a unit half on a reused `Agent` and an integration half on a reused `FlowSession` runtime,
> the latter running as a named non-Administrator — and both were watched red before the fix.

### D2 — one predicate, in one place (`flow/lib/agent.py`, new, next to `_invoke` at `:477`)
```python
def _is_unattended(self) -> bool:
    """A run with nobody who can answer a question."""
    return bool(self.unattended or self.auto_approve)

def _disposition(self, call: ToolCall) -> str:
    """What happens to this call before anything runs: "ask", "refuse" or "run"."""
```
- `"refuse"` — `tool.requires_confirmation and self._is_unattended()`
- `"ask"` — `tool.requires_confirmation` (and attended)
- `"run"` — otherwise

Order matters and is asserted: refuse is checked **before** ask, because an unattended run must
never reach `_confirmation_question`. `_invoke` (`:477-487`) is rewritten to consult it, so there is
exactly one copy of the engine's most important condition — the codebase's own warning at
`flow/lib/agent.py:661-664` is why it is extracted rather than duplicated into the two loops.

**This edits `_invoke`, which is byte-pinned.** See D6.

### D3 — classify the batch before executing any of it (`flow/lib/agent.py:345-351`, `:410-420`)
`_loop` and `_loop_stream` each gain a first pass over `response.tool_calls` calling `_disposition`
and collecting the calls whose disposition is `"ask"`. If that list is non-empty:
- build the `Question` for each of those calls (via `_invoke`, which returns one unchanged),
- execute **nothing else** in the batch,
- return `paused=True` with `tool_calls` holding what ran **before this turn** — `executed_calls`
  (`:328-329`, `:379-380`) is carried forward untouched, never cleared. Earlier iterations of the
  same run already completed legitimately and their results stand.

A `"refuse"` disposition is **not** a pause: refused calls get their literal result in the second
pass like any other, and the run continues.

If the `"ask"` list is empty, the second pass runs exactly as today — including a tool that returns
a `Question` of its own, which `_disposition` never classifies (it returns `"run"`, the tool body
runs, and the `Question` it returns pauses the turn as it always has).

**Streaming.** The classification pass sits **above** `:411`. For a deferred call the loop must
not yield `ToolStarted` at `:414`, and must yield `ToolEnded(id, name, result="")` — the same shape
already emitted for a question at `:419` — so no card is left spinning. `ToolCallBegin`'s
`ToolStarted` at `:389-390` still fires for every call; that is a pre-existing cosmetic artefact
(R5), not a behaviour change.

### D4 — a deferred call executes on resume, and cannot be given a result by the caller (`flow/lib/agent.py:281-305`)
`_prepare_resume`'s `else` (`:301-302`) records the person's answer as a pending call's result. That
is right for a tool that asked its own question and **wrong** for a call nobody was asked about,
which D3 now creates.

A new branch, ordered **after** rows 1–3 (`:290-300`) and **before** today's `else`. A call is
*deferred* when **all** of:
- `call.id not in answers` — note `not in`, not `answers.get(...) is None`; and
- with a record (`asked` given): `call.id` is not the key of **any** question in `asked` — a new
  `_all_question_keys(asked)` beside `_approval_question_keys` (`:668-692`), which filters to
  approval options and so cannot answer this; and
- the tool is present and not gated (rows 1–3 already handled the other cases).

Then: if `_has_denial(answers)` (`:722-725`), resolve with `_withheld_confirmation()`-shaped
wording (`:706-719`) — refusing one action shown in a group refuses the group, and a deferred read is
part of that group precisely because D3 held it back for the group's sake. Otherwise run it and
record its real result.

**And one new fail-closed case.** With a record, a call that **is** in `answers` but is the key of
no question in `asked` resolves as `_not_executed("approval_no_longer_applies")` — never by echoing
the answer. `answers` arrives from `flow/api/api.py:44-62` through `_parse_answers` (`:259-267`),
which validates the **shape only**: any JSON object with any keys is accepted. Without this case a
caller can hand the model arbitrary text as the result of a tool call nobody approved, which is the
defect `_not_executed` exists to stop (`:695-703`). **AT7b** pins it.

`_prepare_resume` is **not** byte-pinned: the pinned four are `_invoke`, `_resolve_confirmation`,
`_confirmation_question`, `_has_denial` (`flow/tests/test_deny_stops_batch.py:360-365`).

### D5 — the refusal text (`flow/lib/agent.py:46-56`)
A third entry in `NOT_EXECUTED_MESSAGES`, whose two existing entries are at `:47-55`:

```
"unattended": (
    "This action was not carried out and nothing was done. It needs someone to approve it, and "
    "this run has nobody who can. Do not report it as done. Say it needs a person."
),
```

Returned through `_not_executed("unattended")` (`:695-703`), already a pure literal function.
**Rule 3 check:** no platform, product, vendor or model name, and no value supplied by anyone.
AT14 pins it.

### D6 — the byte-pin re-baseline (`flow/tests/test_deny_stops_batch.py:361`)
D2 edits `_invoke`, so `BASELINE_DIGESTS["_invoke"]` (current value
`745260a7da1fe7e9221cf6257de98eeb7c7e23edf5eb4e1ce17d4d0505f5fa4f`, `:361`, asserted at `:378-384`,
positive control at `:386-394`) goes red. The owner's exception permits re-baselining exactly this
one digest. The new value is taken from the engine **after** the change, in a commit that names this
spec, and the other three digests must be byte-unchanged in the same commit.

`test_deny_stops_batch.py` is fork-owned — measured: it is absent from
`git ls-tree -r --name-only develop flow/tests/`, which does list `flow/tests/test_ai_agent.py`.
`BASELINE_DIGESTS` is a `ClassVar` on `TestTheLoadBearingFunctionsAreUntouched` (`:346`, `:360`),
so any test reading it imports the class.

--------------------------------------------------------------------------------------------------
## Exceptions required, and exactly which upstream assertions change
--------------------------------------------------------------------------------------------------

| # | upstream assertion | today | after | inside the owner's exception? |
|---|---|---|---|---|
| 1 | `flow/tests/test_ai_agent.py:622-624` `test_auto_approve_runs_confirmation_tool_without_pausing` | `assertFalse(result.paused)`; `calls == [{...}]  # ran unattended`; `output == "done"` | `assertFalse(result.paused)` **unchanged**; `assertEqual(calls, [])` — it did **not** run; `output == "done"` **unchanged**; plus a new assertion that its tool message parses to `status == "not_executed", reason == "unattended"`. The test's name and comment are updated to say refused, not approved | **YES** — the owner extended it to `:613-624` |
| 2 | `flow/tests/test_ai_triggers.py:400` `test_fire_pauses_on_confirmation_tool_without_auto_approve` | `status == "Paused"` | `status == "Completed"`, plus an assertion that the `execute` body never ran. The name and the comment at `:394` change with it | **NO — and this is the blocker** |
| 3 | `flow/tests/test_ai_triggers.py:391` `test_fire_auto_approves_confirmation_tools_when_enabled` | `status == "Completed"` | **unchanged and still green** — its tool is `execute`, now refused rather than approved, but the refusal is a literal result, not a pause, so `_final("done")` (`:378`) still runs and the run still completes. Only its name and comment are now wrong, and changing a name is not an assertion change | needs the same extension as #2, for the rename only |
| 4 | `flow/tests/test_ai_agent.py:731` | `assertEqual([c.name for c in paused.tool_calls], ["read_file"])` | **UNCHANGED.** v1 proposed replacing it; that was wrong (see "What changed from v1" #3) and the exception for `:714` is not used | not needed |
| 5 | `flow/tests/test_ai_agent.py:434` `test_other_tools_run_while_a_question_pauses` | `[c.name for c in result.tool_calls] == ["safe"]` | **UNCHANGED.** Both its tools are plain `@tool`s and the pause comes from `ask_user`'s own return value, which `_disposition` does not classify | not needed |

Every assertion that changes gets **stronger**: #1 goes from "it ran" to "it did not run, and the
model was told why"; #2 goes from "the run is stuck" to "the run finished and nothing was written".

**Build gate.** Part A may be built today. **Part B is DO-NOT-BUILD until the owner extends the
exception to `flow/tests/test_ai_triggers.py:393-400` (and the rename at `:381`).** The trade is
favourable: exception item "the test around `:714`" is handed back unused (#4), and this one is
needed in its place.

--------------------------------------------------------------------------------------------------
## What must not change
--------------------------------------------------------------------------------------------------
1. **`resume_run`'s answers.** `Question.key` (`agent.py:74`), `result.key = call.id` (`:349`,
   `:417`), `answers.get(call.id)` (`:282`), `CONFIRM_ANSWER_OPTIONS` (`:42`),
   `_approval_question_keys` (`:668-692`) and `flow/api/api.py`'s signature. No web-app change is
   required: the pause shape, question shape and answer shape are identical; only how much has
   already run when the pause arrives changes. **AT18** pins this (v1 cited AT12, which is a
   different test — corrected).
2. **`_resolve_confirmation`, `_confirmation_question`, `_has_denial`** stay byte-identical. Only
   `_invoke`'s digest is re-baselined (D6). **AT15.**
3. **The group rule.** `_prepare_resume`'s denial behaviour (`:277`, `:295-296`) and
   `test_deny_stops_batch.py`'s assertions are unchanged in meaning; D4's deferred calls join the
   group rather than sidestep it. `_pause_on_two` (`test_deny_stops_batch.py:117-130`) builds a
   batch of **two gated calls**, so Part A does not change it — verified by reading.
4. **`test_deny_stops_batch.py:320-343`** `test_a_pending_call_on_an_ungated_tool_resolves_as_today_even_in_a_denied_batch`:
   the call **is** in `answers`, so D4's branch must not claim it and `:302`'s `else` must. **AT7.**
5. **A turn with no approval in it.** Same messages, same order, same number of model calls. **AT6.**
6. **`test_ai_agent.py:411`** stays green unmodified. **AT5.**
7. **`flow/tests/test_write_tools_confirm.py`, `test_s16_memory_hardening.py`,
   `test_s16c_memory_by_construction.py`** — fork-owned registry tests. Nothing in v2 adds a field
   they read.
8. **S17's duplicate-id refusal** — **not applicable.** S17 has not landed at `veyqon`:
   `_assistant_message` (`:513-527`) has no such check and `_validate_messages` (`:498-510`) checks
   role and `tool_call_id` presence only. v1 claimed AT13 pinned the ordering; it does not, and the
   claim is dropped rather than faked. If S17 lands first, its check runs at `:334`/`:396`, above
   D3's pass, and one ordering test is added then.

--------------------------------------------------------------------------------------------------
## Acceptance tests
--------------------------------------------------------------------------------------------------
New file `flow/tests/test_s19_batch_is_one_decision.py` (fork-owned). Every test is watched failing
before it passes (workflow rule 2); the mutation named is the one that turns *that* test red for
*that* reason.

**Permissions.** AT1–AT15 and AT18 exercise the code `Agent` with fake tools: no doctype field, no
whitelisted method, no record-level check, so no permission surface. AT14, AT16 and AT17 touch
records and **each runs as a named non-Administrator user** created in `setUp`
(`s19-tester@example.com`, System Manager) with `frappe.set_user`, restored in `tearDown`.

### Part A
**AT1 — `test_an_ungated_call_beside_a_gated_one_does_not_run`**
One batch (a hand-built `ChatResponse` with two `ToolCall`s — **not** two `_tool_call` responses,
which would be two turns): ungated `read_balance` (recorder) then gated `send_money`. Assert
`result.paused`, `len(result.questions) == 1`, `result.tool_calls == []`, and the read recorder is
empty. *Mutation:* delete D3's first pass in `_loop` → the recorder holds one read.

**AT2 — `test_the_gated_call_first_makes_no_difference`** — the same batch reversed, same
assertions. *Mutation:* make the first pass stop at the first `"ask"` instead of scanning the whole
batch → green here, red on AT1.

**AT3 — `test_the_deferred_call_runs_on_resume_before_the_approved_one`**
Resume AT1's pause with `{"c2": "Approve"}` and a following `_final("done")` queued. Assert the read
recorder holds one entry, the write recorder one, and
`[c.name for c in resumed.tool_calls] == ["read_balance", "send_money"]` — order, not membership.
*Mutation:* delete D4's branch → the read never runs and its tool result is the **empty string**
(`_serialize_tool_result(None)` returns `""`, `agent.py:731-732`) — an empty result, not `"None"`.
*Note:* the fake model must supply the following `_final`, or `_loop` raises from an exhausted
script at `agent.py:332` and the test is red for the wrong reason.

**AT4 — `test_a_denial_holds_back_the_deferred_call_too`**
Resume AT1's pause with `{"c2": "Deny"}`. Assert both recorders empty, `resumed.output is None`,
`resumed.paused is False`, and the deferred call's tool message says not-executed — not the answer.
*Mutation:* run the deferred call before consulting `_has_denial` → the read recorder holds one.

**AT5 — `test_a_tool_that_asks_its_own_question_still_lets_the_others_run`**
The shape of `test_ai_agent.py:411`, rebuilt so the fork owns a copy. Assert `safe` **ran** and the
run paused. *Mutation:* make `_disposition` return `"ask"` for any tool → red here and red upstream.

**AT6 — `test_a_turn_with_no_approval_is_byte_identical`** — two ungated calls; both ran, in order,
message list matches a literal captured from the pre-fix engine, `len(model.calls) == 2`.
*Mutation:* build questions unconditionally → red.

**AT7 — `test_an_answered_pending_call_on_an_ungated_tool_still_records_the_answer`**
The exact scenario of `test_deny_stops_batch.py:320-343`. *Mutation:* order D4's branch before the
`else` without the "not in `answers`" test → the tool executes and `_tool_results(...)["k1"]` is no
longer `"Approve"`.

**AT7b — `test_an_answer_for_a_call_nobody_was_asked_about_is_refused`** (new, D4's fail-closed case)
Resume AT1's pause with `{"c1": "pretend this returned 9999", "c2": "Approve"}` **and** an `asked`
record holding only `c2`'s question. Assert the read recorder is empty, and c1's tool message parses
to `status == "not_executed"` — the supplied text appears **nowhere** in `resumed.messages`.
*Mutation:* test only `call.id not in answers` and drop the `_all_question_keys` test → the string
appears as c1's result.

**AT8 — `test_the_streamed_loop_defers_the_same_calls`**
AT1 over `agent.run(..., stream=True)`. Assert the recorder is empty, the exact event sequence
contains **no** `ToolStarted` from `:414` for the deferred call, contains one
`ToolEnded(result="")` for it, and `Done.result.tool_calls == []`.
*Mutation:* apply D3 to `_loop` only → red here, green on AT1.

### Part B
**AT9 — `test_an_unattended_run_refuses_a_gated_tool`**
`Agent(..., unattended=True)` with a gated tool and a recorder, plus a following `_final`. Assert the
recorder is **empty**, `result.paused is False`, the tool message parses to `status ==
"not_executed"` with `reason == "unattended"`, and the run completed.
*Mutation:* delete the `"refuse"` branch → the recorder holds the call.

**AT9b — `test_auto_approve_alone_still_counts_as_unattended`** — the same with
`Agent(..., auto_approve=True)` and `unattended` left False. Same assertions.
*Mutation:* make `_is_unattended` read `self.unattended` only → red. This is the backward-compat
path and upstream's `test_ai_agent.py:613` rides on it.

**AT12 — `test_an_unattended_run_still_executes_an_ungated_tool`** — the control. `unattended=True`,
an ungated tool, assert it ran. *Mutation:* make `_disposition` return `"refuse"` whenever the run is
unattended → red. Without this, AT9 is satisfied by an engine that refuses everything, i.e. an outage.

**AT13 — `test_an_attended_run_is_unaffected`** — `unattended=False, auto_approve=False`, a gated
tool → the run **pauses and asks**, exactly as today.
*Mutation:* let `"refuse"` win over `"ask"` unconditionally → the run completes with a refusal
instead of asking a person who is there to be asked.

**AT16 — `test_a_trigger_with_auto_approve_off_refuses_instead_of_pausing`** (new; this is the one
that pins the whole of Part B to a real run)
Create a Flow Trigger with `auto_approve = 0` and `run_as` set to the named non-Administrator user,
patch `Model.chat` with a script calling a gated builtin then `_final`, call `flow.triggers.fire`,
and assert: the Flow Run status is `Completed`, the tool body never ran, the tool message says
`reason == "unattended"`, and `frappe.session.user` inside the run was the named user (not
Administrator — `triggers.py:75` sets it).
*Mutation:* delete `self._runtime.unattended = unattended` from `flow_session.py` → the run is
`Paused`. **Nothing else in S19 turns red for that mutation**, which is why this test exists.

**AT17 — `test_a_resume_is_never_unattended`** — pause an ordinary chat turn, resume it through
`FlowSession.resume`, and assert the resumed runtime's `unattended` and `auto_approve` are both
False and an approved gated tool ran. *Mutation:* set `unattended` in `resume` too → the approved
call is refused and a person who approved something is told it did not happen.

### Cross-cutting
**AT14 — `test_the_refusal_names_no_platform_or_vendor`** (CLAUDE.md rule 3)
`NOT_EXECUTED_MESSAGES["unattended"]` contains none of `frappe`, `erpnext`, `mariadb`, `openai`,
`anthropic`, `gpt-`, `claude`, `flow`, case-insensitively. Runs as the named non-Administrator user.
*Mutation:* add `Frappe` to the literal → red. *Control:* the same helper over a string containing
`frappe` must raise `AssertionError`, written as `with self.assertRaises(AssertionError):` so the
control itself can go red.

**AT15 — `test_only_the_invoke_digest_moved`** — imports
`TestTheLoadBearingFunctionsAreUntouched` from `flow.tests.test_deny_stops_batch` (the **class** —
`BASELINE_DIGESTS` is a `ClassVar` at `:346`/`:360`) and asserts the three digests other than
`_invoke` equal the values quoted as literals here. *Mutation:* change one character in
`_resolve_confirmation` → red here and at `test_deny_stops_batch.py:378`.

**AT18 — `test_the_pause_and_answer_shapes_are_unchanged`** (v1 mis-cited this as AT12)
Over AT1's pause: every question's `options == list(CONFIRM_ANSWER_OPTIONS)`, every `key` equals the
`call.id` it belongs to, `allow_other is True`, and resuming with `{key: "Approve"}` alone succeeds.
*Mutation:* change `CONFIRM_ANSWER_OPTIONS` or stop setting `result.key = call.id` → red, and the
web apps would have broken silently.

--------------------------------------------------------------------------------------------------
## Which evals scenarios flip
--------------------------------------------------------------------------------------------------
| gate | command | covers |
|---|---|---|
| `GATE=GREEN` | `scripts/run-tests.sh` | AT1–AT18 and every existing `flow/tests/` module |
| `EVALS_GATE` | `evals/run.sh` | the two scenarios below. **Not** inside `GATE=GREEN` |

`evals/` does not exist on `develop` (measured: `git ls-tree -r --name-only develop evals/` returns
nothing), so every file under it is fork-owned.

**`ungated_call_beside_a_gated_one` — flips to PASSED, file unchanged.** Its `expect` block
(`:35-49`) already states the post-fix contract: `pauses: true`, `tool_calls: []`, one question with
`[Approve, Deny]`, `after.denied` → `executed: []`, `output: null`, `paused: false`. A **human**
then removes the `known_defect` block (`:3-8`), because `evals/tests/test_known_defects.py` turns the
suite red on a known defect that starts passing.

**`auto_approve_turns_every_gate_off` — needs its `expect` rewritten by a human.** Today it demands
a pause (`:34-39`); Part B refuses instead. Its `send_money` no longer needs any new key — under the
owner's rule `requires_confirmation: true` is the whole declaration. Proposed replacement, to be
written by a **human**:

```yaml
expect:
  pauses: false
  tool_calls: []
  tool_results:
    c1:
      contains: ["not_executed", "unattended"]
  absent_text: [frappe, erpnext, mariadb, openai, anthropic, gpt-, claude]
```

**Both of those keys are dead on the forward path today and the runner must be changed** —
`_check_tool_results` (`evals/run.py:222`) is called only at `:366`, inside `_run_answer_case`, and
`_check_absent_text` (`:245`) only at `:303`, `:306-308`, `:375`. Either the runner gains a call over
a completed run's output and tool results, or the keys come out of the scenario rather than reading
as coverage that is not there. **This is part of Part B's build, not an option.**

**Human edits required, total: 3** — drop one `known_defect` block; rewrite one `expect` block; drop
the second `known_defect` block once it passes.

--------------------------------------------------------------------------------------------------
## Size
--------------------------------------------------------------------------------------------------
| part | file | change | ~lines |
|---|---|---|---|
| A+B | `flow/lib/agent.py` | `unattended` field, `_is_unattended`, `_disposition`, `_invoke` rewritten | 22 |
| A | `flow/lib/agent.py` | `_loop` first pass | 12 |
| A | `flow/lib/agent.py` | `_loop_stream` first pass | 14 |
| A | `flow/lib/agent.py` | `_prepare_resume` branch + `_all_question_keys` | 18 |
| B | `flow/lib/agent.py` | `NOT_EXECUTED_MESSAGES["unattended"]` | 5 |
| B | `flow/flow/doctype/flow_session/flow_session.py` | pass `unattended` to the runtime | 3 |
| B | `evals/run.py` | forward-path `tool_results` and `absent_text` checks | 14 |
| B | `flow/tests/test_ai_agent.py` | **upstream, under the exception** — `:613-624` rewritten to refused | 8 |
| B | `flow/tests/test_ai_triggers.py` | **upstream, NEEDS A NEW EXCEPTION** — `:400` and two names | 6 |
| A+B | `flow/tests/test_deny_stops_batch.py` | `_invoke` digest re-baselined | 1 |
| A+B | `flow/tests/test_s19_batch_is_one_decision.py` | new, AT1–AT18 | ~400 |
| A+B | `evals/scenarios/*.yaml` | **human** — 3 edits | 12 |

**Engine code: ~88 lines across three files** (v1 said five; `flow/lib/tool.py`,
`flow/tools/builtins.py` and `flow/lib/resolver.py` are no longer touched). Tests: ~415.

--------------------------------------------------------------------------------------------------
## Branches — separate, and sequential
--------------------------------------------------------------------------------------------------
`loop/s19a-batch-is-one-decision`, then `loop/s19b-unattended-refuses-every-gate` branched from
`veyqon` **after A has merged**.

1. **They re-baseline the same byte pin.** Both edit `_invoke` (D2), so both change
   `BASELINE_DIGESTS["_invoke"]` (`test_deny_stops_batch.py:361`). Two branches carrying two digests
   for the same function conflict in the one place a conflict must never be resolved by picking a
   side.
2. **B is blocked and A is not.** B needs a new upstream exception (C3) *and* a human `expect`
   rewrite. Blocking A on either would be avoidable waste.
3. **A is the higher live risk.** A fires in ordinary chat turns today; B has zero live instances
   while production has no triggers.
4. **S20 touches nothing S19 touches** once `write_capable` is gone, so it can run in parallel with
   either. **J2 must come after both** — it edits the same two loop bodies (`agent.py:324-373`,
   `:375-441`) that D3 restructures.

From the harness's own lesson: **while `/loop-verify`'s reviewers run, do not switch branches or
touch the working tree.**

--------------------------------------------------------------------------------------------------
## Risks
--------------------------------------------------------------------------------------------------
- **R1 — `_prepare_resume` gains a fourth kind of pending call, and it is the one with no answer.**
  The function already fails closed three ways (`agent.py:254-264`). D4's branch is the first that
  *executes*, so its ordering relative to rows 1–3 and its two-part deferred test are the whole
  safety argument. AT7 and AT7b exist because getting it wrong runs a tool on the strength of
  somebody's answer to a different question — or on text they typed.
- **R2 — a deferred read is delayed.** The model asked for the read in the same breath as the write
  and now gets it only after the person answers. Behaviourally correct; a model that batches
  aggressively will do more round trips.
- **R3 — every unattended gated call is refused, with no allow-list.** Today that costs nothing (no
  triggers exist). The day someone builds a trigger that must write, they hit a refusal with no way
  around it short of a spec. **Open question 1.** This is the deliberate price of the owner's rule
  and it is the right way round: an outage is recoverable, an unapproved write is not.
- **R4 — `assistant.py:36-38` still tells the model to set `auto_approve=1`.** After B the sentence
  is narrower than the behaviour but not false. **Open question 2.**
- **R5 — the streamed UI draws cards for calls that then do not run.** `ToolStarted` is yielded from
  `ToolCallBegin` at `:389-390` before the batch is classified. Cosmetic; nothing executes, nothing
  persists. The web apps should be checked.
- **R6 — `_rebind_memory_tool` is now redundant for survival but must stay.** The rule already saves
  an unattended run from parking, but the rebind gives the memory tool's own, better-worded literal
  (`builtins.py:274-276`) and is the only path when `self.agent` is empty (`flow_session.py:272`).
- **R7 — a legacy Paused trigger run.** A run that paused before S19 can still be resumed by a
  person through `resume_run`; nothing about that changes. After S19 no new one can be created.

--------------------------------------------------------------------------------------------------
## Upstream position
--------------------------------------------------------------------------------------------------
**Part A: upstreamable, and now cleanly so** — it is entirely in `flow/lib/agent.py` and edits **no**
upstream test at all (see "What changed from v1" #3). Branch from `develop`, engine code only,
conventional commit (`fix: nothing in a turn runs if anything in it needs approval`).

**Part B: not upstreamable as specced.** It changes two upstream trigger tests and depends on the
fork's notion of an unattended run. A narrower version — *an unattended run refuses a gated tool* —
is a reasonable upstream proposal on its own, but it needs upstream to agree that
`test_auto_approve_runs_confirmation_tool_without_pausing` was asserting a defect. Not attempted here.

--------------------------------------------------------------------------------------------------
## Open questions for the owner
--------------------------------------------------------------------------------------------------
1. **When a trigger genuinely needs to write unattended, what authorises it?** A per-trigger
   allow-list, a per-tool `unattended_ok` declaration, or a signed configuration — each is its own
   spec. Deferred on the strength of "no triggers in production".
2. **Should `flow/assistant/assistant.py:36-38` be reworded now or with question 1's answer?** It is
   one string in one file, and it is the sentence that causes the first trigger to be created with
   the flag on.
3. **The blocker: extend the exception to `flow/tests/test_ai_triggers.py:393-400`?** Without it
   Part B cannot be green. The assertion changes from "the run is stuck in Paused" to "the run
   finished and nothing was written", which is strictly stronger.

---

## AMENDED, run 11 — Part B covers the other way a run pauses (REVIEW-FLOW-10 M2)

Part B as written closes one of the two routes into `Paused`: a tool whose RECORD or CODE says it
needs approving. The second route is a tool whose **body returns a `Question`**. `_disposition`
excludes those on purpose — by the time such a question exists the body has already run, so holding
its neighbours back would protect nothing — and that reasoning is right for Part A and does not
carry to Part B. In an unattended run such a question still parked the run in `Paused`, holding its
session, with nobody who could ever answer it. That is the exact failure this spec exists to remove,
arriving by the other door, and it is the one `_rebind_memory_tool` was written to dodge for a
single tool.

**The rule extends:** in an unattended run, a `Question` returned by a tool is converted to
`_not_executed("unattended")` instead of being appended to `questions`. Both loops, identically.
The tool's BODY is not undone — it has run, and nothing pretends otherwise; what is refused is the
question, so the model is told the action was not carried through rather than left mid-sentence.
`_invoke` is untouched and its byte pin does not move: the conversion is in the loops, where the
`Question` is consumed.

Reachability: no shipped tool returns a `Question`. The only `Question(` construction outside tests
in `flow/{tools,lib,memory,knowledge}` is `_confirmation_question`, and that same grep hitting
exactly one line is the positive control for the claim. It is a supported pattern for code agents
and upstream exercises it (`test_other_tools_run_while_a_question_pauses`), so it is reachable for
anyone writing one.

**AT19** `test_a_tools_own_question_does_not_park_an_unattended_run`, **AT19b** the streamed twin,
**AT19c** the control that an attended run still pauses on such a question. All three in
`flow/tests/test_s19_batch_is_one_decision.py`. *Mutation:* drop the conversion in both loops ->
AT19 and AT19b come back `paused=True`.
