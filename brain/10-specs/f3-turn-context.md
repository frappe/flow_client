---
type: spec
status: implemented     # draft → approved (HUMAN ONLY) → in-progress → implemented
implemented: 2026-09-19
created: 2026-09-19
upstreamable: yes
---
# Spec: F3 — per-turn context (date, time, time zone, user)

## Problem
The model never knows today's date, the time, the user's time zone, or who it is speaking with. Agent Q's
prompt has to tell it "you do not know today's date — always ask", which costs an extra exchange on
every date-dependent request. A wrong date began the 15 Sep 2026 production incident (a record posted
with a date nobody gave).

## Goals
- Every session turn, the model receives the current date (ISO + weekday), local time, the time zone
  those are expressed in, and the invoking user's full name.
- The information is always current — including on later turns and on resume after a pause.

## Non-goals
- Roles, company, permissions or any other user data. (Separate spec if wanted.)
- Code-only `Agent` runs without a session (`flow/lib/agent.py` `_build_initial_messages`).
- Changing how or when agent instructions are stored (see [[00-inbox/instructions-frozen-at-first-turn]]).
- Any change to the write-confirmation path.
- Changing Agent Q's prompt. That happens only after this is deployed to production.

## Current behaviour
- `flow_session.py:209` `_persist_turn` stores the agent's `instructions` as the system message on the
  first turn only.
- `flow_session.py:319` `_build_prompt_messages` rebuilds what the model is sent each turn and appends
  the memory block to the system message ephemerally (`:354`–`:360`); it inserts a system message if none exists.
- `flow_session.py:302` — `resume` also builds messages through `_build_prompt_messages` (read 19 Sep 2026).
- Nothing anywhere adds the date, time, time zone or user name.

## Proposed behaviour
In `_build_prompt_messages`, alongside the memory block and using the same pattern, append a short
context block to the system message (or insert one if absent). Never stored.

## Model-facing impact
The model sees, e.g.: "Current context: today is Saturday, 2026-09-19. Local time is 10:42
(Europe/Berlin). You are speaking with Thivs Gobinath." It must not name any software, framework,
database, vendor or model.

## Acceptance criteria
1. With time frozen to a known instant, the system message sent to the model on a session turn contains
   that date in ISO format and its weekday name.
2. Two builds in the same session, time frozen to day 1 then to day 2, show day 1 then day 2.
3. The context block is never stored: after a turn, no stored session message contains the frozen date.
4. A session whose agent has no instructions and no memory still sends a system message with the context.
5. The time zone used is the user's own when set, otherwise the system time zone, and its name appears
   in the block; the local time shown is correct for that zone.
6. The block contains the invoking user's full name, and none of "frappe", "flow", "erpnext"
   (case-insensitive).
7. Upstream's existing suite stays green unmodified (in particular `TestAgentConfirmation`).

## Risks
- Time-zone conversion wrong around DST or midnight → wrong date sent confidently. Criterion 5 + QA.
- Token cost: roughly 30 tokens per turn.
- Prompt-injection surface: the user's full name is user-editable text placed in the system role. Quote it
  plainly; security-auditor to review.

## Open questions
- Which Frappe v16.31.0 functions give system tz, user tz and conversion? (Plan must cite file:line.)
- Which time-freezing utility exists in this Frappe version for tests?

## Links
[[40-architecture/engine-overview]] · [[20-adr/ADR-001-fork-flow]]

---
## Plan
<!-- Filled by /loop-plan. Max 8 tasks. -->

### Findings that shape this plan (all read 19 Sep 2026, Frappe v16.31.0)

**F-A — the prompt length is load-bearing, and an inserted system message breaks the transcript.**
`flow_run.py:226` `_new_messages_for_session` computes what a run "produced" **positionally**:
`full_transcript[existing:]`, where `existing = frappe.db.count("Flow Session Message", ...)`.
`Agent._build_initial_messages` (`flow/lib/agent.py:370`) trusts a list caller and returns it as-is, so
`RunResult.messages` is *exactly* the prompt we sent plus what the run appended. The slice is therefore
correct only while `len(_build_prompt_messages()) == stored row count`.
`_build_prompt_messages` already breaks that invariant in one branch: when no system row exists it
*inserts* the memory block at index 0 (`flow_session.py:357-358`), making the prompt one longer — the
slice then starts one message early and **re-persists the last stored row** (the user message, with its
injected file text) as if it were new output. That branch is dead today (`Flow Agent.instructions` is
`reqd: 1` in `flow_agent.json`, so a doctype session always stores a system row; a code agent has no
`agent`, so `build_memory_block` returns `None`). F3 makes the insert branch **live** — AC4 requires a
system message for a session that has no stored one — so this must be fixed before the block is wired
in, or AC3 and AC7 both fail.

**F-B — call sites.** `_build_prompt_messages` is called from exactly two places, `chat` (`:166`) and
`resume` (`:301`), plus `test_flow_session.py:282,305,315`. Positive control for that grep form:
`build_memory_block` in the identical command hit 9 lines. Both call sites funnel into
`run.apply_result(result)` on the same in-memory run (sync at `:190`/`:311`, streamed via
`stream_with_persistence` → `flow_run.py:196`), so one fix covers both.

**F-C — the empty-transcript guard.** `resume` throws "no transcript to resume from" when
`_build_prompt_messages()` is empty (`:302-303`). A block added unconditionally would make that list
never empty and silently disable the guard. The builder must return early on a session with no rows.

**F-D — `_row_to_message` (`:447`) returns fresh dicts**, so augmenting `messages[0]["content"]` cannot
write through to a stored child row. AC3 holds structurally, but is still proven end-to-end in T4.

**F-E — weekday name is deterministic.** No `setlocale` call exists in this app or in Frappe (positive
control: the identical grep form for `get_system_timezone` hit 3 lines), so `strftime("%A")` runs under
the C locale and yields English names.

### Answers to the spec's open questions (file:line)

| Need | Function | Where |
|---|---|---|
| System time zone | `get_system_timezone()` | `frappe/utils/data.py:388` (falls back to `Asia/Kolkata`) |
| User time zone | `User.time_zone` field | `frappe/core/doctype/user/user.json:214`; "user or system" precedent at `frappe/website/utils.py:196-198` |
| Now, in a zone | `get_datetime_in_timezone(tz)` | `frappe/utils/data.py:403` (tz-aware; freezegun-patchable — it calls `datetime.now(UTC)`) |
| Zone conversion | `convert_utc_to_timezone()` | `frappe/utils/data.py:393` — **swallows `ZoneInfoNotFoundError` and returns the UTC time unchanged**, so an invalid `User.time_zone` would be labelled with a zone it is not in. Hence explicit validation in T2. |
| User full name | `get_fullname()` | `frappe/utils/__init__.py:59` — falls back to the user id (an email) when first/last are empty |
| Freeze time in tests | `self.freeze_time(...)` | `frappe/tests/classes/context_managers.py:26-44` (freezegun; a naive string is read as system-tz) |
| Set system tz in tests | `self.change_settings("System Settings", time_zone=...)` | `frappe/tests/classes/context_managers.py:76-78` |
| Act as another user | `self.set_user(...)` | `frappe/tests/classes/context_managers.py:47-56` |

### Tasks

| # | Task | Files | Test | Satisfies AC |
|---|---|---|---|---|
| 1 | **Fix the positional-delta bug first (F-A).** Add `ephemeral_prompt_prefix(messages) -> int` to `flow_session.py` — the number of prompt messages with no stored counterpart (1 when the transcript has no system row of its own, else 0) — and have `_new_messages_for_session` offset by it. Written and watched RED before the fix, by feeding `apply_result` a transcript whose first element is an unstored system message. | `flow/flow/doctype/flow_session/flow_session.py`, `flow/flow/doctype/flow_run/flow_run.py`, `flow/flow/doctype/flow_run/test_flow_run.py` | `test_flow_run.py`: a session with one stored user row + a result whose messages are `[ephemeral system, that user row, assistant]` persists **two** rows total, not three (no duplicated user row). | 3, 7 (prerequisite for 4) |
| 2 | **Build the block.** Module-level `build_turn_context_block() -> str` in `flow_session.py`: resolves the zone (`User.time_zone` via `frappe.db.get_value`, else `get_system_timezone()`; invalid zone → system zone, never a mislabelled time), formats ISO date + `%A` weekday + `HH:MM` + zone name via `get_datetime_in_timezone`, and appends the full name from `get_fullname()` — whitespace-collapsed and length-capped, quoted plainly as data (injection surface, spec Risks). No software, vendor, or model name in the emitted text. | `flow/flow/doctype/flow_session/flow_session.py`, `flow/flow/doctype/flow_session/test_flow_session.py` | New `TestTurnContextBlock`: (a) user tz set → that zone's name and its correct local time; (b) user tz empty → system zone; (c) invalid user tz → system zone, and the time matches the system zone; (d) block contains the full name and none of "frappe"/"flow"/"erpnext" (case-insensitive); (e) a name containing a newline is flattened. | 5, 6 |
| 3 | **Wire it in, ephemerally.** In `_build_prompt_messages`, return early when there are no stored rows (F-C), then collect `[context_block, memory_block]` and either append them to an existing system message or insert one system message carrying them — same pattern as the memory block, never stored. | `flow/flow/doctype/flow_session/flow_session.py`, `flow/flow/doctype/flow_session/test_flow_session.py` | `TestBuildPromptMessages`: (a) with time frozen to a known instant, the system message contains that ISO date and its weekday; (b) two builds on one session, frozen to day 1 then day 2, show day 1 then day 2; (c) a session with no instructions and no memory still yields a `system` message carrying the context; (d) a session with instructions keeps them **and** gains the context; (e) an empty transcript still builds to `[]` (resume's guard intact). | 1, 2, 4 |
| 4 | **Prove it is never stored, end to end.** A full `chat()` turn with a mocked `Model.chat`, time frozen, then re-read the session from the database. | `flow/flow/doctype/flow_session/test_flow_session.py` | After the turn: no stored `Flow Session Message` content contains the frozen date or the user's name-block text; the stored rows are exactly system?/user/assistant with no duplicate; the same assertions on a second turn. | 3, 4 |
| 5 | **Whole-suite green + contract flip.** `scripts/run-tests.sh` with `MIN_TESTS` set to the pre-change count; `TestAgentConfirmation` untouched and green; `pre-commit run --files` on each changed file. Then flip `passes` in `features.json` (only that key). | `features.json` (only `passes`) | `scripts/run-tests.sh` prints `GATE=GREEN`; record the log path and the test count in the build notes. | 7 (and re-confirms 1-6) |

### Decision needed from the human (T1 approach)

I recommend the **derived-offset** fix above: stateless, recomputed from the transcript, nothing to
thread between objects, and it documents the invariant where the invariant is created. The alternative
is to add `prompt_length` to `RunResult` and slice by it — semantically purer ("everything after the
prompt is output") and it would delete the DB count entirely, but it edits `flow/lib/agent.py`, the file
that carries the write-confirmation path, in three places (`run`, `resume`, `_stopped_result`). I chose
the smaller blast radius. **If you prefer the `RunResult.prompt_length` route, say so and I re-plan —
it changes the DO NOT CHANGE list.**

**DO NOT CHANGE:** `flow/lib/agent.py` entirely — including the confirmation functions (`_invoke`,
`_resolve_confirmation`, `_confirmation_question`, `_has_denial`); `_persist_turn` (stored messages are
untouched — the block is ephemeral only); any doctype JSON; any existing test (upstream's
`TestAgentConfirmation` must stay green unmodified); `features.json` descriptions (only `passes` flips);
`scripts/`, `.claude/`, `brain/20-adr/`. Agent Q's own prompt is out of scope (spec non-goal).

**Files this work may touch (and no others):**
- `flow/flow/doctype/flow_session/flow_session.py`
- `flow/flow/doctype/flow_run/flow_run.py`
- `flow/flow/doctype/flow_session/test_flow_session.py`
- `flow/flow/doctype/flow_run/test_flow_run.py`
- `features.json` (`passes` only)

**Rollback plan:** work stays on `loop/f3-turn-context` (branched from `veyqon`); nothing is committed to
`veyqon` or `develop`. Before the first edit, byte-copy each of the four source files to
`/tmp/claude-1000/.../f3-backup/` and record `sha256sum`. Restore = copy the backup back and prove the
restore by re-hashing to the recorded digest — never `git checkout --`. If T1 cannot be made green, stop
before T3: the context block must not be wired in while the delta is positional, because that corrupts
stored transcripts.

**Upstream-able as-is:** yes, as two commits on a branch cut from `develop`, engine files only (no
`brain/`, `.claude/`, `scripts/`, `CLAUDE.md`): `fix: persist only the messages a run produced` (T1) and
`feat: give the model the current date, time, zone and user each turn` (T2-T4).

**Known limitation to record, not solve here:** on a trigger-sourced run the "invoking user" is whoever
the scheduler runs as (often Administrator), so the name in the block is that account. Out of scope per
the spec's non-goals; worth an inbox item if it matters.

**Cost check:** the block is one short paragraph on the system message, ~30 tokens per turn, matching the
spec's estimate.

---
## Ship

### What changed
Two things, in one place each.

**1. Every prompt now carries the turn's context.** `build_turn_context_block()` in
`flow_session.py` emits one line — weekday + ISO date, 24-hour local time, the IANA zone that time is
expressed in, and the name of the person being spoken with. `_build_prompt_messages` appends it to
the system message (or carries it on a system message that exists only for this prompt), in the same
ephemeral way the memory block already worked: stored rows are never touched, so a session left open
for days reports today rather than the day it started. Resume goes through the same builder.

**2. The transcript delta stopped being a bare positional slice.** What a run "produced" was
`full_transcript[stored_row_count:]`, which is only correct while the prompt has exactly one message
per stored row. Adding an unstored system message broke that and re-persisted the last stored row as
run output. `ephemeral_prompt_prefix()` derives how many head messages the session never stored, and
`_new_messages_for_session` offsets by it.

### Why
Spec [[10-specs/f3-turn-context]] · branch model [[20-adr/ADR-001-fork-flow]].
A wrong date began the 15 Sep 2026 production incident. Agent Q's prompt currently has to tell the
model it does not know the date, which costs an exchange on every date-dependent request.

### How it was verified
- `MIN_TESTS=604 scripts/run-tests.sh` → `GATE=GREEN` (98 unit + 506 integration = 604).
- Probed both directions. Disabling the ephemeral prefix re-persists the user row
  (`['user','user','assistant']`). Making the block non-ephemeral trips three assertions, the
  sharpest being `assertEqual(rows[0].content, "be terse")` — the context text found in a stored row.
  Restored from byte backups, verified with `sha256sum -c`.
- `/loop-verify` with three fresh reviewers. See the verify table in the run log.
- `pre-commit run --files` on every changed file.

### Rollback
Work is confined to `loop/f3-turn-context`, cut from `veyqon`. Nothing is committed to `veyqon` or
`develop`, nothing pushed. To undo: delete the branch. `flow/lib/agent.py` is untouched, so the
write-confirmation path cannot have moved.
