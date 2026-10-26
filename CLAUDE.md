# VEYQON Flow — the engine behind Agent Q

VEYQON's fork of `frappe/flow_client`, the Frappe app that runs Agent Q's agent loop: the model
calls, the tools, write confirmations, sessions and memory. What we change here is what runs in
production under every Agent Q conversation. See @brain/MOC.md.

## Commands (run from the bench, never from this repo)
- Test (the ONLY accepted green): `scripts/run-tests.sh` · one module: `scripts/run-tests.sh flow.tests.test_session`
- Lint/format a file: `pre-commit run --files <path>` (upstream's own config — never a different formatter)
- Harness self-check: `scripts/doctor.sh`
- Bench: `~/code/flow-bench`, site `flow.localhost`, Frappe v16.31.0. Every shell: `export PATH="$HOME/.local/bin:$PATH"`

## Branches — this matters more than in a normal repo
- `develop` = an exact mirror of upstream. **Never commit to it.** Upstream merges fast-forward here.
- `veyqon` = our line: upstream + our changes + this harness. Never commit to it directly either.
- `loop/<spec-slug>` = where all work happens. Branch from `veyqon`.
- Anything meant for upstream: a separate branch from `develop` carrying ONLY engine code — no
  `brain/`, no `.claude/`, no `scripts/`, no `CLAUDE.md`. Upstream commits use conventional
  commit messages (`feat:`, `fix:` …) — their commitlint enforces it.

## Rules that differ from defaults
1. **bench's exit code is not evidence.** It has exited 0 after a failure here, and Frappe's runner
   exits 0 when it discovers ZERO tests. Green means `scripts/run-tests.sh` printed `GATE=GREEN`.
2. **Tabs, not spaces**, per upstream's `pyproject.toml`/`.editorconfig`. Doctype JSON is 1-space
   indented and — measured 19 Sep 2026 — all 16 doctype JSON files DO end with a newline, despite
   `.editorconfig`. Match the file you are editing; never reformat it. Only `pre-commit`, never a
   formatter with defaults.
3. **Model-facing text never names the platform.** Anything the model reads (system/context blocks,
   tool descriptions, error strings returned to it) must not say Frappe, Flow, ERPNext, MariaDB,
   OpenAI, or any vendor/model name. The product requirement is absolute.
4. **The write-confirmation path is load-bearing.** `flow/lib/agent.py` `_invoke`,
   `_resolve_confirmation`, `_confirmation_question`, `_has_denial`: no change without a spec that
   names it, and upstream's `TestAgentConfirmation` must stay green unmodified.
5. **Per-turn additions to what the model sees are ephemeral.** Put them in
   `FlowSession._build_prompt_messages` (the memory-block pattern) — never in stored messages.
6. **Never read or print `sites/*/site_config.json`** or anything holding a password or key.
7. **Restore by byte backup + sha256, never `git checkout --`.** Probe a test by breaking the code,
   watching it go red, restoring, and proving the restore by hash.

## Workflow — the loop
`/loop-capture` → `/loop-spec` → `/loop-plan` → `/loop-build` → `/loop-verify` → `/loop-ship` → `/loop-retro`
1. No code without an approved spec (`status: approved` is set by a human only).
2. Every test is watched failing before it passes.
3. Touch only the files in the approved plan. Need another? Stop and re-plan.
4. Never edit or delete a test to make it pass; never edit `features.json` except to flip `passes`.
5. The agent that wrote the code never reviews it — `/loop-verify` uses fresh subagents.
   **While reviewers run, the builder does not switch branches or touch the working tree**: the
   reviewers read and test the checked-out files. Test runs are serialised by the gate's lock.
6. Report status as `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`.

## Lessons
<!-- Appended by /loop-retro. Each line is a mistake that must never recur. -->
- A "zero hits" search is only a finding when a positive control in the identical form hits.
- A gate whose failure mode has never been observed is a comment. Prove every gate can go red.
- Read the function before asserting what it does. "The run proceeds" in a docstring did not mean
  "the write executes" — that misreading produced a false security finding (F2, 19 Sep 2026).
- A block that starts with `cd` must stop if the `cd` fails, or it measures the wrong directory.
- A measurement written into a comment carries its date, or it does not go in the comment.
- Switching branches while reviewers were running broke a QA pass and left three mutations untested
  (19 Sep 2026). The tree belongs to the reviewers until they report.
- A "sandboxed" template engine rendered model-controlled text into an approval question and could
  run a database call before anyone approved (E5 v1, 19 Sep 2026). Model-controlled values are data:
  never evaluate them, never let them change the shape of what a person is asked to approve.
