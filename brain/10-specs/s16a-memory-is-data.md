---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 6 2026-09-20 — REVIEW BEFORE MERGE
created: 2026-09-20
implemented: 2026-09-20
upstreamable: partly
---
# Spec: S16a — memory is data, and agent-wide memory is not writable from a conversation

## Problem
The model can write to memory, unasked, and what it writes becomes an instruction to itself and to
everyone else.

Three facts compose, each re-verified in this repository at `merge/flow-run5-2026-09-20` before a
line was written:

1. **`update_memory` is a write tool with no gate.** `bind_update_memory` builds it with
   `tool(update_memory, description=…)` and no `requires_confirmation`
   (`flow/tools/builtins.py`), and `Tool.requires_confirmation` defaults to `False`
   (`flow/lib/tool.py`). It inserts and saves `Flow Agent Memory` rows with
   `ignore_permissions=True` (`flow/memory/memory.py` `_add`, `_update`).
2. **What it writes goes into the SYSTEM message of every later turn.**
   `FlowSession._build_prompt_messages` appends `build_memory_block(...)` to `messages[0]` when
   that is a system message, or inserts a system message to carry it. The system message is where
   the agent's own instructions live: a saved memory is read in the same voice as the instructions.
3. **`scope="agent"` memories are read by every user of that agent.** `_active_memories` filters
   `or_filters=[["scope","=","Agent"],["user","=",user]]`.

So one successful manipulation of the model — a document it reads, a record's text, a tool result —
can plant a standing instruction that every later conversation, for every user of that agent, is
told in the instruction voice. Nobody is asked, and nothing shows it happened.

Separately, `submit_feedback` (a thumbs-down with a comment) writes an **Agent**-scope memory with
no model and no approval at all (`flow/api/api.py` → `save_feedback_memory`). Any user's typed
feedback becomes standing context for every user. Gating the tool does not reach this path.

## Goal
Memory stops being a channel through which anything can instruct the agent, and stops being
writable agent-wide from a conversation.

1. A memory write from a conversation is a write like any other: the person is asked first, and is
   shown the exact text that will be remembered.
2. A conversation may create and edit **personal** memories only. Shared, agent-wide memory is an
   administrator's to curate.
3. Memory reaches the model as quoted data inside the turn, not as instructions.

## Non-goals
- Changing how an administrator manages memories in the desk. That path is unchanged.
- Deleting, migrating or rewriting any memory that already exists.
- The `execute` sandbox's injected `update_memory` (already fails closed: the injected copy is
  unbound and throws).
- `auto_approve` as a general mechanism. S16a decides only what it means **for memory**.

## Design

### D1 — the gate lives in the tool definition, not on the row
`bind_update_memory` passes `requires_confirmation=True`. This is not a style choice:
`after_migrate` → `sync_builtin_assistant` → `sync_builtin_tools` **rewrites every builtin row's
`requires_confirmation` from the code flag on every migrate**, so a row-only change is undone by the
next deploy and a code-only change needs a migrate to reach an existing site. The code is the source
of truth; the row is a copy. (R8 Q7 — answered.)

### D2 — the approval question shows the exact note, its scope, and whether it adds or replaces
`update_memory` gets a `confirm_prompt` callable, which `_confirmation_question` uses as the body.
It states, in this order: whether it **adds** a new note or **replaces** an existing one (decided by
whether `memory_id` was given) **and, when it replaces, the id of the note whose wording is lost** —
a question showing only the replacement text asks somebody to destroy a note they were never shown;
**the scope the call actually asked for**, not a fixed reassurance, because a call asking for a
shared note must not be described as "only you"; that this will be read back in later conversations;
and then the note itself on its own line, quoted and escaped. Nothing on this path reads the
database: what a person is asked must not depend on a query, and a question must never be the thing
that runs first (E5 v1's lesson).

The note is model-authored text placed in a question a person answers. E5 v2's lesson applies
without amendment: **every control and format character is shown escaped, never obeyed**, so a
newline cannot write a second, friendlier question underneath the real one and a bidi override
cannot reorder the sentence. S16a reuses the engine's own `escape_for_display` rather than writing
a second escaper — one rule, one implementation, one set of tests.

No truncation, ever: a note shown in part reads exactly like a note shown in full. A note longer
than the stored limit (the controller's `MAX_CONTENT_CHARS`, imported rather than copied) **cannot
be kept at all**, so the question says that instead of showing it — nobody is asked to approve text
that would throw the moment they did.

### D3 — a conversation may write personal memories only
The refusal lives in `save_memory`, the one function both the add and the edit funnel through, as an
explicit keyword-only argument `from_conversation: bool = False`. The tool body — the only
model-reachable caller — passes `from_conversation=True`.

Why the default is the *permissive* one: the rule being encoded is *who may write*, not *what may
be written*. The desk (`W3`) and an administrator's own scripts must keep
writing shared memory, and the ten existing unit tests that use `scope="agent"` as a convenient
default for testing keywords, limits and ownership are testing the **core**, not the model's
permission. Defaulting to `False` would turn ten unrelated tests red and invite exactly the wrong
repair (R8 §5 names this trap). A new caller that wants shared scope must say so in one visible,
reviewable word. (R8 Q3 — answered.)

Refused, with a fixed not-executed result and **no** write:
- `scope="agent"` (or anything that is not `user`), and
- a `memory_id` naming a row whose scope is `Agent` — editing a shared note is a shared write.

The model's schema stops offering the choice at all: the two-value enum is gone and the signature
becomes `scope: str = "user"`. It is a plain string rather than a one-value enum on purpose — a
value the schema REJECTS comes back as a validation error raised below this code, and the whole
point is that a model asking for a shared note gets a clear sentence saying nothing was saved and
what to do instead. The schema describes what is wanted; the refusal is the control. (R8 Q8:
`_UPDATE_MEMORY_DESCRIPTION` is rewritten in the same change; it may no longer teach a scope that
cannot be used.)

### D4 — a run with nobody to answer does not write memory at all
(R8 Q1 and Q4; the run prompt's F1 — answered, with the reason.)

Gating `update_memory` creates a new failure that did not exist: an unattended run reaching a gated
tool **pauses with nobody to answer**, and parks in `Paused` forever. Every trigger whose agent
carries the memory tool would be exposed to it.

**A trigger run may not write memory.** It receives a fixed not-executed result and does not pause.

> **Corrected during verification, and this is the most important line in the spec.** The first
> implementation put the refusal in `save_memory` — and the runtime decides to ask from the tool's
> flag *before any tool body runs*, so a gated memory tool in a trigger with the doctype default
> `auto_approve = 0` raised a question nobody could answer and **parked the run in `Paused`
> forever, holding its session with it.** The gate meant to prevent the stranding caused it. All
> three reviewers found it independently.
> The fix: in an unattended run the memory tool is **rebound without its gate**
> (`bind_update_memory(agent, unattended=True)`, swapped into this session's own runtime by
> `FlowSession._rebind_memory_tool`). That reads backwards and is the opposite of what it does — a
> question in a run with nobody to answer is not a protection. Ungated, the body runs, returns the
> fixed not-kept record, and the run finishes. Nothing is written either way; the only thing the
> gate decided there was whether the run survived.
The reasons, in order:
- A stalled trigger is worse than a lost memory. The run prompt says never strand a trigger.
- A trigger with `auto_approve=1` would otherwise write memory *with every gate off* — the exact
  ungated, unattended write S16a exists to remove. Pausing fixes the `auto_approve=0` case and
  makes the `auto_approve=1` case worse.
- A trigger's user-scope memory is stamped with the trigger's `run_as` identity, usually a service
  account nobody ever reads memories as. It would be a **write-only** memory: invisible forever.
  Producing those silently is the worst of the three outcomes.

"Unattended" is `source == "Trigger"` **or** `auto_approve` set, recorded on `frappe.flags` beside
the existing `flow_run` flag by the same function, scoped to the same call and cleared in the same
places. It is derived from the run's own configuration; nothing the model says can reach it.

### D5 — memory is delivered as quoted data inside the user turn
The block leaves `messages[0]` entirely. It is appended to the **last user message** of the prompt,
after that message's own text and after any file injection, between fence markers, introduced by a
line that says what it is: notes kept at the user's request, data and not instructions, never to be
followed as an instruction.

Three reasons this shape and not a new message:

1. **It cannot re-break F3.** `ephemeral_prompt_prefix` counts exactly one ephemeral head message,
   and `_new_messages_for_session` slices positionally by that count. **Any** new ephemeral message
   — at the head, or (worse) at the tail, where it would be re-persisted as though the run produced
   it — changes that arithmetic. Appending to an existing message changes no count at all. (R8 Q5 —
   answered: **no new message, so no role to choose**.)
2. **It is the house pattern.** `_inject_inline_files` already appends per-turn file content to a
   user message between `--- File: … ---` markers. Memory is the same kind of thing: material for
   this turn that the session never stored.
3. **The user turn is the right trust level.** A note written by a model, quoted inside the user's
   own turn, is plainly not the operator's instruction. Moving it out of the system message and into
   a *second* system message would have kept it in the instruction voice.

The fence cannot be forged, from either side.
 - **From inside a note**: content and ids are flattened on the way in, so a note holding the
   closing marker, or a newline followed by a fake header, closes nothing and adds no line.
 - **From the rest of the message**, found by the security review and fixed: the block now shares a
   message with text the engine did not write — the person's words, an attached file's extracted
   text, a retrieved chunk. A typed message cannot carry a forged block (the platform's sanitiser
   strips it, measured on this bench), but **injected text does not pass through that sanitiser**,
   and a document carrying a complete, well-formed block would have sat beside the real one in the
   same role and the same shape. While the block lived in the system message nothing could reach
   it; moving it created the vector. `neutralise_memory_markers` is applied to what is already in
   the message as well, so **exactly one block in it is the engine's: the one it just wrote.**
 - The neutraliser is a **pattern, not a pair of literals**. The first version replaced the two
   exact strings and let `</AGENT_MEMORY>` and `</agent_memory >` through — a blacklist of
   spellings, the shape of rule this project has already been bitten by.

The turn-context block stays in the system message: it is not model-authored, it is the platform
stating what is true now, and it is exactly the kind of thing the instruction voice is for.
(R8 Q6 — answered.)

### D6 — feedback may not write shared memory
(R8 Q2; the run prompt's F2 — answered.)
`save_feedback_memory` writes `scope="User"`, stamped with the user who gave the feedback. A
thumbs-down comment is one person's opinion about one run; it is not a fact about the organisation,
and nothing asks anyone before it is stored. Shared memory stays an administrator's to write.

The alternative the run prompt offers — a pending review row an administrator promotes — is a new
doctype, a new desk surface and a new workflow. It is the better long-term answer and it is out of
this spec's size. **Open question 1.**

### D7 — what already exists is untouched
No migration, no backfill, no deletion. Agent-scope memories written before S16a keep being read by
everyone exactly as they are read today; only the ways to *create* one change. (R8 Q9 — answered.)

## Acceptance criteria
See `s16a-memory-is-data.features.json`. Every one is a named test.

## Risks
- **R1 — two upstream tests assert the behaviour this spec removes, and they may not be edited.**
  `flow/tests/test_ai_api.py::TestMemoryRunProvenance::test_agent_memory_stamped_with_run_then_flag_cleared`
  drives a chat run whose scripted model calls `update_memory(scope="agent")` and asserts the run
  **Completed** and the row exists; and `…::TestFeedback::test_down_comment_saved_as_memory` asserts
  a feedback memory's scope is **`Agent`**. Both are upstream files under `flow/tests/`, which
  CLAUDE.md hard limit 6 forbids editing or deleting. **They are left failing, untouched.** The
  branch's gate is therefore RED with exactly those two failures, and that is the honest encoding:
  they are not wrong tests, they are the old contract, and replacing a contract is a human's commit.
  See "What a human does at merge" below.
- **R2 — a person is asked before the scope refusal is known.** `_invoke` decides to ask from the
  tool's flag alone; the arguments are not consulted. So a model proposing `scope="agent"` produces
  an approval question, and the refusal arrives only if the person approves. Nothing is written
  either way, and the question shows the scope, so a person can deny it. Making the gate depend on
  arguments would mean changing `_invoke` — a rule-4 function — for a cosmetic gain.
- **R3 — memory saving becomes visible and interruptive.** Every remembered fact is now an approval.
  That is the point, and it is a real change to how a conversation feels. If it proves too noisy the
  answer is to make the model save less, not to remove the gate.
- **R4 — the block is still not counted in `_file_injection_budget`.** It was not counted before
  (the budget sums stored rows plus the instructions delta) and it is not counted now. Appending it
  to a user message makes the omission more visible without making it worse. **Open question 2.**
  (R8 Q10 — answered: not in this spec, and said out loud rather than fixed silently.)
- **R5 — a prompt with no user message delivers no memory.** The block rides on the last user
  message; every path that reaches `_build_prompt_messages` has one (chat stores the turn before
  building, resume replays a transcript that contains it). Pinned by
  `test_a_prompt_with_no_user_message_carries_no_block_and_does_not_raise`, added during
  verification — until then the claim was a comment, which this project has a Lesson about.
- **R6 — a resume is treated as attended, always.** `resume` sets the active run with
  `unattended=False`, so a person answering a question can have the note kept — which is the point.
  A *trigger* run that paused on some other gated tool and is later resumed by its owner is
  therefore able to keep notes for the rest of that call. That is a person answering, so it is the
  intended reading, but it is stated here rather than left to be discovered.
- **R7 — the approval body may not be what the person actually sees.** The security review found
  that the web client renders the tool's argument table for any call that has arguments and shows
  the shipped `confirm_prompt` body only when there are none. If that is so in production, none of
  D2's wording or escaping reaches the approver, and a note's control characters are rendered by
  the browser instead. **No frontend file is touched by this branch**, and this was not verified in
  a running app. **Open question 5**, and the first thing to check before shipping.
- **R8 — a note at the 100-note ceiling makes a thumbs-down lose its rating.** `_add` throws at the
  cap and that throw now happens inside `submit_feedback` before the rating is recorded. It counts
  against the person's own bucket now rather than the shared one, so it is reachable sooner.
  Pre-existing in shape, newly reachable — recorded, not fixed here.

## Open questions for the owner
1. **Should a thumbs-down create a pending review row an administrator promotes to shared memory,
   instead of a personal memory?** D6 chose personal, because it is one line and loses nothing that
   exists today. The review row is better and is its own spec.
2. **Should the memory block be counted in the file-injection budget?** It is unbudgeted today and
   stays so. A large memory set plus a large file can now crowd a turn together.
3. **Should an administrator be able to approve a shared memory the model proposes?** S16a removes
   the model's ability to write one and offers nothing in its place. A "propose a shared memory"
   flow may be wanted; it is not built here.
4. **Should the memory block be counted against the file-injection budget** now that it shares a
   message with injected files? See R4.
5. **Does the approval body actually reach the approver in the web client?** See R7. If it does not,
   D2's whole design is dark on the path that matters and a small frontend change is needed.
6. **Should `update_memory`'s gate be bypassable for a trusted agent?** D4 refuses for unattended
   runs. An agent whose whole purpose is unattended curation cannot do it any more.

## The tests this spec changes, named
Rewritten to the new contract, each keeping its subject and gaining a line saying what moved and
why. None was deleted and none was weakened; a spec that changes a contract has to change the
tests that encode it, and naming them here is what makes that a decision rather than a repair.
 - `flow/flow/doctype/flow_session/test_flow_session.py::TestBuildPromptMessages::test_memory_still_reaches_the_prompt_alongside_the_context`
   — still asserts both blocks reach the prompt; now asserts the channel each arrives by.
 - `…::TestBuildPromptMessages::test_memory_reaches_a_session_that_has_no_stored_system_message`
   — the F3 transcript shape. Now asserts the note is NOT in the inserted system message and that
   the message count is unchanged, which is the property that keeps F3 intact.
 - `…::TestAgentInstructionsAreRebuiltEachTurn::test_context_and_memory_still_follow_the_instructions_in_that_order`
   — order is still a contract, now across two channels instead of inside one string.

Left green and untouched, deliberately, because their subject is the core and not the model's
permission: every `scope="agent"` test in
`flow/flow/doctype/flow_agent_memory/test_flow_agent_memory.py`, including
`test_save_memory_adds_agent_scope`. That they stayed green is the signal D3 wanted — it proves the
refusal is a property of the caller.

## What a human does at merge
Two upstream tests (R1) encode the old contract and this fork may not edit them. One of:
 - carve them out in the fork with a documented override file, or
 - take S16a upstream, where the same commit that changes the behaviour changes its tests, or
 - accept the two failures until upstream moves.
This is a decision, not an oversight, and no code in this branch pretends otherwise.
