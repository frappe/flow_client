---
type: inbox
status: raw
created: 2026-09-19
---
# Trigger-sourced runs tell the model it is speaking with the scheduler's account

**Problem:** The per-turn context block says `You are speaking with "<name>"` using the *session
user*. On a trigger-sourced run that user is the trigger's run identity, not a person — so the model
is told it is talking to "Administrator" (or a service account) when in fact nobody is there.

## Context
Found while building F3 ([[10-specs/f3-turn-context]]); explicitly out of F3's scope (its non-goals
exclude anything about who the invoking user is beyond the full name). Two distinct problems hide
here and they may want different answers:
1. The name is *wrong* — it is the automation's identity, not a human's.
2. There may be **no one to speak to at all**. A trigger run has no interlocutor, so "You are
   speaking with …" is a false premise the model may act on (e.g. offering to ask a question).

## Evidence
- `flow/triggers/triggers.py:74-75` — `fire()` does `original_user = frappe.session.user` then
  `frappe.set_user(t.run_as or t.owner)` for the whole run, restoring at `:98`.
  `_passes_condition` does the same at `:118-123`.
- `flow/flow/doctype/flow_session/flow_session.py` `build_turn_context_block()` reads the name via
  `get_fullname()`, which resolves against `frappe.session.user` — i.e. the run-as identity.
- `Flow Run` already records `source` and `trigger` (`flow_run.py:124,136`), so the run *knows* it
  was trigger-sourced; the block just doesn't consult it.
- Read 19 Sep 2026 on `loop/f3-turn-context` @ a05e691.

## Open questions
- For a trigger run, should the block (a) omit the "speaking with" sentence entirely, (b) say the run
  is unattended and describe the triggering record instead, or (c) name the record's owner as the
  person the outcome is for?
- Does the date/time/zone half of the block still make sense for a trigger run? (Probably yes — a
  scheduled run still needs today's date. Only the *person* half is wrong.)
- Where would the decision live: in `build_turn_context_block()` (which would then need the run), or
  in the caller that already knows the source?
- Same question for any other run source that is not a live chat.

## Links
[[10-specs/f3-turn-context]] · [[MOC]]
