---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
implemented: 2026-09-21 (unattended run 9) — see "Found in the build review" before merging
approved-by: owner, run 9
  (v1 drafted by an unattended research session; v2 revised by an unattended adversarial review,
  2026-09-21. The owner approved v2 for unattended run 9 — REVIEW BEFORE MERGE.)
amended-by: owner, run 10, R7 — the refusal applies to the model's NEW reply and to resume, NOT to
  replayed history in `_build_initial_messages`. Status stays approved/implemented; see D3 and
  "Found in the build review".
amended-by: owner, run 11, R10 — the same rule one door over: a resume refuses the turn it is
  LIVE on, never old history. Status stays approved/implemented; see "R10" below.
amended-by: owner, run 11b (2026-09-23) — a SINGLE call carrying an unusable reference is refused
  too, before the reply is stored. The non-goal this withdraws said one such call "is answerable —
  there is nothing to confuse it with"; the owner accepts the counter-reasoning that a reference is
  also how a RESULT is filed, and a stored tool message with no usable reference bricked every later
  turn of that conversation. AT10b is inverted; the refusal carries its own sentence, because the
  two-actions one is false for a single call. Status stays approved/implemented; see "Non-goals",
  the AT10b row, and acceptance entry 3.
created: 2026-09-21
revised: 2026-09-21 (v2)
upstreamable: yes (the engine change only — see "Upstream")
supersedes-choice-of: brain/00-inbox/known-defects-ranking.md recommended rank 1; this spec takes rank 3.
base: veyqon = 04f4eab (every file:line below re-read at that revision; v1 was pinned at the ancestor
  3da5570, which differs only by S18 — no file this spec touches changed between them)
changes-from-v1: |
  Owner decisions applied: refuse (not dedup), and the scenario rewritten to expect the refusal with
  the runner gaining that ability. Corrections from review 2026-09-21 folded in: F1 (a `None` id was a
  live bypass — D1 rewritten, AT10 inverted), F2 (empty-string ids now tested), F3 (new AT1b: the
  ungated double execution is watched), F4 (D4 factored into an engine-free helper so AT11 can run),
  F5 (`absent_text` now applies to the refusal), F6 (one person-readable message), F7–F16.
  Open questions 1 and 2 are closed by the owner; question 3 is closed as "capture it".
---
# Spec: S17 — one approval answers one action (v2)

## Contract, in one sentence
**A model response in which two tool calls cannot be told apart by their reference is refused before
any tool runs — because one approval cannot answer two actions — and a stored transcript containing
such a response cannot be resumed.**

Two calls cannot be told apart when they carry the same id, *or* when neither carries a usable one.

--------------------------------------------------------------------------------------------------
## Problem
--------------------------------------------------------------------------------------------------

### §0 — why this defect and not run 7's rank 1
Run 7 ranked `auto_approve_turns_every_gate_off` first with `ungated_call_beside_a_gated_one` as the
fallback "if the answer to (1) is *not yet*". Both are blocked. Evidence in `S1-ranking-check.md`; the
short form:

| candidate | what blocks it |
|---|---|
| rank 1 `auto_approve…` | `flow/tests/test_ai_triggers.py:381` and `flow/tests/test_ai_agent.py:613` assert today's behaviour; both are upstream's at identical line numbers. **Plus** `_invoke` carries a sha256 byte-identity pin (`flow/tests/test_deny_stops_batch.py:361`). **Plus** it needs a new per-trigger allow-list surface, which run 7 itself says "is the spec, not an extra". |
| rank 2 `ungated_call…` | run 7 wrote *"Nothing in `flow/tests/` appears to assert today's order — check that before relying on it."* It does not hold: `flow/tests/test_ai_agent.py:714` `test_resume_preserves_tool_calls_from_before_the_pause` batches an ungated `read_file` with a gated `write_file` and asserts at `:731` that the read has already run at pause time. It is upstream's and sits in `class TestAgentConfirmation` (`:587`), which CLAUDE.md rule 4 protects by name. |

The *risk* ranking is not disputed and this spec does not reorder it. The *build* ordering is:
rank 3 is the only one of the three that can reach `GATE=GREEN` inside this fork today.

**The owner has since ruled that ranks 1 and 2 may later edit exactly the named upstream test
(`flow/tests/test_ai_agent.py` around `:714`) and re-baseline the named `_invoke` byte pin, under run
7 Task 0's rules. That is not this spec, and S17 does neither.**

### §1 — the defect, re-read at 04f4eab
Nothing distinguishes tool calls whose ids collide, and every downstream decision is keyed by id.

1. **`flow/lib/agent.py:457-462`** — `_transcript_calls` appends one `ToolCall` per `tc` entry, with no
   `seen` set. Two entries sharing an id become two `ToolCall`s.
2. **`flow/lib/agent.py:452`** — `has_result` is a **set of ids**, so the two are indistinguishable to
   the filter at `:458`: while neither has a result both are pending, and the moment *one* result
   exists **both** count as answered.
3. **`flow/lib/agent.py:346-351`** — at pause time each produces its own `Question`, and
   `result.key = call.id` gives them **the same key**. Same shape streamed at `:410-420`.
4. **`flow/lib/agent.py:281-282`** — `_prepare_resume` reads `answer = answers.get(call.id)`. One
   `{"c1": "Approve"}` answers both.
5. **`flow/lib/agent.py:298` → `:307-311`** — `_resolve_confirmation` runs the tool at `:310`. **The
   write happens twice**, and two `tool` messages with the same `tool_call_id` are appended at `:303`.

The interface stamps one card. A person approves one action and two happen.

### §1a — the shape v1 missed: a call with no usable id (review F1, F2)
A colliding *non-empty* id is not the only way two calls become indistinguishable, and it is not the
likeliest. **A call with no id at all is worse, because today nothing refuses it anywhere.**

- `_validate_messages` checks ids only on `tool` messages (`flow/lib/agent.py:507-508`). It never
  inspects an assistant message's `tool_calls` entries. Neither does `_assistant_message`.
- `_normalize` reads the id as `_attr(raw_call, "id", "")` (`flow/lib/model.py:244`), and `_attr`
  (`:261-266`) returns its default **only when the key or attribute is absent**: both
  `obj.get(key, default)` and `getattr(obj, key, default)` return a present-but-null value unchanged.
  So a provider emitting `{"id": null, …}` twice produces two `ToolCall(id=None)`.
- The streaming accumulator initialises `slot["id"] = ""` and overwrites only on a truthy id
  (`model.py:185-188`); `_finalize_tool_calls` (`:204-206`) drops a slot only when id **and** name are
  both empty. So a provider or gateway that omits ids gives every call in the turn `id=""`.

Both shapes route straight into §1 steps 2–5, with `None` or `""` as the shared key. **A rule that
compares only non-empty strings would leave the more likely defect live.** Hence D1 below folds them in
rather than skipping them, which is the single largest change from v1.

### §2 — why refusing, not repairing (owner decision: REFUSE)
**The owner has decided: on a duplicate tool-call id within one model reply, refuse — fail closed,
write nothing. Not dedup.** This section records why, and is no longer an open question.

The tempting fix is to deduplicate in `_transcript_calls` (keep the first per id). It is smaller and it
is worse: it silently drops a call the model asked for, which is the same class of quiet divergence
between what was shown and what happened as the defect itself.

A response whose calls cannot be told apart is a **protocol violation**, not a preference. The engine
already refuses malformed input rather than repairing it — `_validate_messages`
(`flow/lib/agent.py:498-510`) throws on a bad role, a `tool` message with no `tool_call_id`, a message
with neither `content` nor `tool_calls`. Refusing here is consistent with that, not a new posture.

**The rejected alternative, recorded.** The other precedent is `call.error`: a malformed-JSON argument
is fed *back* to the model as a tool result and the run continues (`flow/lib/agent.py:480-481`, pinned
by `test_parse_error_feeds_back_and_run_continues` at `test_ai_agent.py:783`). Feeding back would avoid
failing the run. It is rejected for two reasons: it would append two `tool` messages sharing one
`tool_call_id`, which is the malformed transcript this spec exists to prevent; and a provider that
collides ids will keep colliding them, so the model would spin to `max_iterations` instead of failing
once, visibly. **Refuse early, and only once.**

--------------------------------------------------------------------------------------------------
## Goal
--------------------------------------------------------------------------------------------------
One approval executes one action. A batch that cannot be answered unambiguously is not offered to
anyone to answer.

## Non-goals
- **Deduplication.** Explicitly not built; see §2. Owner-decided.
- **Making a colliding model usable.** If a provider collides ids, this engine stops.
- **A *single* call with no id — WITHDRAWN. Amended by the owner, run 11b (2026-09-23).**
  It read, and this is the text being withdrawn: *"One id-less call is answerable — there is nothing
  to confuse it with — and refusing it would be a behaviour change this spec has no evidence for.
  Only a turn in which **two or more** calls share an id, or lack one, is refused. This asymmetry is
  deliberate and is pinned by a control test (AT10b)."*

  **Why it changed.** The evidence the old text said did not exist arrived. A reference is not only
  how an answer is matched, it is how a RESULT is filed: both loops and `_prepare_resume` write
  `{"role": "tool", "tool_call_id": call.id, ...}`, and a tool message with no usable reference is
  one the structural check has always rejected. So one such call waved through and executed wrote a
  message into the stored transcript that made *every later turn of that conversation* raise — the
  conversation was over, recoverable only by someone who could delete the stored row. Refusing the
  reply costs the one unanswerable reply; waving it through cost the conversation. It is refused
  before anything is stored or invoked, in `_assistant_message`, where every other unanswerable
  reply is refused.

  This is **not** the collision rule reaching further, and it does not borrow the collision rule's
  sentence: a single call collides with nothing, and telling a person "two actions could not be told
  apart, so one approval would have answered both" when there was one action and no approval is the
  same untruth the run-11b fixes exist to remove. It raises its own literal (`_UNFILEABLE_CALL`).

  **What is still a non-goal here.** Repairing a transcript that already holds such a message.
  Replay reads history, never refuses it — R7's and R10's rule, unchanged: `_build_initial_messages`
  and `_prepare_resume` both pass `refuse_unusable_tool_results=False`, and each of those two
  opt-outs is now pinned by its own test.
- **`auto_approve`** (run 7 rank 1) and **the batch execution order** (rank 2). Untouched. See
  `S3-next.md`. Each new test says so in its docstring rather than implying coverage.
- **Ids colliding across *different* assistant messages in one transcript.** Out of scope — see R3.
  It is captured to the inbox as a separate item, not absorbed here (owner decision).

--------------------------------------------------------------------------------------------------
## Design — the smallest change, with exact file:line
--------------------------------------------------------------------------------------------------

Three edits in one engine file, plus one capability the evals runner is missing.

### D1 — one predicate, in one place
**New module-level function in `flow/lib/agent.py`, inserted immediately above `_validate_messages`
(currently `flow/lib/agent.py:498`), so both callers below it and above it read the same rule.**

```python
# A tool call that cannot be told apart from another in the same turn cannot be approved separately
# from it. There are two such shapes and they fail the same way downstream, so they are one rule
# here: two calls carrying the same id, and two calls carrying no usable id at all — `None` from a
# provider that sends a null, `""` from one that omits the field or never streams it. Both end up as
# the same `Question.key`, the same `answers.get(...)` lookup and the same `has_result` membership,
# which is the defect. Anything that is not a non-empty string is folded to one bucket rather than
# skipped: skipping it is what left the likelier half of this defect live.
NO_CALL_REFERENCE = "<none>"


def _indistinguishable_tool_call(ids: Iterable[Any]) -> tuple[bool, str] | None:
	"""The first reference that appears twice in one assistant turn, or None.

	Returns `(found, reference)` rather than a bare string, so no caller can ever decide on the
	truthiness of the value — an empty id is a real collision and the most likely one, and a guard
	written `if collided:` would wave it through.

	Ids are compared EXACTLY: no case-folding and no stripping, because nothing downstream
	normalises either. `has_result` (`:452`), `answers.get(call.id)` (`:282`) and `Question.key` all
	compare raw, so "c1" and "C1" are two answerable calls and must stay two.
	"""
	seen: set[str] = set()
	for id in ids:
		reference = id if isinstance(id, str) and id else NO_CALL_REFERENCE
		if reference in seen:
			return True, reference
		seen.add(reference)
	return None
```
`Iterable` joins the existing `from collections.abc import Generator` import at
`flow/lib/agent.py:9`.

**Changed from v1** (review F1, F2, F14): v1 skipped any non-`str` id, which left two `id=None` calls
passing the check and executing twice — the defect surviving the fix. v1 also returned a bare `str`,
making correctness depend on callers writing `is not None` rather than `if collided`.

### D2 — the turn is refused before any tool runs
**`flow/lib/agent.py:513-527`, `_assistant_message`.** This is the choke point: it has **exactly two
call sites**, `flow/lib/agent.py:334` (`_loop`) and `:396` (`_loop_stream`), and both loops call it
*before* iterating `response.tool_calls` (`:346` and `:411`). One check there covers both loops, with
no duplicated rule and no second pass.

```python
def _assistant_message(response: ChatResponse) -> dict[str, Any]:
	message: dict[str, Any] = {"role": "assistant", "content": response.content}
	if response.tool_calls:
		collided = _indistinguishable_tool_call(call.id for call in response.tool_calls)
		if collided is not None:
			# One question cannot address two actions: both would carry the same key, one answer
			# would resolve both, and the tool would run twice on one approval. Refused here,
			# before the message enters the transcript and before any tool is invoked.
			raise ValueError(_UNANSWERABLE_TURN)
		message["tool_calls"] = [ ... unchanged ... ]
```

Because the raise happens *inside* `_assistant_message`, the `messages.append(...)` at `:334`/`:396`
never runs: **the colliding assistant message never enters the transcript.** Nothing is invoked,
because `_invoke` is only reached at `:347`/`:415`, after the append. This was traced, not assumed:
`_invoke` has exactly two call sites and `_run_tool` exactly three (`:310`, and `:487` reached only
from `_invoke`), and every one is downstream of D2 or D3.

The message is **not model-facing** — it is raised, never returned to the model — but it **is
person-facing** on every path (see D3 and R1), so it is written for that reader:

```python
_UNANSWERABLE_TURN = (
	"Two actions in one reply could not be told apart, so one approval would have answered both. "
	"Nothing was carried out."
)
```

**Changed from v1** (review F6): the reference is no longer interpolated into the sentence. It added
nothing a person can act on, and for the empty/absent case it rendered as `()`.

### D3 — a transcript already carrying one cannot be resumed
**`flow/lib/agent.py:501-510`, inside `_validate_messages`'s `for i, message in enumerate(messages):`
loop, appended after the existing `content`/`tool_calls` check at `:509-510`.**

```python
		if role == "assistant" and isinstance(message.get("tool_calls"), list):
			collided = _indistinguishable_tool_call(
				tc.get("id") for tc in message["tool_calls"] if isinstance(tc, dict)
			)
			if collided is not None:
				raise ValueError(_UNANSWERABLE_TURN)
```

This is what makes the fix complete rather than only forward-looking. `_prepare_resume` calls
`_validate_messages(messages)` at **`flow/lib/agent.py:271`**, so a run that paused *before* this fix
with a colliding transcript is refused at resume instead of double-executing. That is S15's
fail-closed principle applied to the one input S15 did not cover, and it is the only part of this
change that protects a site that already has the bad transcript stored.

**AMENDED by the owner, run 10 (R7).** v2 said `_validate_messages` is also reached from
`_build_initial_messages` (`flow/lib/agent.py:474`), so a caller handing in history with a colliding
turn is refused at the door too, and that "both paths are wanted". That is withdrawn. The replay path
is **not** refused:

- it buys no execution safety — on the `run(list)` path `_loop` only ever invokes calls from the
  CURRENT reply, never from history, and `_pending_calls`/`_prepare_resume` are not reachable from
  there — so refusing it prevents no double write;
- and it is the path a conversation is replayed through on EVERY later message, so one stored
  colliding turn refused every future turn of that session, forever, recoverable only by someone who
  could delete the `Flow Session Message` row.

`_validate_messages` gains `refuse_indistinguishable_calls: bool = True`; `_build_initial_messages`
is the one caller that passes `False`, with the reason in the code. The default stays True so any new
call site is guarded unless it says otherwise. The guarantee is unchanged: two actions in one reply
that cannot be told apart run nothing, on the model's new reply (D2) and at resume (D3).

**Changed from v1** (review F6): v1 used a developer-facing message (`messages[i] has two tool calls
sharing the id …`) on the grounds that "a transcript handed in by a caller is a programming error".
That is true of the `_build_initial_messages` path and false of the other one: `_prepare_resume` is the
ordinary end-user resume, `FlowSession.resume` catches at
`flow/flow/doctype/flow_session/flow_session.py:391-393` and calls `run.mark_failed(str(e))`, and
`mark_failed` writes the text into `run.error` (`flow/flow/doctype/flow_run/flow_run.py:121-122`) —
which is what a person is shown. One sentence, person-readable, on both paths.

### D4 — the evals runner learns to expect a refusal
**`evals/run.py:270-284`.** Measured, not assumed: `run_scenario` wraps `agent.run` in
`try/except Exception` and returns `Result(..., False, [f"the run raised {type(e).__name__}: {e}"])`.
There is **no `expect.raises` key in the runner**. Without D4 a scenario whose correct behaviour is a
refusal can never pass — it would sit red forever as a KNOWN-DEFECT and the record would stay wrong,
the exact state `evals/tests/test_known_defects.py` was built to prevent.

The runner gains one expectation key:

```yaml
expect:
  raises: "could not be told apart"    # a substring of the refusal the run must raise
```

**The logic lives in a pure module-level helper that imports nothing from the engine** (review F4):

```python
def refusal_failures(expect: dict[str, Any], error: BaseException) -> list[str] | None:
	"""Failures for a run that raised, or None when the scenario did not expect a refusal.

	Pure: the exception and the expectation, nothing else. `evals/tests/` runs as plain unittest
	with no platform context (see both test modules' docstrings), so the branch that decides a
	refusal must be reachable without importing the engine.
	"""
```

- `expect.raises` absent → returns `None`; `run_scenario` keeps today's behaviour (the raise is a
  failure with the reason on the row).
- present and a substring of `str(error)` → returns `[]`; the scenario **passes**.
- present and not a substring → returns a failure naming both the expected and the actual text.
- in every case where `raises` is present, `absent_text` is applied to `str(error)` as well, so a
  refusal that named a platform or vendor fails even though `raises` matched (review F5). Without
  this, `absent_text` on a raising scenario checks nothing: `_check_absent_text` runs only over
  questions (`evals/run.py:303`), a paused output (`:306-308`) and a resume reply (`:375`), and the
  `except` branch returns at `:278-284` before all of them.

`run_scenario`'s `except` branch calls the helper and returns `Result(..., not failures, failures,
known_defect=…)` when it is not `None`.

`expect.raises` together with `pauses`/`tool_calls`/`questions`/`after` is refused by `load_scenarios`
as contradictory — a run that raised has no result to check those against.

**D4 does not cover D3.** The answer-case replay has its own catch at `evals/run.py:358-364` and no way
to expect a refusal there, so the resume half of this fix is proved by AT6 only, in Python. That is
accepted rather than hidden (review F7); extending `raises` to answer cases is a separate, later
change and is listed under `S3-next.md`.

`evals/` is this fork's own artifact, not upstream's, so this is ours to extend.

--------------------------------------------------------------------------------------------------
## What it must not change
--------------------------------------------------------------------------------------------------
1. **The four rule-4 functions stay byte-identical.** `_invoke`, `_resolve_confirmation`,
   `_confirmation_question`, `_has_denial`. This spec touches none of them, so
   `flow/tests/test_deny_stops_batch.py:378`
   `test_the_four_functions_are_byte_identical_to_their_reviewed_form` must stay green **with its
   `BASELINE_DIGESTS` literals unedited** (`test_deny_stops_batch.py:360-365`, a `ClassVar` on
   `TestTheLoadBearingFunctionsAreUntouched` at `:346`). The pin hashes by function name
   (`:367-373`) and `:382` asserts the found name set equals the baseline set exactly, so the new
   function must not be named after any of the four. Adding it and widening the `collections.abc`
   import leave all four digests unchanged.
   *(This is a constraint, not an acceptance test — see the note under AT8, review F8.)*
2. **`resume_run`'s answers must not change.** The wire contract is `answers: {question.key: answer}`
   (`flow/api/api.py:44-62`). Unchanged: `Question.key` (`flow/lib/agent.py:74`), `key = call.id`
   (`:349`/`:417`), `answers.get(call.id)` (`:282`), `CONFIRM_ANSWER_OPTIONS = ("Approve", "Deny")`
   (`:42`), `_approval_question_keys` (`:668`), `_resolve_confirmation` (`:307-322`), `_summarize`.
   **No web-app change is required and none is permitted by this spec.** The only new outcome a client
   can see is a refusal on a transcript whose answers could never have been correct.
3. **Every distinguishable turn behaves exactly as today** — one call, many calls with distinct ids,
   one call with no id, gated, ungated, streamed, `auto_approve`, denied batches. Measured at
   `veyqon` over **both** literal forms, with a detection control:

   | form | blocks | carrying ids | duplicates |
   |---|---|---|---|
   | `tool_calls=[…]` keyword-list literals | 26 | 13 | **0** |
   | `{"tool_calls": […]}` dict literals (hand-built transcripts) | 3 | 3 | **0** |
   | entries with no `id` key at all | — | — | **0** |
   | `evals/scenarios/*.yaml` model scripts | 13 files | — | **1** |

   The one YAML duplicate is `evals/scenarios/one_approval_can_execute_two_writes.yaml:25-26`, the
   known-defect scenario. **That is the positive control**: a scanner that does not flag it is broken,
   and "zero in the Python tests" is only a measurement because the same scanner found it.
   *(v1 scanned only the keyword-list form and offered extraction, not detection, as its control —
   review F11. The conclusion was right; the method is restated.)*
4. **The batch execution order is not touched** (rank 2 stays open), and `auto_approve` is not touched
   (rank 1 stays open). In particular `test_ai_agent.py:411`, `:613`, `:714` and
   `test_ai_triggers.py:381` must stay green unmodified. Each was re-read at `veyqon`; none constructs
   a turn this spec would refuse.
5. **No model-facing or person-facing text names the platform, a vendor or a model** (CLAUDE.md rule
   3). The refusal is raised, never returned to the model — but it reaches a person on every path, so
   AT9 checks it as person-facing text and checks D2's and D3's messages both (they are now one
   literal).

--------------------------------------------------------------------------------------------------
## Acceptance tests — each with the mutation that turns it red
--------------------------------------------------------------------------------------------------
New file: **`flow/tests/test_s17_one_approval_one_action.py`**. Every test below is watched failing
before it passes (workflow rule 2); the "mutation" column is the specific edit that must make it red,
and each must be *observed* red, not asserted to be.

**No permission surface.** AT1–AT10b are `UnitTestCase` tests over `flow/lib/agent.py` driven by a fake
model; AT11 is plain `unittest` over a pure helper. Nothing here reads a document, so the
named-non-Administrator-user rule does not apply — stated explicitly rather than left unaddressed.

| # | test | asserts | mutation that turns it red |
|---|---|---|---|
| **AT1** | `test_a_colliding_gated_batch_raises_before_any_tool_runs` | two calls with `id="c1"`, one gated tool; `agent.run` raises. Docstring says plainly that `ran == []` is already true here today, because a gated batch pauses — the discriminating assertion is the raise | delete the `if collided is not None: raise` block in D2 → the run pauses, no raise |
| **AT1b** | `test_a_colliding_ungated_batch_raises_and_neither_call_runs` | **the test that watches the defect on the path being fixed.** Two calls with `id="c1"` to an **ungated** tool; `agent.run` raises and the recorder's `ran == []` | delete D2's raise → the recorder shows the tool ran **twice**, with nobody asked anything. *(New in v2 — review F3. v1 had no forward-path test that could observe a double execution.)* |
| **AT2** | `test_the_colliding_turn_never_enters_the_transcript` | after catching the raise, the agent's message list has **no** assistant message carrying `tool_calls` | move D2's check out of `_assistant_message` into `_loop`, after the `messages.append` at `:334` → the message is present |
| **AT3** | `test_it_raises_identically_in_the_streamed_loop` | the same, driving `agent.run(..., stream=True)` and draining the generator; and that the refusal text is the same literal as the non-streamed one | the same mutation as AT2 (moving the check into `_loop` leaves `_loop_stream` unguarded) → the stream stops raising |
| **AT4** | `test_two_distinct_ids_still_both_execute` | **the positive control.** `id="c1"`/`id="c2"`, both ungated, both run, no raise, two tool messages | make `_indistinguishable_tool_call` return `(True, "x")` unconditionally → this goes red, proving AT1/AT1b are not passing vacuously |
| **AT5** | `test_a_single_call_is_untouched` | the second control: one ungated call runs; one gated call pauses with one question and `options == ["Approve", "Deny"]` | same mutation as AT4 |
| **AT6** | `test_a_stored_colliding_transcript_cannot_be_resumed` | a hand-built transcript with one assistant message carrying two `tool_calls` both `id="c1"` and no `tool` result; `agent.resume(msgs, {"c1": "Approve"})` raises **and the tool did not run**. The fake model supplies a following final turn, so that under the mutation the resume gets past `_prepare_resume` into `_loop` (`:192`) and the observation is the recorder, not an exhausted script | delete D3's block → the resume double-executes and the recorder shows **two** runs (the defect, reproduced) |
| **AT7** | `test_a_stored_transcript_with_distinct_ids_still_resumes` | the control for AT6: two pending calls `c1`/`c2`, answers `{c1: Approve, c2: Deny}`, resolves exactly as today | the same mutation as AT4 *(v1's "delete the `seen` set" mutation is a `NameError` that reddens four tests at once — review F9)* |
| **AT8** | `test_the_four_reviewed_functions_were_not_touched` | imports `TestTheLoadBearingFunctionsAreUntouched` from `flow.tests.test_deny_stops_batch` and re-asserts its `BASELINE_DIGESTS` against the engine on disk | change one character inside `_invoke` → red. **This is a constraint check, not an acceptance test of S17**: it is green before and after this change and no S17 edit can move it, and the existing `test_the_four_functions_are_byte_identical_to_their_reviewed_form` (`:378`) catches the same mutation with its own control at `:386`. Kept only so the constraint is visible in this spec's own file. *(Review F8: v1 imported a module-level name that does not exist and counted this as criterion 8.)* |
| **AT9** | `test_the_refusal_names_no_platform_vendor_or_model` | the raised message from **both** D2 and D3, lower-cased, contains none of `frappe`, `erpnext`, `mariadb`, `openai`, `anthropic`, `gpt-`, `claude`; and the control — that the assertion can fail — by running the same check over a string that does contain one | put `frappe` in the refusal literal → red |
| **AT10** | `test_two_calls_with_no_id_are_refused_like_any_other_collision` | two calls with `id=None`, and separately two with `id=""`, are both refused and neither tool runs — the two shapes a provider actually produces (`flow/lib/model.py:244`, `:185`) | restore v1's `if not isinstance(id, str): continue` skip → the tool runs twice. **Inverted from v1**, which asserted the opposite and pinned the bypass open (review F1) |
| **AT10b** | `test_a_single_call_with_no_id_is_refused_as_well` | **INVERTED by the owner, run 11b (2026-09-23)** — **one** call with `id=None` (and, in `TestAReplyWithNoUsableReferenceIsRefusedBeforeItIsStored`, with `id=""`) is refused before the reply is stored and nothing runs; the sentence raised is `_UNFILEABLE_CALL`, not `_UNANSWERABLE_TURN`. Its old control role is rehomed to AT10c and to `test_the_control_a_usable_reference_still_runs`, which pin that a usable reference still executes. *(v2's row read: "the control for AT10 and for the non-goal: one call with `id=None` is not refused and behaves exactly as today", with the mutation "make `_indistinguishable_tool_call` refuse any non-string id outright → red" — the shipped behaviour, which is why the row had to move rather than stand.)* | delete the `if NO_CALL_REFERENCE in references: raise ValueError(_UNFILEABLE_CALL)` branch from `_assistant_message` → the single call executes and its result is filed under nothing → red |
| **AT10c** | `test_ids_differing_only_by_case_or_whitespace_are_two_answerable_calls` | `"c1"`/`"C1"` and `"c1"`/`"c1 "` both execute; no raise | add `.strip().lower()` to D1's comparison → red. Pins that no normalisation creeps in, since nothing downstream normalises either (review F14) |
| **AT11** | *(in `evals/tests/test_runner.py`)* `test_a_scenario_that_expects_a_refusal_passes_on_it`, `test_a_scenario_that_expects_a_refusal_fails_on_the_wrong_one`, `test_a_raise_with_no_expectation_still_fails`, `test_a_forbidden_word_in_the_refusal_fails_even_when_raises_matched` | D4's four branches, calling `refusal_failures(expect, error)` directly — **no engine import**, which is what lets these run under `python3 -m unittest discover -s evals/tests -t .` as both eval test modules' docstrings require | remove the `expect.get("raises")` branch → the first goes red while the third stays green; remove the `absent_text` application → the fourth goes red *(review F4, F5: v1 said "built on `Result` objects directly", which cannot reach `run_scenario`'s `except` branch at all)* |

**AT1b and AT6 are the two that matter most**, and they are the pair that reproduces the defect end to
end on both paths: AT1b's mutation makes the recorder show two runs in one turn with no approval at
all; AT6's makes it show two runs on one `Approve`. That is CLAUDE.md rule 7 in its test-facing form —
the defect is watched happening before it is watched refused, on each path separately.

**Which gate proves what** (review F4):
- AT1–AT10c: `scripts/run-tests.sh` → `GATE=GREEN`.
- AT11: `python3 -m unittest discover -s evals/tests -t .` (outside the bench gate by design).
- the scenario flip: `evals/run.sh` → `EVALS_GATE`.

--------------------------------------------------------------------------------------------------
## Which existing tests and evals scenarios change state
--------------------------------------------------------------------------------------------------

### `flow/tests/` — **nothing changes state**
See "What it must not change" §3 for the measurement and its control. This is the whole reason this
defect is buildable in the fork: **no upstream test asserts it**, unlike run 7's rank 1
(`test_ai_triggers.py:381`, `test_ai_agent.py:613`) and rank 2 (`test_ai_agent.py:714`, in the
protected `TestAgentConfirmation`).

### `evals/` — one scenario flips, and it needs a human
**`evals/scenarios/one_approval_can_execute_two_writes.yaml`: KNOWN-DEFECT → FIXED.**

`evals/tests/test_known_defects.py::test_a_known_defect_that_started_passing_fails_the_suite` makes a
known defect that starts passing turn `EVALS_GATE` **red**, with "Drop `known_defect` from the
scenario" printed, *because only a person may correct the record*. **The owner has decided this
scenario is rewritten to expect the refusal.** Three human edits, all named here:

1. **Drop the `known_defect:` block** (`:3-8`). The defect is fixed; the record must say so.
2. **Rewrite `expect:` to the refusal contract.** The current block (`:27-38`) asserts **dedup**
   semantics, which the owner has rejected — `pauses: true`, then `answers: {c1: Approve}` →
   `executed: [send_money]`, `output: paid`. Under D2 the run raises, so `pauses: true` fails. The
   replacement, which needs D4:
   ```yaml
   expect:
     raises: "could not be told apart"
     absent_text: [frappe, erpnext, mariadb, openai, anthropic, gpt-, claude]
   ```
   and the whole `after:` block (`:30-37`) goes, taking its `model_script` second turn with it. The
   top-level `model_script` (`:23-26`) keeps its single colliding turn — that is the input under test.
   *(v1 said "`model_script`'s second turn is removed"; the top-level script has only one turn — review
   F16.)* `absent_text` is only meaningful here because D4 applies it to the refusal; see D4.
3. **Correct the stale sentence while there.** The scenario says *"Captured at
   `brain/00-inbox/one-approval-can-execute-two-writes.md`"*. That file **does not exist** — verified
   at `veyqon`: the inbox holds 11 notes and that is not one of them. Replace with a reference to this
   spec.

**These three are human edits to a fork-owned file that the spec authorises; the builder does not make
them unilaterally.** This mirrors S16b, where adding the five `features.json` entries was left as "a
one-line change for a human".

**The other two known-defect scenarios keep their state exactly**
(`auto_approve_turns_every_gate_off`, `ungated_call_beside_a_gated_one` stay KNOWN-DEFECT). Their
scenarios must not be edited by this spec, and each new test's docstring says so rather than letting
coverage be implied.

--------------------------------------------------------------------------------------------------
## Size
--------------------------------------------------------------------------------------------------
| file | change | lines |
|---|---|---|
| `flow/lib/agent.py` | D1 new function + sentinel + refusal literal, D2 five lines in `_assistant_message`, D3 six lines in `_validate_messages`, one import name | **~40** |
| `evals/run.py` | D4 `refusal_failures` helper + the `except` branch calling it + loader contradiction check | **~25** |
| `evals/scenarios/one_approval_can_execute_two_writes.yaml` | rewrite `expect`, drop `known_defect`, fix the stale reference (**human**) | ~15 |
| `evals/tests/test_runner.py` | AT11's four tests | ~45 |
| `flow/tests/test_s17_one_approval_one_action.py` | **new**, AT1–AT10c with their controls | ~280 |
| `brain/10-specs/s17-one-approval-one-action.features.json` | the acceptance contract | ~22 |

**One engine file. Three functions, none of them rule-4 pinned.** A single
`loop/s17-one-approval-one-action` branch from `veyqon`.

--------------------------------------------------------------------------------------------------
## Risk to the web apps' approval flow
--------------------------------------------------------------------------------------------------
**`resume_run` answers must not change, and they do not.** Re-read at `veyqon`:
`flow/api/api.py:44-62`, `Question.key` (`agent.py:74`), `result.key = call.id` (`:349`, `:417`),
`answers.get(call.id)` (`:282`), `CONFIRM_ANSWER_OPTIONS` (`:42`), `_approval_question_keys` (`:668`),
`_resolve_confirmation` (`:307-322`). **All unchanged, byte for byte.** A client that renders questions
and posts `{key: answer}` needs **no change**.

The honest residual risks:

- **R1 — a client sees a new failure where it used to see a pause.** Traced on each path:
  *Non-stream chat*: `flow/flow/doctype/flow_session/flow_session.py:198-205` catches, calls
  `run.mark_failed(str(e))`, commits and **re-raises** — the client gets an error response and the Flow
  Run is `Failed`. *Streaming chat*: `flow/flow/doctype/flow_run/flow_run.py:208-213` marks failed and
  `yield Error(message=str(e))`, so the refusal text reaches the client over the stream. The user's
  message is already persisted by `_persist_turn` (`flow_session.py:224-247`, called at `:177`), so the
  session is intact and the turn can be retried; nothing of the refused turn is stored, because
  persistence happens only in `apply_result`, which is never reached. This is the same shape as any
  other model-call failure, which clients already handle — but it is a new *reason*, and the web apps
  should be checked to confirm they surface the message rather than swallowing it. **A check, not a
  change.**
- **R1a — streamed, the UI draws both tool cards before the refusal.** `_loop_stream` yields
  `ToolStarted` from each `ToolCallBegin` at `agent.py:389-390`, *before* `_assistant_message` at
  `:396`. Nothing executes and nothing persists, so this is cosmetic — but a client will show two
  started cards and then an error, and should not leave them spinning. *(New in v2 — review F15.)*
- **R2 — a paused run that already has a colliding transcript is not merely unresumable: the first
  resume attempt destroys the pause.** `FlowSession.resume` catches at `flow_session.py:391-393` and
  calls `run.mark_failed`, which sets `status="Failed"` and **clears `questions`**
  (`flow_run.py:121-123`). So the Paused run becomes Failed, `_assert_not_blocked`
  (`flow_session.py:541-555`) stops blocking the session, and the person cannot retry — there is no
  orphaned Paused run, and no path to answering the question correctly either. That is the intent (the
  alternative is the double write) and with no such transcript known to exist it is theoretical, but v1
  understated it. *(Review F6, C3.)*
- **R3 — ids colliding across *different* assistant messages are not caught.** D1 is applied per
  assistant turn. `has_result` (`:452`) is transcript-wide, so an id reused in a *later* turn after the
  first was answered would look answered immediately. Deliberately out of scope: a different defect
  with a different fix (a transcript-wide uniqueness rule), and widening this spec would put a new rule
  on every historical transcript the engine loads. **Captured to the inbox, not absorbed here** — the
  owner's answer to v1's open question 3.
- **R4 — the refusal is raised, not returned, so the model is never told.** Chosen (§2): a model with a
  systematic id bug produces repeated hard failures rather than self-correction. Visible beats quiet.
- **R5 — `expect.raises` is a new key in a gate file.** A scenario could be silenced by giving it a
  `raises:` that matches an unrelated error. Mitigated by AT11's second test (a wrong expected string
  must fail), by the loader's contradiction check, and by `absent_text` now applying to the refusal —
  but it is a new way to write a weak scenario and reviewers should know it exists.
- **R6 — D3 has no eval coverage.** The answer-case replay has its own catch (`evals/run.py:358-364`)
  with no way to expect a refusal, so the half of this fix that protects stored transcripts is proved
  by AT6 alone. Accepted; listed for `S3-next.md`. *(New in v2 — review F7.)*

--------------------------------------------------------------------------------------------------
## Upstream
--------------------------------------------------------------------------------------------------
**D1–D3 are upstreamable and should go up.** They fix a defect present on `develop`, touch one upstream
file (`flow/lib/agent.py`), contradict no upstream test (0 duplicates across both literal forms, §3),
and touch none of `brain/`, `.claude/`, `scripts/` or `CLAUDE.md`. Branch from `develop`, engine + the
new test file only, conventional commit (`fix: one approval answers one action`).

**D4 and the scenario rewrite stay in the fork** — `evals/` is ours.

This is the opposite position from run 7's rank 1, which cannot go up as a whole. That asymmetry is a
further reason to do this one first: it is the only one of the three whose engine change can be handed
upstream unmodified.

--------------------------------------------------------------------------------------------------
## Acceptance criteria
--------------------------------------------------------------------------------------------------
See `brain/10-specs/s17-one-approval-one-action.features.json`, to be created with the spec. Proposed
entries (the builder may only flip `passes`):

1. Two tool calls in one response sharing an id raise before any tool is invoked.
2. Two tool calls in one response that carry no usable id — `None` or `""` — are refused the same way,
   and neither runs.
3. ~~A single call carrying no id is unchanged (control for 2).~~ **WITHDRAWN by the owner, run 11b
   (2026-09-23) — see "Non-goals".** The shipped engine refuses it. The entry may not be reworded or
   removed (`features.json` allows only `passes` to be flipped), so entry 3 there is flipped to
   `false`: it is a record that the engine no longer does what that sentence says, which is the
   decision, not a defect. What it used to control for is covered by entries 4, 7 and 8.
4. Ids differing only by case or whitespace are two answerable calls and both execute (control).
5. The colliding assistant message never enters the transcript.
6. The refusal is identical in the streamed loop.
7. A response whose ids are all distinct executes exactly as today (control).
8. A single call, gated or ungated, is unchanged (control).
9. A stored transcript carrying an indistinguishable assistant turn is refused at resume, and the tool
   does not run.
10. A stored transcript with distinct ids resumes exactly as today (control).
11. The refusal, on both the forward and the resume path, names no platform, vendor or model.
12. The evals runner can express an expected refusal, fails a wrong one, still fails an unexpected
    raise, and applies `absent_text` to the refusal text.
13. `resume_run`'s answer contract is unchanged: no web-app change is required.

*(The four reviewed functions being byte-identical is listed under "What it must not change" §1, not
as an acceptance criterion — no S17 change can move that test. Review F8.)*

--------------------------------------------------------------------------------------------------
## Found in the build review — NOT fixed, because fixing it changes this spec (run 9)
--------------------------------------------------------------------------------------------------
**R7 — D3 does not merely block a resume; it makes the whole conversation unusable.**
**Both reviewers found this independently and both rated it MEDIUM. It is the single most important
thing on this page for the owner to decide.**

`_validate_messages` is reached from **two** call sites, and R2 traces only one:
`_prepare_resume` (`agent.py:271`) **and `_build_initial_messages` (`:474`)**. `FlowSession.chat`
replays the entire stored transcript through the second on **every later message**
(`flow_session.py:177` -> `:179` -> `run(list)`), and `_row_to_message` restores the stored
`tool_calls` each time. So one indistinguishable turn anywhere in a session's history refuses:

1. the resume — as R2 says, converting the Paused run to Failed and clearing its questions; then
2. **every subsequent turn of that conversation, forever.** Each attempt creates another Failed run
   and leaves another orphan user message in the transcript. There is no user-reachable recovery —
   only someone who can delete the `Flow Session Message` row.

**Why it matters more than R2 admits.** R2 calls the stored-transcript case theoretical because no
such transcript is known to exist. But AT1b's own path *creates* them: an ungated colliding batch
**completed and was stored** before this fix. And a gateway that never streams ids gives **every**
multi-call turn `id=""` (`model.py:185-188`), so on such a site every session with any multi-tool
turn in its history stops accepting messages the moment this ships. For an already-answered turn the
refusal's own sentence — *"one approval would have answered both"* — is simply false.

**And the `_build_initial_messages` half buys no safety.** On the `run(list)` path `_loop` only ever
invokes calls from the **current** `response.tool_calls` (`:346-347`), never from history;
`_pending_calls`/`_prepare_resume` are not on that path. So the refusal at `:474` prevents no double
write. It only turns a survivable session into a dead one.

**The two candidate fixes, both small:**
- **(a)** fire D3 only for calls with **no `tool` result yet** — the set `_transcript_calls` already
  builds. That is exactly the security-relevant condition: two *pending* colliding calls. A turn
  whose calls are already resolved stops being refused, and sessions stay usable.
- **(b)** move D3 out of `_validate_messages` into `_prepare_resume` only — the sole path that can
  reach `_run_tool` from stored calls. Forward turns stay guarded by D2.

**DECIDED by the owner in run 10: fix (b), narrowed to the two paths where execution happens.**
D3 now fires from `_prepare_resume` only; `_build_initial_messages` passes
`refuse_indistinguishable_calls=False`. Applied and measured in run 10 on
`loop/s17-r7-new-replies-only`. The test that named itself as the one to change was changed
(`TestReplayedHistoryIsNotRefused`), a second test pinning the same withdrawn behaviour (AT6c) was
converted into the sharper pair rather than deleted, and three new tests were watched failing first:
a real `Flow Session` whose stored transcript holds such a turn can still chat, and the S17
guarantee — a new reply, and a resume, both refuse and run nothing — is asserted on the identical
input. Probe: re-adding the history check reddens exactly those four.

**Not done in run 9** (kept for the record). Run 9 read this spec as saying both call sites are
wanted, so narrowing it was a change to an approved spec and belonged to the owner, not to the
builder. The behaviour **as specified** is pinned by
`TestWhatThisRefUsesThatItDidNotHaveTo::test_a_stored_colliding_turn_refuses_every_later_turn_not_only_the_resume`
(since renamed and inverted in run 10 —
`TestReplayedHistoryIsNotRefused::test_a_stored_colliding_turn_no_longer_refuses_every_later_turn`),
whose docstring says it is the test to change if the rule is narrowed.

**R10 — the approval path still carries the blast radius R7 removed from the chat path.**
**Found by the run 10 review. Pinned, not changed: it is the owner's decision.**

`_prepare_resume` validates the WHOLE prompt transcript, not the turn the answers address. So one
indistinguishable turn anywhere in a session's history — *including a fully resolved one* — refuses
every later resume in that session: the run is marked Failed, its questions are cleared, and the
person is shown a sentence that is false for their situation, since nobody was about to approve the
old turn. That session can chat (R7) but can never approve anything again, with no user-reachable
recovery.

**The cost has no matching benefit.** Once either call of a colliding pair has a result,
`_transcript_calls` counts BOTH as answered (§1 step 2), so `_prepare_resume` never iterates them
and nothing from such a turn can execute on resume. Refusing it prevents nothing.

**Candidate fix, for the owner:** scope the resume-time refusal to the calls being resolved — the
pending set `_prepare_resume` already builds — so a collision among PENDING calls is still refused
and a resolved one in history is not. That is the security-relevant condition exactly. It was not
applied in run 10 because it changes the reach of a refusal in an approved spec.

**DECIDED AND APPLIED, run 11 (owner).** The rule is the one R7 settled: *validation refuses what is
about to RUN, never old history.* `_prepare_resume` now calls
`_validate_messages(messages, refuse_indistinguishable_calls=False)` for structure and
`_refuse_indistinguishable_live_turn(messages, answers)` for indistinguishability.

A turn is **live** — and therefore checked — when either is true:
1. it still has a call with no result (the only turns a resume can execute from); or
2. one of its references is a key in `answers` (a person is answering THAT turn).

Condition 2 is not decoration. It is what keeps the nastiest stored shape closed: two colliding
calls of which one already ran leave NOTHING pending, because `_transcript_calls` counts both of a
colliding pair answered — yet an answer carrying that reference would resolve the one that had
already executed. A narrowing written only around the pending set (the candidate fix above, as
worded) would have opened exactly that, and
`test_a_colliding_turn_that_already_has_one_result_is_still_refused` is the test that caught it
mid-build. A reference that is `None` or `""` can never be in `has_result`, so such a turn is
always live and always checked.

Everything else is history and is let through. `TestWhatIsStillRefusedOnTheApprovalPath` now pins
the narrowing itself plus two guarantees behind it: a LIVE collision behind a dirty history is still
refused, and so is a live pair carrying no reference at all.

**CORRECTED the same day, by the run 11 QA adversary.** The first version of condition 1 read "any
call in this turn has no result". An ABANDONED pause is exactly that, for ever — `stop_run` clears a
run's questions but not its messages — so a legacy colliding turn left unanswered still refused every
later approval in that session. That is the whole of the R10 defect, one door further along, and the
narrowing had walked straight past it. Condition 1 is now **the LAST turn holding a call with no
result**, matched positionally, the same way `_live_turn_pending_count` decides what may execute.
Refusing an abandoned turn was buying nothing anyway: since the abandoned-turn branch in
`_prepare_resume`, a call from a turn nobody is resuming is closed out with nothing and can never
execute. Pinned by `test_an_abandoned_colliding_turn_does_not_refuse_a_later_approval_either`,
watched red.

**R8 — two distinct non-string references are refused although they are answerable.** `[1, 2]` as
integers fold to one bucket and the turn is refused, though a set of ids, `answers.get(1)` and
`Question.key` would all tell them apart. `[True, 1]` folding is correct on the merits (they are
equal and hash alike). This is D1's stated rule working as written, fail-closed; pinned by
`TestTheEdgeOfTheFoldIsDeliberate` so it reads as a decision. Raised because it is the one behaviour
this change makes **stricter** than the defect required.

**R9 — `1` beside `"1"` survives the predicate and can still collide at the client.** They are
genuinely distinct in Python, so nothing double-executes server-side; but `Question.key` is
serialised with `asdict`, and a browser building `answers[q.key] = answer` collapses both onto
`"1"`. Contrived, pre-existing, and recorded rather than closed.

## Open questions for the owner
**v1's questions 1 and 2 are closed by the owner's decisions** (refuse, not dedup; the runner gains the
ability to expect a refusal). **Question 3 is closed**: R3 is captured to the inbox, not widened into
this spec. One remains:

1. **Should the streamed path suppress `ToolStarted` until after the turn is admitted?** R1a means a
   client draws two tool cards and then an error. Moving the `ToolCallBegin` announcement after
   `_assistant_message` would fix it but would delay every ordinary tool card until the whole response
   has streamed, which is the thing that announcement exists to avoid. **My recommendation: leave it,
   and note it for the web apps** — it is cosmetic, it only happens on a refused turn, and the fix
   costs every non-refused turn its early card.
