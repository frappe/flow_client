---
type: architecture
measured: 2026-09-19 against upstream 4a3189b
---
# Engine overview — how one Agent Q turn flows

Line numbers are upstream `4a3189b`, read 19 Sep 2026. Re-check before relying on them after an upstream merge.

1. **Entry.** `flow/api/api.py:21` `start_run(input, agent, session, model, attachments, stream)` —
   first parameter is `input`; blank input throws. `resume_run` (`api.py:44`) checks
   `assert_run_owner(run)` and that the run is `Paused`.
2. **Session turn.** `FlowSession.chat` (`flow_session.py:129`). On the first turn `_persist_turn`
   (`:209`) **stores the agent's instructions as the system message** — later edits to the agent's
   instructions do not reach existing sessions (see [[00-inbox/instructions-frozen-at-first-turn]]).
3. **What the model is sent.** `_build_prompt_messages` (`:319`) rebuilds the transcript every turn and
   adds **ephemeral** augmentation that is never stored: inline files, retrieved chunks, and the agent's
   memory block appended to the system message (`:354`). Resume also goes through it (`:302`).
   This is the extension point for per-turn context.
4. **Agent loop.** `flow/lib/agent.py`. Code-only runs build `[system, user]` in
   `_build_initial_messages` (`:370`), appending `instructions` raw — no templating.
5. **Tools and the write gate.** `_invoke` (`:382`): a `requires_confirmation` tool returns a
   confirmation question and the run pauses (unless `auto_approve`, which only a Flow Trigger sets).
   On resume, `_resolve_confirmation` (`:212`): **only the exact answer "Approve" executes the tool**;
   "Deny" records a denial and stops the run (`_has_denial`, `:449`); any other text is returned to the
   model as a redirect with "Tool not executed". Upstream test
   `test_free_text_answer_redirects_to_llm_with_feedback` asserts the tool never runs on free text.
6. **Desk panel.** `flow/hooks.py:26` injects Flow's own chat panel into every desk page.

[[MOC]]
