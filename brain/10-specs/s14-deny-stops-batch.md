---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 4 2026-09-20 — REVIEW BEFORE MERGE
created: 2026-09-20
implemented: 2026-09-20
upstreamable: yes
---
# Spec: S14 — a Deny in a batch executes nothing

## Problem
One pause can carry more than one question. When the person answers two of them
`{"k1": "Approve", "k2": "Deny"}`, **`k1`'s tool runs.** The Deny then halts the turn, but the write
it was answered alongside has already happened.

That is not what a person means. Two changes are shown together, as one group, in one question set;
refusing one of them reads as refusing the group. Today it refuses only the future, not the batch.

This is measured, not inferred — see Current behaviour.

## Goals
- If **any** answer in one resume is exactly `"Deny"`, **no pending call executes**.
- The run still halts exactly as a Deny halts it today.
- Every answer the person gave is still recorded against its own call, so the transcript says what
  they decided and the model is told why nothing ran.

## Non-goals
- **Changing what a single answer means.** Only the exact `"Approve"` ever executes anything.
  Options stay exactly `["Approve", "Deny"]`; `allow_other` is unchanged.
- Changing single-question behaviour in any way. It must be byte-identical.
- Changing the free-text (redirect) contract. See the Open question — that is the owner's call.
- Making the resume atomic in any wider sense (partial answer maps, ungated calls in the pausing
  turn). Both are real and both are out of scope — see Risks.

## Current behaviour
Read on `veyqon` @ `0560bdd`, in the function, not the docstring.

- `Agent.resume` (`flow/lib/agent.py:164-166`):
  `messages, _ = self._prepare_resume(messages, answers)` **then** `if _has_denial(answers): return
  self._stopped_result(messages)`. The halt is consulted **after** the resolution, not before.
  `_resume_stream` (`:173-179`) has the same order.
- `_prepare_resume` (`:207-231`) loops over **every** pending call and, for a
  `requires_confirmation` tool, calls `_resolve_confirmation(call, answer)`.
- `_resolve_confirmation` (`:230-246`) runs the tool on exactly `"Approve"`
  (`result = self._run_tool(call)`), returns a `denied` record on exactly `"Deny"`, and a `redirect`
  record on anything else.
- So an Approve anywhere in the map executes, whatever else the map holds. Order does not matter:
  execution follows the transcript's pending order, not the map's.

**Evidence, executed:** `flow/tests/test_spike_two_questions_one_pause.py` @ `83f5620` on
`loop/o1-agent-handoff-spike` —
`test_approve_plus_deny_executes_the_approved_one_and_then_halts_the_run` and
`test_deny_plus_approve_is_the_same_regardless_of_order`, both passing against today's engine, and
both turned RED by run 3's PROBE A (consult `_has_denial` before resolving anything).
ADR-003 lists this as required work item (b) regardless of which agent design is chosen.

## Proposed behaviour
One rule, stated once:

> **When the answers of a resume contain a `"Deny"`, an answer of exactly `"Approve"` does not run
> its tool.** Everything else about the resume is unchanged.

Mechanically, in `_prepare_resume` only:
1. `denied = _has_denial(answers)` is computed **once, before the loop**, from the same function the
   halt already uses — so the halt and the withholding can never disagree.
2. Inside the loop, for a `requires_confirmation` tool whose answer is exactly `"Approve"`, when
   `denied` is true the call resolves to a **withheld** record and `_run_tool` is never reached.
3. Every other path is untouched and calls `_resolve_confirmation` exactly as today: `"Deny"` still
   produces today's `denied` record, free text still produces today's `redirect` record, and a
   pending call on a tool that does not require confirmation still resolves through
   `_serialize_tool_result(answer)`.
4. `resume` and `_resume_stream` keep consulting `_has_denial` after `_prepare_resume` and keep
   returning `_stopped_result`. The halt is not moved, only the execution is withheld.

**The four load-bearing functions are not modified.** `_invoke`, `_resolve_confirmation`,
`_confirmation_question` and `_has_denial` stay **byte-identical** to `veyqon` (CLAUDE.md rule 4).
The change is confined to `_prepare_resume` plus one new module-level helper that only builds a
JSON string. `_has_denial` is *read* by new code; it is not changed.

### What the model is told
The withheld call resolves to:

    {"status": "not_executed",
     "message": "Nothing in this group ran. The user approved this action but denied another action in the same group.",
     "user_answer": "Approve"}

`user_answer` is what makes the person's decision recorded rather than merely absent: the model sees
that this one *was* approved and still did not run, which is different from it never having been
asked. It is a fixed literal, not the value from the answers map, so nothing a caller supplies is
echoed back into the model's context.

## Model-facing impact
One new string, quoted above. It names no platform, vendor or model: no Frappe, Flow, ERPNext,
MariaDB, OpenAI, no model name. It matches the style of the two strings already in
`_resolve_confirmation` ("User denied this tool call.", "Tool not executed.") and, like them, is a
plain literal and not translated — matching the file rather than reformatting it.

## Acceptance criteria
1. `{"k1": "Approve", "k2": "Deny"}` executes **nothing**: the approved tool is never called (proved
   by a tool that records its calls, asserted at zero), and the run halts.
2. `{"k1": "Deny", "k2": "Approve"}` is the same. Neither the order of the map nor the order of the
   calls in the transcript changes it.
3. A Deny anywhere in a batch of three or more withholds **every** Approve in that batch.
4. The withheld call still gets a tool result recorded against its own `tool_call_id`, carrying
   `status: "not_executed"` and the person's own answer.
5. The denied call's own result is byte-identical to today's `denied` record.
6. The run's terminal shape after a mixed batch is what a Deny produces today: `output is None`,
   `iterations == 0`, no further model call.
7. **Single-question behaviour is byte-identical**: a lone `"Approve"` executes, a lone `"Deny"`
   halts and executes nothing, a lone free text redirects and executes nothing.
8. **Approve-only behaviour is unchanged**: `{"k1": "Approve", "k2": "Approve"}` executes both and
   the run continues.
9. **Free-text-only behaviour is unchanged**: `{"k1": "Approve", "k2": "some feedback"}` executes
   the approved one and redirects the other, and the run continues. (See the Open question — this
   is today's behaviour, pinned deliberately so a later decision changes it visibly.)
10. A pending call on a tool that does **not** require confirmation resolves exactly as today, even
    in a denied batch.
11. The streaming resume behaves identically: the same withholding, the same `ToolEnded` events for
    each resolved call, the same `Done` carrying the stopped result.
12. `_invoke`, `_resolve_confirmation`, `_confirmation_question` and `_has_denial` are byte-identical
    to `veyqon`, and upstream's `TestAgentConfirmation` is green and unmodified.

## Risks
- **A resume is still not atomic in every sense.** A partial answers map silently turns the
  unanswered questions into redirects with `user_feedback: null` (run 3, measured). S14 does not
  change that, and a client must still send every key in one resume.
- **An ungated call beside a gated one still executes during the turn that pauses** (run 3's fourth
  fact). S14 is about the *resume*; that write happens before anyone is asked anything. ADR-003's
  required item (a) — every write tool carries `requires_confirmation` — is the fix for that, and it
  is not this spec.
- **A withheld Approve is not a Deny.** The model is told it did not run, not that it was refused.
  If the person means to refuse it they must say so; S14 deliberately does not reinterpret their
  answer.

## Open questions — FOR THE OWNER, not decided here
1. **Should free text stop the batch too?** Today, and after S14, `{"k1": "Approve", "k2": "please
   change the amount"}` **executes k1** and redirects k2, and the run continues to the model.
   The argument that it should stop: a person asking for changes to one of two grouped actions has
   not obviously consented to half of the group going ahead. The argument that it should not: free
   text is a *redirect*, not a refusal — the run continues by design so the model can adjust and
   re-ask, and stopping it would make every clarifying remark cancel everything beside it.
   **AC 9 pins today's behaviour so that whichever way this is decided, the change is visible as a
   test going red rather than as a silent shift.** Not mine to decide.
2. **Should a withheld Approve be re-offered on the next turn?** Today the model simply learns it
   did not run and decides for itself whether to propose it again. Leaving that to the model is the
   smaller change; making the engine re-ask is a feature.

## Links
- [[00-inbox/a-deny-does-not-stop-the-batch]]
- [[20-adr/ADR-003-one-agent-scoped-tools]] — required item (b)
- `flow/tests/test_spike_two_questions_one_pause.py` @ `83f5620` (the measurement)

---
## Plan
<!-- Filled by /loop-plan. -->
| # | Task | Files | Test | Satisfies AC |
|---|---|---|---|---|
| 1 | New test module: multi-question batches through the real `Agent.resume`, red against today's engine | `flow/tests/test_deny_stops_batch.py` (NEW) | itself | 1–11 |
| 2 | Withhold execution in `_prepare_resume` when the batch holds a Deny; new module-level `_withheld_confirmation()` builds the JSON record | `flow/lib/agent.py` | task 1's module | 1–6, 10, 11 |
| 3 | Pin the four load-bearing functions as byte-identical to `veyqon`, with a positive control so the check can fail | `flow/tests/test_deny_stops_batch.py` | itself | 12 |
| 4 | Flip `passes` in the features contract; brain updates | `brain/10-specs/s14-deny-stops-batch.features.json`, `brain/MOC.md`, `brain/changelog.md`, `brain/00-inbox/a-deny-does-not-stop-the-batch.md` | — | — |

**DO NOT CHANGE:** `_invoke`, `_resolve_confirmation`, `_confirmation_question`, `_has_denial` (they
stay byte-identical — CLAUDE.md rule 4) · `flow/tests/test_ai_agent.py`, including
`TestAgentConfirmation` · any other upstream test · `Question.options`, `allow_other` · the
`denied` and `redirect` record shapes · `resume`/`_resume_stream`'s existing
`_has_denial` → `_stopped_result` halt · anything outside `flow/` and `brain/`.

**Rollback plan:** the engine change is one `if` and one helper in `flow/lib/agent.py`. A byte
backup of that file is taken before the edit and its sha256 recorded here; restoring it and deleting
the new test module returns the branch to `veyqon`'s behaviour exactly. Nothing else in the engine
is touched, so there is no migration, no doctype change and no stored data to undo.

---
## Ship

**What changed.** `_prepare_resume` reads `_has_denial(answers)` once, before it resolves anything.
If the group holds a denial, an answer of exactly `"Approve"` resolves to a withheld record and
`_run_tool` is never reached. The run halts exactly as a Deny halts it today, every answer is still
recorded against its own call, and the model is told why nothing ran.

**Why.** A pause can carry more than one question and they are answered as one group. Refusing one
of several actions shown together is refusing all of them — it was not. Measured on
`loop/o1-agent-handoff-spike` @ `83f5620` before it was specified. ADR-003 lists it as required
work item (b) whichever agent design is chosen. See [[00-inbox/a-deny-does-not-stop-the-batch]].

**How it was verified.**
- **Red first:** 18 new tests run against the unmodified engine — `GATE=RED`, `EXIT=1 TESTS_RUN=18
  FAILURE_LINES=7`, `FAILED (failures=5, errors=1)`, log `20260920T114622`. The six red were exactly
  the six S14 tests; the twelve pins were already green.
- **Probes**, each restored by byte copy and proved with `sha256sum -c` → OK:
  A `denied_group = False` → RED on exactly the six S14 tests · B `denied_group = True` → RED on the
  three pins that assert an Approve still executes (so the pins are gates, not comments) ·
  C reword the `denied` record inside `_resolve_confirmation` → RED including the rule-4 pin.
- **Gate:** `MIN_TESTS=670 scripts/run-tests.sh` → **GATE=GREEN**, `EXIT=0 TESTS_RUN=688
  FAILURE_LINES=0`, `LOCK_WAITED_SECONDS=0`.
- **Rule 4:** `_invoke`, `_resolve_confirmation`, `_confirmation_question` and `_has_denial` are
  byte-identical to `veyqon`; `flow/tests/test_ai_agent.py` is unmodified and green
  (`TESTS_RUN=49`, GATE=GREEN). Verified independently by the security reviewer.
- **Three reviewers**, launched in one message, rule 14 observed throughout (no branch switch, no
  tree write until all three reported). One HIGH, fixed and re-verified. Table below.

**Verify table.**

| sev | finding | source | decision |
|---|---|---|---|
| HIGH | the rule-4 pin resolved its baseline with `git show veyqon:…` and `skipTest`ed when that failed — so it silently no-opped in this project's own CI (`ci.yml` checks out one ref, no `veyqon`), in a fresh worktree, and in an installed app dir | code-reviewer | **FIXED** — the pin now carries the four functions' sha256 digests as literals and cannot opt out; two controls added (`test_the_comparison_can_fail`, `test_the_digests_describe_the_engine_that_is_actually_imported`) |
| MED | `brain/MOC.md` and `brain/changelog.md` were in the plan but not yet written | code-reviewer | **FIXED** in this ship commit — they are /loop-ship's own step 2 and the reviewer read the branch mid-loop |
| MED | the pin class names "S14", "veyqon" and CLAUDE.md, which mean nothing upstream | code-reviewer | **ACCEPTED, and recorded in the upstream section below**: the 16 behavioural tests travel; the pin class is fork-only and stays behind |
| LOW | three tests are non-regression pins that would stay green if S14 were reverted | code-reviewer | **DISMISSED with reason**: AC 5 and AC 6 *ask* for "byte-identical to today". They discriminate a buggy S14, not the feature's presence, which is their job. Probes B and C show they can go red |
| LOW | the dict-insertion-order test is low marginal value | code-reviewer | **KEPT**: it is two lines and it is the only thing that would catch an implementation that iterated `answers` instead of `pending`. Cheap tripwire |
| LOW | Approve + free text still executes the approved one | security-auditor | **NOT A DEFECT — the owner's decision.** Spec Open question 1, pinned by a test so a change to it is visible |

**Rollback plan.** The engine change is one `if` inside `_prepare_resume` and one module-level
helper. Restore `flow/lib/agent.py` from a byte backup (sha256 `605bf665…de5b8c` is the shipped
state; `d10a9098…ab7b79` is `veyqon`'s) and delete `flow/tests/test_deny_stops_batch.py`. No
migration, no doctype change, no stored data to undo.

**Upstream.** `upstreamable: yes`, with one split. Cut from `develop`, engine only:
- `flow/lib/agent.py` — clean as written: tabs, matching idiom, no fork references.
- `flow/tests/test_deny_stops_batch.py` — take `TestDenyStopsTheBatch` and
  `TestWhatS14MustNotChange` (16 tests). **Leave `TestTheLoadBearingFunctionsAreUntouched` behind**:
  it is a fork tripwire for CLAUDE.md rule 4 and names things upstream has no notion of. Reword the
  module docstring to drop "S14".
- Conventional commit message: the one on `3ae3267`, unchanged — it was written for an upstream
  reader and names nothing internal.

**The QA adversary's one gap, closed.** All 18 original tests drove `Agent.resume` directly; none
went through the session and API layer a client actually uses. It proved the behaviour holds there
with a throwaway test and deleted it. That test is now permanent —
`TestItHoldsThroughTheWholeStack.test_a_deny_in_the_batch_executes_nothing_through_the_public_resume`
drives `flow.api.api.resume_run` against a record-backed session and reads the stored transcript
back, so a future reshaping of the answers map or the prompt messages cannot quietly undo the
withholding. It was probed: reverting `_prepare_resume` turns it **RED**.

**The QA adversary's mutation results, recorded because two of them are honest negatives.** Six
mutations, each restored by byte copy and verified: `_withheld_confirmation` returning `""` → RED ·
dropping the `requires_confirmation` condition → RED · reverting `_prepare_resume` → RED on exactly
the six S14 tests · moving `denied_group` inside the loop → GREEN (a genuinely equivalent mutant —
`answers` does not change mid-loop) · `is` instead of `==` → GREEN (CPython interns the literal, so
this mutation cannot be detected by any test; the code uses `==`) · `in ("Approve",)` → GREEN
(exactly equivalent). The two GREENs are equivalent mutants, not coverage gaps.
