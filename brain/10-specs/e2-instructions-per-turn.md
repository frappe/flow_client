---
type: spec
status: implemented     # draft → approved (HUMAN ONLY) → in-progress → implemented
implemented: 2026-09-19
approved-by: owner pre-approval for unattended run 2026-09-19 — REVIEW BEFORE MERGE
created: 2026-09-19
upstreamable: yes
---
# Spec: E2 — agent instructions reach existing conversations

## Problem
An agent's instructions are stored as the session's system message on the first turn and never
looked at again. Editing a Flow Agent's instructions therefore changes only conversations started
afterwards. Rolling out a revised Agent Q prompt would silently skip every session already open,
and there is no way to tell from the outside which prompt a given conversation is running.

## Goals
- For a session linked to an agent, the system message sent to the model carries that agent's
  CURRENT instructions, on every turn, rebuilt ephemerally.
- Stored messages are not rewritten. The transcript keeps showing what was actually stored.
- Resume uses the current instructions too.

## Non-goals
- Code-only sessions (no agent link). They keep today's behaviour exactly.
- Changing what `_persist_turn` stores, or migrating existing stored system rows.
- Versioning or auditing which instructions a past turn ran under. (Worth its own spec — see Risks.)
- Any change to the write-confirmation path.
- Changing Agent Q's own prompt.

## Current behaviour
<!-- Read 19 Sep 2026 on loop/f3-turn-context @ a05e691. -->
- `flow_session.py` `_persist_turn`: `if not self.messages and self._runtime.instructions:` appends
  one stored system row holding `self._runtime.instructions`, on the FIRST turn only. Nothing ever
  rewrites it.
- `_build_prompt_messages` replays stored rows through `_row_to_message`, then appends the per-turn
  context block and the memory block to `messages[0]` when it is a system message, or inserts a
  system message carrying them when it is not.
- `self._runtime` is rebuilt on every load: `flow/lib/session.py` `_resolve_existing_agent` does
  `frappe.get_doc("Flow Agent", doc.agent).assemble(model=doc.model)` for a doctype session, and
  `assemble` (`flow_agent.py:99-105`) passes `instructions=self.instructions` straight from the
  record. **So the current text is already in hand at prompt-build time** — the staleness is only in
  the stored row being replayed instead.
- `resume` builds through the same `_build_prompt_messages`, so one change covers both paths.
- `ephemeral_prompt_prefix` counts head messages the session never stored, and is what keeps
  `_new_messages_for_session` from re-persisting a stored row.

## Proposed behaviour
In `_build_prompt_messages`, when the session has an agent link, the base text of the system message
is the agent's current instructions rather than the stored row's content. Everything else is
unchanged: the context block and memory block are still appended after it, stored rows are not
touched, and the number of prompt messages is unchanged when a stored system row exists.

## Model-facing impact
The model receives the agent's current instructions instead of a possibly older copy. The text is
the agent author's own and is not generated here, so this spec adds no new model-facing string of
its own and names no platform, vendor or model.

## Acceptance criteria
1. Edit a linked agent's instructions between two turns: the second turn's system message contains
   the new text.
2. After that second turn, the stored first message is byte-identical to what it was — the new text
   is not written into the transcript.
3. The second turn's system message does NOT contain the superseded instructions.
4. A session with no agent link is unaffected: its system message is still the stored row's content.
5. Resume uses the current instructions too.
6. The per-turn context block and the memory block still appear, after the instructions, in that
   order.
7. A linked session whose transcript has no stored system row still gets one carrying the current
   instructions, and that turn persists no extra row (the ephemeral prefix still holds).
8. The number of stored rows after a turn is unchanged from today's behaviour.
9. Upstream's existing suite stays green unmodified, including `TestAgentConfirmation`.

## Risks
- **Auditability.** After this, the stored system row no longer tells you what the model was
  actually sent. That is already true of the memory and context blocks, but instructions are the
  bulk of the prompt. Record it; do not solve it here.
- **A mid-conversation instruction change can contradict what the model already did** earlier in the
  same transcript. That is the intent, but it is a behaviour change users may notice.
- **An agent whose instructions were blanked out of band.** `Flow Agent.instructions` is `reqd: 1`,
  so validation prevents it, but `frappe.db.set_value` does not. Falling back to the stored row is
  safer than sending an empty system message.
- Message-count drift would break `ephemeral_prompt_prefix` and duplicate stored rows. AC7/AC8.
- **The file-injection budget stops matching the prompt.** `_file_injection_budget` measured the
  stored rows, which used to be exactly what the model received. After this change they are not, so
  a long set of instructions would silently buy itself room an attachment then overruns. Found by
  the adversarial pass, measured at ~200 KB of phantom room on a 512 KB window, and fixed by
  `_instructions_delta()`. Note the budget still does not count the per-turn context block or the
  memory block — both predate this spec, both are small, and neither is fixed here.
- **Only the system message at index 0 is replaced.** A stored system row at a later index is
  replayed verbatim, so superseded instructions would reach the model beside the current ones. The
  engine cannot produce that shape — `_persist_turn` writes a system row only into an empty
  transcript and `append_run_messages` stores only assistant and tool output — so it needs a direct
  database write. Recorded rather than coded around.
- **A record-linked session continued with a code `Agent` object runs that object's instructions.**
  `load_session`'s mismatch guard rejects only a *string* agent, so an `Agent` instance passes while
  the session still points at the record. That follows from the runtime being the source of truth
  and is the intended reading, but it is a behaviour change this spec did not originally state.

## Open questions
- Should a session pin the instructions it started with, opt-in? Out of scope; capture if wanted.

## Links
[[00-inbox/instructions-frozen-at-first-turn]] · [[10-specs/f3-turn-context]] ·
[[40-architecture/engine-overview]] · [[MOC]]

---
## Plan
<!-- Filled by /loop-plan. Max 8 tasks. -->

### Findings that shape this plan (read 19 Sep 2026, on loop/f3-turn-context @ a05e691)

**F-1 — the current text is already in hand; nothing new needs fetching.**
`flow/lib/session.py` `_resolve_existing_agent` rebuilds `doc._runtime` on EVERY `load_session`, via
`frappe.get_doc("Flow Agent", doc.agent).assemble(model=doc.model)`, and `assemble`
(`flow_agent.py:99-105`) passes `instructions=self.instructions` straight off the record. So
`self._runtime.instructions` inside `_build_prompt_messages` is already today's text. The fix is to
USE it instead of the replayed stored row — no extra query, no new dependency.

**F-2 — `self.agent` is the right discriminator, not the presence of a runtime.**
`new_session` leaves `Flow Session.agent` empty for a code `Agent` (`session.py:63` returns
`agent_name=None`). `_build_prompt_messages` already uses `self.agent` for exactly this purpose when
it calls `build_memory_block(self.agent, ...)`. Reuse it; do not invent a second test.

**F-3 — message COUNT must not change, or F3's offset breaks.**
`ephemeral_prompt_prefix` returns 1 only when the transcript starts with a system message AND the
stored rows do not. Replacing the CONTENT of an existing system message changes no count, so the
common case is unaffected. The one case that does change a count is F-4.

**F-4 — the insert branch is now reachable for a second reason.**
Today a linked session always has a stored system row (`Flow Agent.instructions` is `reqd: 1`). If it
somehow does not, E2 must still put the current instructions in front — which inserts a message.
`ephemeral_prompt_prefix` already returns 1 for that exact shape, so it is covered; AC7 proves it
rather than assuming it.

**F-5 — order is a contract F3 established.** `<instructions>` then `<context block>` then
`<memory block>`. F3's `test_memory_still_reaches_the_prompt_alongside_the_context` pins the last two.
E2 must not reorder them.

### Tasks

| # | Task | Files | Test | Satisfies AC |
|---|---|---|---|---|
| 1 | **Pin today's behaviour first.** A characterisation test that a LINKED session currently replays the STORED instructions even after the agent record changes. Watched GREEN before the change (it describes today), then inverted in T2 — so it is written to fail after the fix and is rewritten there, not deleted. *(Alternative, preferred: write the AC1 test directly and watch it RED. Do that instead if it is unambiguous — the loop wants red-first, not a test that must later be rewritten.)* | `flow/flow/doctype/flow_session/test_flow_session.py` | AC1 test, watched RED | 1 |
| 2 | **Use the current instructions.** In `_build_prompt_messages`, when `self.agent` and the runtime has instructions, the system message's base text is `self._runtime.instructions`; otherwise the stored row's content, unchanged. Append the context and memory blocks after it exactly as now. | `flow/flow/doctype/flow_session/flow_session.py` | AC1, AC3, AC4, AC6 | 1, 3, 4, 6 |
| 3 | **Prove nothing is rewritten.** End-to-end: two turns with the agent's instructions edited in between, then re-read the session from the database. | `test_flow_session.py` | AC2, AC8 | 2, 8 |
| 4 | **Resume, and the no-stored-system-row shape.** | `test_flow_session.py` | AC5, AC7 | 5, 7 |
| 5 | **Whole-suite green + contract flip.** `MIN_TESTS=<F3 baseline + new>`, `TestAgentConfirmation` untouched, `pre-commit run --files` on each changed file, then flip `passes` in the E2 features file. | `brain/10-specs/e2-instructions-per-turn.features.json` (only `passes`) | `GATE=GREEN` | 9 |

**DO NOT CHANGE:** `flow/lib/agent.py` entirely, including `_invoke`, `_resolve_confirmation`,
`_confirmation_question`, `_has_denial`; `_persist_turn` (stored messages stay as they are — that is
the point of the spec); `ephemeral_prompt_prefix` and `_new_messages_for_session` (F3 owns them);
any doctype JSON; any existing test; the root `features.json` (it belongs to F3); `scripts/`,
`.claude/`, `brain/20-adr/`.

**Files this work may touch (and no others):**
- `flow/flow/doctype/flow_session/flow_session.py`
- `flow/flow/doctype/flow_session/test_flow_session.py`
- `brain/10-specs/e2-instructions-per-turn.md` and its `.features.json`

**Rollback plan:** work stays on `loop/e2-instructions-per-turn`, cut from `loop/f3-turn-context`.
Byte-copy both source files to the scratchpad with recorded sha256 before the first edit; restore by
copying the backup back and re-hashing to the recorded digest.

**Upstream-able:** yes, one commit from `develop`, engine files only — but it sits ON TOP of F3's
`ephemeral_prompt_prefix`, so it must follow F3 upstream, not precede it.

---
## Ship

### What changed
`_build_prompt_messages` now takes the system message's base text from the linked agent record as it
is NOW (`_current_instructions`), instead of replaying the row stored on the first turn. Ephemeral,
exactly like the context and memory blocks: the stored row is never rewritten and the transcript
keeps showing what was stored. Code-driven sessions — which have no record to read and whose
transcript is the only copy of what they were told — keep the stored row verbatim.

### Which test proves which criterion
| AC | Test |
|---|---|
| 1 | `test_edited_instructions_reach_the_next_turn_of_an_open_session` |
| 2 | `test_the_stored_system_message_is_never_rewritten` |
| 3 | same test (asserts the superseded text appears nowhere in the second prompt) |
| 4 | `test_a_code_agent_session_is_unaffected` + `test_a_code_agent_continued_with_different_instructions_keeps_the_stored_ones` |
| 5 | `test_resume_uses_the_current_instructions` |
| 6 | `test_context_and_memory_still_follow_the_instructions_in_that_order` — **but see the note below: this test pins F3's ordering and passes whether the text came from the record or the stored row. It is a real contract test, just not a discriminating proof of E2.** |
| 7 | `test_a_linked_session_with_no_stored_system_row_gets_one_and_stores_no_extra` |
| 8 | the role-list assertions in AC2's and AC7's tests |
| 9 | `MIN_TESTS=618 scripts/run-tests.sh` → `GATE=GREEN`; `flow/lib/` untouched |

Plus `test_an_edit_is_picked_up_on_the_next_load_not_mid_request`, which pins a boundary the spec
did not state: instructions come from the runtime the session was loaded with, so an edit made after
that load is not seen until the session is loaded again. A turn is a request and a request loads the
session, so in practice "the next turn" is when an edit lands.

### How it was verified
- Red first: the four behavioural tests failed on the unchanged code, for the right reasons.
- `MIN_TESTS=618 scripts/run-tests.sh` → `GATE=GREEN` (98 + 522 = 620 reported as 618 floor met).
- Probes, each restored from a byte backup and re-hashed: dropping the code-agent guard reddens
  `test_a_code_agent_continued_with_different_instructions_keeps_the_stored_ones`; writing the
  instructions into the stored row reddens `test_the_stored_system_message_is_never_rewritten`.
- **One probe initially failed to go red**, which found a weak test of mine rather than a code bug:
  a code session's runtime and its stored row hold identical text, so asserting on one proved
  nothing about which was used. Replaced with a test that continues the session using a DIFFERENT
  `Agent` object, which separates them. The probe then reddened it.

### Rollback
Branch `loop/e2-instructions-per-turn`, cut from `loop/f3-turn-context`. Nothing pushed.
`flow/lib/agent.py` untouched; `TestAgentConfirmation` green and unmodified.
