---
type: inbox
status: raw
created: 2026-09-19
---
# The run's prompt length is inferred from shape instead of being declared

**Problem:** `_new_messages_for_session` decides where a run's OUTPUT begins by counting stored rows
and then guessing how many prompt messages were ephemeral, from the transcript's shape. Both call
sites know the real answer exactly and throw it away.

## Context
Raised independently by two reviewers during F3's verify pass (19 Sep 2026): the security auditor as
an audit-trail risk, the code reviewer as an upstream-readability and cost objection. F3's plan
already recorded the alternative and rejected it on blast radius, because it edits `flow/lib/agent.py`
— the file carrying the write-confirmation path, which is on every DO NOT CHANGE list. That makes
this a decision for a human, not a refactor to slip in.

## Evidence
- `flow/flow/doctype/flow_run/flow_run.py` `_new_messages_for_session`:
  `existing = frappe.db.count(...)`, `prefix = ephemeral_prompt_prefix(session, full_transcript)`,
  then `full_transcript[existing + prefix:]`. Two DB queries plus a heuristic per `apply_result`.
- `flow/flow/doctype/flow_session/flow_session.py` `ephemeral_prompt_prefix` decides from shape: the
  transcript starts with a system message AND the first stored row does not.
- The exact value IS known at both call sites: `chat` holds `run_input` and `resume` holds
  `messages`, each the list handed to the runtime.
- **Not reachable today.** Every production `apply_result` receives a `_build_prompt_messages`
  transcript, so shape and reality always agree. Verified by grepping all four call sites
  (`flow_run.py:168`, `flow_run.py:196`, `flow_session.py:198`, `flow_session.py:321`) and by
  confirming `persist_result` has no non-test caller.
- The failure it would cause: a caller passing its own leading system message, on a session whose
  first stored row is not a system message, would have that message silently dropped from the stored
  transcript — a gap in the record, not a duplication.

## Open questions
- Adopt `RunResult.prompt_length` (or an `apply_result(..., prompt_length=)` argument, which needs
  only the two doctype files)? The former is semantically cleaner and deletes both queries; the
  latter avoids `flow/lib/agent.py` entirely. Which?
- If neither: should `ephemeral_prompt_prefix` at least assert the message it is about to skip
  actually looks like the block it thinks it is, so a wrong guess fails loudly instead of silently?
- Offer it upstream with F3's fix, or after?

## Links
[[10-specs/f3-turn-context]] · [[MOC]]
