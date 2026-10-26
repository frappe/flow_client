---
type: inbox
status: ranked — for the owner to turn one of these into S17
created: 2026-09-20
---
# The three known defects, ranked

Three scenarios in `evals/` carry `known_defect:`. They hold nothing red, they are printed with
their reason on every run, and **no spec has claimed any of them**. This note is the comparison
needed to choose. Every path below was re-read on `veyqon` (`14da9b3`) and every line number is that
revision's — not inferred from the scenarios' own descriptions.

Nothing here is a fix and nothing here starts one.

> **A stale reference found while writing this.** `evals/scenarios/one_approval_can_execute_two_writes.yaml`
> says the defect is "Captured at `brain/00-inbox/one-approval-can-execute-two-writes.md`". **That
> file does not exist** — the scenario is the only record there is. Either write the note or correct
> the scenario's text; a one-line discrepancy, not a defect of its own.

--------------------------------------------------------------------------------------------------
## Rank 1 — `auto_approve_turns_every_gate_off`
--------------------------------------------------------------------------------------------------
**One flag turns off every approval in the engine, and the shipped assistant tells the model to set
it.**

### The code path
- `flow/lib/agent.py:485` — `if tool.requires_confirmation and not self.auto_approve:`
  The condition is "the tool is gated **and** this run is not auto-approving". With the flag set no
  question is ever built — `_confirmation_question` is never reached — and every gated tool executes
  inline at `flow/lib/agent.py:487` (`return self._run_tool(call)`).
- `flow/lib/agent.py:141` — `self.auto_approve = auto_approve`, one run-wide boolean.
- `flow/flow/doctype/flow_session/flow_session.py:180` — `self._runtime.auto_approve = auto_approve`.
- `flow/triggers/triggers.py:94` — `auto_approve=bool(t.auto_approve)`, read off the record.
- `flow/flow/doctype/flow_trigger/flow_trigger.py:23` — `auto_approve: DF.Check`, a checkbox.
- **`flow/assistant/assistant.py:36` — the line that makes it reachable by anyone:**
  *"On the Flow Trigger set auto_approve=1 unless the user says otherwise — a trigger runs
  unattended, so any tool call needing confirmation would stall forever without it."*

### Who can trigger it in production today
1. **An administrator**, by ticking one checkbox.
2. **A chat user, without knowing any of this exists.** Ask the shipped assistant for anything
   recurring — "email me a summary every morning" — and its own instructions tell the model to create
   the trigger with `auto_approve=1`. The person is shown the JSON and asked to confirm *creating the
   trigger*. They are not told that what they are approving is a run in which no approval will ever
   be asked again. From then on it executes every gated write — create, update, delete, run_action,
   and `execute` (arbitrary code) — with nobody asked.
3. **Every trigger already in production**, on every fire, for as long as it exists.

This is the only one of the three an ordinary person can cause **by asking for a feature they want**,
and the only one whose blast radius is *the whole approval mechanism* rather than one call.

**And it is wider than "the write tools."** A security review during run 7 established two things
that belong here rather than in a memory spec:
- With the flag set, the **`create` builtin writes any doctype the run's identity may write —
  including `Flow Agent Memory` itself.** A trigger whose `run_as` is a System Manager can be asked
  for `create(doctype="Flow Agent Memory", records=[{"scope": "Agent", "content": …}])` and plant a
  **shared standing note** every later conversation is given. That route touches none of the memory
  hardening: not the tool, not its approval, not either refusal.
- The same is true of a **Script tool**, which is arbitrary code that nothing can classify.

So the honest statement is not "gated writes run unasked" but **"in such a run there is no approval
mechanism at all, and the data behind the approvals is writable too."**

### The smallest safe fix
Not the smallest possible change — the smallest one that is safe. `auto_approve` asks the wrong
question. It asks "may questions be skipped in this run", when the only answerable question is "may
*this tool* run unasked in this run".

Keep it as it is for read-only tools. For a tool the engine classifies as write-capable, an
unattended run gets a fixed not-executed result and **does not pause** — exactly the S16a pattern,
for exactly the reason S16a wrote down. The pieces exist: `WRITE_CAPABLE` in `flow/tools/builtins.py`
(S16b) is the classification, and S16a's D4 is the precedent. The change is one condition in
`_invoke` plus a per-trigger allow-list for the writes an administrator deliberately wants unattended.

### What it would break
- **Every trigger whose job is to write.** "Create the weekly report", "send the reminder emails" —
  all of them stop working and start returning "not executed" to the model. That is the main use of a
  trigger, so a fix without the allow-list is not shippable: **the allow-list is the spec, not an
  extra.**
- **Two upstream tests assert today's behaviour**: `flow/tests/test_ai_triggers.py:381`
  `test_fire_auto_approves_confirmation_tools_when_enabled` (the `execute` tool runs unattended) and
  `flow/tests/test_ai_agent.py:613` `test_auto_approve_runs_confirmation_tool_without_pausing`. Hard
  limit 6 forbids this fork to edit either, so **this cannot be fixed in the fork without the same
  decision run 6 put about S16a's two pins.** That is the single most important fact on this page.
- **`_invoke` is a rule-4 load-bearing function.** A spec that names it is exactly what this is.
- `flow/assistant/assistant.py:36` has to change too, or the model keeps writing the configuration
  the fix now refuses to honour.
- **The allow-list is not enough on its own** unless `Flow Agent Memory`, `Flow Agent`, `Flow Tool`
  and `Flow Trigger` are also excluded as targets of the generic write builtins in such a run —
  otherwise a trigger allowed to create anything can rewrite the configuration that decides what it
  is allowed to do. `triggers.dispatch` already excludes those doctypes from *firing* triggers, so
  there is a precedent for treating them as not-ordinary-data.

--------------------------------------------------------------------------------------------------
## Rank 2 — `ungated_call_beside_a_gated_one`
--------------------------------------------------------------------------------------------------
**A read runs in the person's name while they are still reading the question about the write.**

### The code path
- `flow/lib/agent.py:346` — `for call in response.tool_calls:`
- `flow/lib/agent.py:347` — `result = self._invoke(call)`. Each call is invoked in the order the
  model emitted them. An ungated one runs here and now.
- `flow/lib/agent.py:348-351` — a `Question` is collected into `questions` and the loop `continue`s.
  **It does not break.**
- `flow/lib/agent.py:362` — `if questions:` returns the paused result, **after the whole batch has
  been walked.** Every ungated call has already executed by the time the question exists, let alone
  reaches a person.
- `flow/lib/agent.py:382` onwards — the streamed loop has the same shape.

### Who can trigger it in production today
**Any chat user, in an ordinary turn, with no attacker anywhere.** A model asked to "check the
balance and pay her" batching a read with a write is normal, well-behaved behaviour, not a
manipulation. It is the most *frequent* of the three.

What actually executes is better than it looks: since S16b every write-capable builtin ships gated
and every read-only one ships ungated, so the calls that run early are reads. The exceptions are the
ones S16b cannot classify — **a Script tool (arbitrary Python, gated by default only since S16b's D4)
and any Imported tool that does not declare its own approval.** Those can write.

So: reliably a disclosure and an unapproved side effect — a read performed and recorded in the
person's name, not undone by a Deny, with nothing telling them it happened — and an unapproved
**write** wherever an administrator has an ungated custom tool.

### The smallest safe fix
Two passes over the batch in `_loop` and `_loop_stream`: decide first, execute second. If any call in
the batch needs an approval, build the questions, execute **nothing**, return paused. On resume, the
calls that needed no approval execute then, in their original order, before the loop continues.

This is S14's principle — a batch is one decision — extended from "a Deny stops the others" to "a
pending question stops the others".

### What it would break
- **`_prepare_resume` has to learn to execute a call nobody was asked about.** Today its `else`
  branch (`flow/lib/agent.py:302`) treats an unasked pending call's *answer* as the tool's result,
  which is right for a tool that asked its own question and wrong for a deferred read. That is the
  real cost, and it is not a one-liner; `_prepare_resume` is the function S14 and S15 both changed,
  so it is well covered and also dense.
- **A turn costs an extra round trip.** A read the model wanted in order to *decide* the write now
  happens after the write is approved. Some prompts get worse.
- **A Deny now discards work that used to be done.** That is the point, and it is a behaviour change.
- Nothing in `flow/tests/` appears to assert today's order — I read for it rather than proving its
  absence, so **check that before relying on it.** If it holds, this is the only one of the three
  fixable inside the fork with no decision from anybody.

--------------------------------------------------------------------------------------------------
## Rank 3 — `one_approval_can_execute_two_writes`
--------------------------------------------------------------------------------------------------
**Two calls sharing one id, one answer key, two executions — and one card shown.**

### The code path
- `flow/lib/agent.py:457-462` — `_transcript_calls` walks every `tc` in every assistant message's
  `tool_calls` and appends one `ToolCall` per entry. **There is no deduplication by `tc["id"]`.**
  `has_result` (`:452`) is a *set* of ids, so the two entries are indistinguishable to it: while
  neither has a result both are pending, and the moment one result exists both count as answered.
- `flow/lib/agent.py:346-351` — at pause time each produces its own `Question`, and `result.key =
  call.id` gives them **the same key**.
- `flow/lib/agent.py:277-303` — `_prepare_resume` loops over every pending call and reads
  `answers.get(call.id)`. One `{"c1": "Approve"}` answers both.
- `flow/lib/agent.py:307` — `_resolve_confirmation` runs the tool for each, so the write happens
  **twice**, and two `tool` messages with the same `tool_call_id` are appended.

### Who can trigger it in production today
**Nobody directly. The ids are the model's.** No person types a `tool_call_id`; it arrives in the
model's response. Providers generate unique ids, so this needs a model that collides them — a
provider bug, a local or self-hosted model, or a model steered by injected text into emitting a
crafted response. Anyone who can run server code could hand-craft the transcript, but they were never
contained by any of this.

So: the **worst impact** of the three (a money-moving write executed twice on one approval, with the
interface showing one action) and the **narrowest reachability** — it needs the model to do something
no well-behaved provider does.

### The smallest safe fix
Refuse rather than repair, and refuse early: when a model's response contains two tool calls with the
same id, the batch is not answerable — one question cannot address two calls — so fail the turn with
an explicit error instead of pausing on it. One check where the assistant message is built.

The tempting fix is to deduplicate in `_transcript_calls` (keep the first per id). **It is smaller and
it is worse**: it silently drops a call the model asked for, which is the same class of quiet
divergence between what was shown and what happened as the defect itself.

### What it would break
- A run whose model emits colliding ids now fails loudly instead of quietly doing the wrong thing.
  That is the intent; it is still a new failure mode for anyone running such a model today, who
  currently sees a doubled write and may not have noticed.
- The check reads the response before `_invoke`, so it touches the loop but **not** any rule-4
  function. Of the three this is the most self-contained change.

--------------------------------------------------------------------------------------------------
## The ranking, and why in this order
--------------------------------------------------------------------------------------------------
| rank | defect | who can cause it | what is lost | how self-contained the fix is |
|---|---|---|---|---|
| **1** | `auto_approve_turns_every_gate_off` | a chat user asking for a recurring task; any administrator | **every** approval, for **every** write tool, for the life of the trigger | poor — `_invoke` (rule 4), the assistant's instructions, two upstream tests |
| **2** | `ungated_call_beside_a_gated_one` | any chat user, ordinary use, no attacker | a read performed unapproved and not undone; an unapproved write where a custom tool is ungated | moderate — the loop plus `_prepare_resume` |
| **3** | `one_approval_can_execute_two_writes` | only a model that collides ids | one write executed twice on one approval | good — one check, no rule-4 function |

Risk is reachability times blast radius, and rank 1 wins both axes: an ordinary request produces the
configuration, and the configuration removes the mechanism rather than one call. Rank 2 is far more
*frequent* than rank 3, but what it executes is, by S16b's construction, read-only except where an
administrator ships an ungated tool of their own. Rank 3 has the worst single outcome and a
reachability that depends on a model doing something providers do not do.

## Recommendation: S17 is `auto_approve_turns_every_gate_off`
It is rank 1 on both axes, it is the only one a person can cause by asking for a feature they want,
and it is the only one where the engine's own shipped instructions are part of the path.

It is also, deliberately, the hardest of the three, and the recommendation comes with two things the
owner must decide **before** the spec is written rather than during it:

1. **Two upstream tests assert today's behaviour** (`flow/tests/test_ai_triggers.py:381` and
   `flow/tests/test_ai_agent.py:613`). This is the same decision run 6 put about S16a's two pins, with
   the same three answers: carry the change upstream where the tests move with it, carve them out in
   the fork, or accept a red gate. **A spec written without that decision will strand on it**, exactly
   as S16a did.
2. **A write-performing trigger must keep working**, so the spec has to carry the per-trigger
   allow-list rather than defer it. Refusing every unattended write is a smaller change and an outage.

If the answer to (1) is "not yet", the honest second choice is **rank 2**: no upstream test appears to
assert today's execution order, the fix needs no new configuration surface, and it removes an
unapproved side effect that happens in ordinary use every day. It is the one that can be finished
inside this fork without a decision from anybody.

Rank 3 should wait. Its reachability depends on a model doing something well-behaved providers do
not do, and its fix — one check that fails the turn loudly — will still be one check whenever it is
written.
