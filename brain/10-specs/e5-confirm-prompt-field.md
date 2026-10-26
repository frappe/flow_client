---
type: spec
status: superseded     # draft → approved (HUMAN ONLY) → in-progress → implemented
implemented: 2026-09-19
approved-by: owner pre-approval for unattended run 2026-09-19 — REVIEW BEFORE MERGE
created: 2026-09-19
upstreamable: yes
---
# Spec: E5 — plain-language approval questions, configurable on the tool record

> **SUPERSEDED by [[e5-confirm-prompt-field-v2]] on 2026-09-19 (unattended run 2).**
> This version rendered the question with the platform's template engine. Security review found
> three HIGH issues against it — a truncation that hid "and DELETE every invoice", a forged second
> question made with a newline, and `frappe.db.sql` running inside the question before anyone had
> approved anything. Patching those fixed the symptoms; the design was the problem. v2 replaces the
> engine with a single regex substitution. The implementation commits for v1 are kept in history.
>
> Three entries in this spec's features file were flipped to `passes: false` because v2 no longer
> makes those claims — nothing else in the file was touched:
> - **1** — v2 shows the JSON dump ALWAYS, beneath the sentence, so "no JSON dump" is no longer true
>   and is no longer wanted.
> - **4** — nothing on the v2 path can raise, so "a template that raises falls back" has no case
>   left to demonstrate.
> - **6** — an attribute-escape attempt is now shown back as literal text rather than falling back,
>   which is stronger, but it is not what this entry says.
> Entries 2, 3, 5, 7, 8, 9, 10 and 11 still hold in v2 and stay `true`.

## Problem
When a tool needs approval, the person is shown the tool's internal slug and a raw dump of the
model's arguments: "Approve `create_sales_invoice`?" followed by JSON. A plain-English summary is
possible today only for tools defined in Python, because `confirm_prompt` is a callable attribute on
the runtime `Tool`. Every tool defined as a record — which is how the product's own tools are built —
falls back to the JSON dump. Someone approving a write is being asked to authorise something written
in a language they did not choose to learn, which is the worst possible moment for a comprehension gap.

## Goals
- An optional template on the tool record renders the approval question in plain language from that
  call's arguments.
- The first line names the tool the way a person would, using its human title when it has one.
- Rendering can never raise, never execute arbitrary code, and never blocks the approval.

## Non-goals
- **Anything about what executes.** The options stay exactly `["Approve", "Deny"]`, `allow_other` is
  unchanged, and only the exact answer "Approve" runs the tool. This spec changes the question's
  TEXT and nothing else.
- Free-text refusal handling (see [[00-inbox/worded-refusal-reproposes]]).
- Changing the JSON fallback's format.
- Per-user or per-locale templates.

## Current behaviour
<!-- Read 19 Sep 2026. -->
- `flow/lib/agent.py` `_confirmation_question(call, tool)`:
  `Question(prompt=_("Approve `{0}`?\n\n{1}").format(call.name, body), options=["Approve","Deny"],
  allow_other=True)` where `body` is `tool.confirm_prompt(call.arguments)` if set, else
  `json.dumps(call.arguments, indent=2, default=str)`. `call.name` is the SLUG.
- `flow/lib/tool.py` `Tool` dataclass carries `confirm_prompt: Callable | None` and no title.
- `flow/lib/resolver.py` `_build_tool(doc, ...)` is the single place a `Flow Tool` record becomes a
  runtime `Tool`; it already has the record in hand. `_resolve_module` forwards an imported Tool
  object's `confirm_prompt`; `_resolve_script` passes none, so Script tools can never have one.
- `Flow Tool` has `title` (reqd) and `summary` (human-facing) but no approval-question field.

## Proposed behaviour
Add an optional template field to `Flow Tool`. `_build_tool` passes it, and the record's `title`,
onto the runtime `Tool`. `_confirmation_question` then chooses the body in this order:
1. `tool.confirm_prompt` (the code callable) — unchanged precedence, still wins.
2. the record's template, rendered against the call's arguments.
3. the JSON dump — unchanged, and also the fallback whenever (2) fails or renders blank.
The first line uses the tool's title when it has one, else the slug.

## Model-facing impact
**None.** The confirmation question is shown to the person approving, never sent to the model. No
string added here reaches a prompt. The template is authored by a privileged desk user; the values
interpolated into it are the model's own arguments, which is why the spec requires that the arguments
shown are the same dict passed to the tool.

## Acceptance criteria
1. A record-defined tool with a template renders it, with the call's arguments substituted, as the
   question body — no JSON dump.
2. A tool with BOTH a code callable and a record template uses the callable.
3. A tool with neither renders the JSON dump exactly as today.
4. A template that raises falls back to the JSON dump; the run still pauses and the question is
   still asked.
5. A template naming an argument the call did not supply falls back to the JSON dump rather than
   showing a blank where a value belongs.
6. A template cannot execute code or reach out of its sandbox: a template attempting attribute
   escape or filesystem access renders nothing dangerous and falls back.
7. A template whose text resembles a file path is rendered as text, not loaded from disk.
8. The first line uses the tool's human title when it has one, and the slug when it does not.
9. Options are exactly `["Approve", "Deny"]` and `allow_other` is unchanged, for every case above.
10. Only the exact answer "Approve" executes the tool, for a templated tool as for any other.
11. Upstream's `TestAgentConfirmation` stays green and unmodified.

## Risks
- **Misleading the approver.** A careless template could describe a delete as a read. It changes only
  what the question SAYS; the tool that runs is unchanged. Document it on the field.
- **Template injection via the arguments.** Values come from the model. They are interpolated as
  data by the sandboxed renderer, never as template source. Test it.
- **`render_template` treats a single-line string ending in a known extension as a PATH** and loads
  it off disk (`frappe/utils/jinja.py:132,168-176`). AC7 exists for this; `is_path=False` is
  mandatory.
- **A missing name renders as empty rather than raising** under Jinja's default undefined, so AC5
  needs explicit handling, not a bare try/except.
- Requires `bench --site flow.localhost migrate` after the doctype change.

## Open questions
- Should the template also be offered for the model-facing `description`? No — out of scope.

## Links
[[40-architecture/engine-overview]] · [[00-inbox/worded-refusal-reproposes]] · [[MOC]]

---
## Plan
<!-- Filled by /loop-plan. Max 8 tasks. -->

### Findings that shape this plan (read 19 Sep 2026, Frappe v16.31.0)

**F-1 — one chokepoint turns a record into a runtime tool.** `flow/lib/resolver.py` `_build_tool`
is called by both `_resolve_module` and `_resolve_script`, and it already receives `doc`. Threading
`title` and the template through it covers Imported AND Script tools in one place. Positive control
for that claim: grepping `Tool(` in `flow/` finds the dataclass definition, `_build_tool`, and the
`@tool` decorator's `wrap` — no fourth construction site.

**F-2 — the safe renderer, by file:line.** `frappe.utils.safe_exec.safe_render_template`
(`frappe/utils/safe_exec.py:361-363`) is `frappe.render_template(*args, restrict_globals=True)`.
`render_template` (`frappe/utils/jinja.py:111`) compiles through `jinja2.sandbox.SandboxedEnvironment`
(`:124`, `:136`), rejects any template containing `.__` (`:137-138`), and with `restrict_globals=True`
loads `render_safe_globals()` rather than the wider `get_safe_globals()` (`:31-34`). **No `eval`,
no `exec`, no `safe_exec`.** That is the AC6 evidence.

**F-3 — two traps in that renderer.**
1. `:132` `if is_path or guess_is_path(template)` — `guess_is_path` (`:168-176`) returns True for a
   single-line string with a dot whose last segment is html/css/scss/py/md/json/js/xml/txt, and the
   template is then LOADED FROM DISK. `is_path=False` must be passed explicitly. (AC7.)
2. A bad template is reported with `frappe.throw` (a `ValidationError`), not a jinja error
   (`:140-146`), so catching `jinja2.TemplateError` alone is not enough. Catch `Exception`.

**F-4 — a missing argument does not raise.** Jinja's default `Undefined` renders empty. AC5
therefore needs an explicit mechanism, not a try/except: render with `StrictUndefined`, or verify
the template's referenced names against the arguments before rendering. Decide in T2 and test it.

**F-5 — what constrains the first line.** Upstream `flow/tests/test_ai_agent.py:610` asserts
`assertIn("write_file", result.questions[0].prompt)` for a code `@tool`, which has no title. The
slug fallback keeps that green **unmodified** — which is a hard limit, not a preference. `:608`
pins the options and `:609` `allow_other`.

**F-6 — doctype JSON house rules.** 1-space indent, no final newline — **WRONG, corrected in CLAUDE.md 2026-09-19: all 16 doctype JSON files DO end with a newline; match the file**. A new field needs
`bench --site flow.localhost migrate`, which the run's limits allow.

### Tasks

| # | Task | Files | Test | Satisfies AC |
|---|---|---|---|---|
| 1 | **Carry title + template on the runtime tool.** Add `title: str \| None = None` and `confirm_template: str \| None = None` to the `Tool` dataclass (defaults keep every existing construction working), and pass `doc.title` / `doc.confirm_template` from `_build_tool`. | `flow/lib/tool.py`, `flow/lib/resolver.py` | resolver test: a record with a template produces a Tool carrying it; a `@tool`-decorated function still produces one with both fields `None` | 1, 8 |
| 2 | **The doctype field.** Optional `confirm_template` (Small Text) on `Flow Tool`, with help text saying plainly that it changes only what the question SAYS, never what runs. `migrate`. | `flow/flow/doctype/flow_tool/flow_tool.json`, `flow/flow/doctype/flow_tool/flow_tool.py` (auto-generated DF block only) | doctype test: the field persists; a tool without one still validates | 1 |
| 3 | **Render it safely.** A helper that renders the template with `safe_render_template(..., is_path=False)`, returns `None` on ANY exception, on a blank result, or when the template references a name the call did not supply. | `flow/lib/agent.py` (new helper only) | unit tests: substitution works; a raising template returns None; a missing name returns None; `.__` is rejected; a `{{ }}`-free string round-trips | 1, 4, 5, 6 |
| 4 | **Wire the precedence and the first line.** `_confirmation_question` picks callable → template → JSON, and titles the first line with `tool.title or call.name`. **Question TEXT only** — options, `allow_other`, and everything about what executes are untouched. | `flow/lib/agent.py` | tests for all three precedence cases; options are `["Approve","Deny"]` and `allow_other` is True in each; a path-shaped template renders as text | 1, 2, 3, 7, 8, 9 |
| 5 | **Prove the gate did not move.** A templated tool still executes ONLY on the exact "Approve": "Deny" and free text do not run it. | `flow/tests/test_ai_tool.py` or a new test class — NOT `test_ai_agent.py` | end-to-end pause → resume with "Approve"/"Deny"/free text | 10 |
| 6 | **Whole-suite green + contract flip.** `MIN_TESTS=<baseline + new>`, `TestAgentConfirmation` untouched and green, `pre-commit run --files` on each changed file, flip `passes` in the E5 features file. | `brain/10-specs/e5-confirm-prompt-field.features.json` (only `passes`) | `GATE=GREEN` | 11 |

**DO NOT CHANGE:** `_invoke`, `_resolve_confirmation`, `_has_denial` — and within
`_confirmation_question`, ONLY the question text may change: `options` stays exactly
`["Approve", "Deny"]`, `allow_other` stays as it is, and nothing about what executes moves.
Any existing test, especially `flow/tests/test_ai_agent.py::TestAgentConfirmation`. The root
`features.json` (it belongs to F3). `scripts/`, `.claude/`, `brain/20-adr/`.

**Files this work may touch (and no others):**
- `flow/lib/tool.py` · `flow/lib/resolver.py` · `flow/lib/agent.py` (the helper + the question text)
- `flow/flow/doctype/flow_tool/flow_tool.json` · `flow/flow/doctype/flow_tool/flow_tool.py`
- new/extended tests in `flow/tests/` and `flow/flow/doctype/flow_tool/test_flow_tool.py`
- `brain/10-specs/e5-confirm-prompt-field.md` and its `.features.json`

**Rollback plan:** branch `loop/e5-confirm-prompt-field` from `veyqon`. Byte-copy every source file
to the scratchpad with recorded sha256 before the first edit; restore by copying back and re-hashing.
The doctype field is additive and optional, so an unmigrated site is unaffected.

**Upstream-able:** yes, one `feat:` commit from `develop`, engine files only.

---
## Ship

### What changed
A `Flow Tool` record can now carry an **Approval Question** — a short template, filled in from the
call's arguments, shown to the person instead of a JSON dump. The runtime tool also carries the
record's title, so the first line names the tool the way a person would rather than by its slug.

Precedence: the code callable if the tool has one, else the record's template, else the arguments as
they are — which is also the fallback whenever a template cannot be filled in.

### One finding worth the owner's attention
The plan said to pass `is_path=False` so a path-shaped template is not read off the disk. **That is
not sufficient, and the plan was wrong about it.** The renderer's check is
`if is_path or guess_is_path(template)`, so asking for False does not switch the guess off. The
guess fires on any single-line string whose last dotted segment resembles a file extension — which
an ordinary question does: "Delete the report for {{ customer }}.txt". Caught by AC7's test failing.
The fix is to give the template a line break, which is the only condition under which the renderer
guesses at all, and strip it back off the result. Without this, such a template silently fell back
to the JSON dump, and a crafted one could have loaded an app template file off disk.

### How it was verified
- Red first: all 22 tests failed before the implementation existed.
- `MIN_TESTS=608 scripts/run-tests.sh` → `GATE=GREEN` (98 + 510 = 608), 0 deadlocks, solo run.
- Upstream's `TestAgentConfirmation`: unmodified (`git diff veyqon --name-only -- flow/tests/test_ai_agent.py`
  is empty) and all 8 green.
- Only three lines were removed from `flow/lib/agent.py`, all inside `_confirmation_question`: a
  docstring line, an `else:`, and the prompt line. `_invoke`, `_resolve_confirmation` and
  `_has_denial` are untouched, and `options` / `allow_other` are unchanged.
- Probes, each restored from a byte backup and re-hashed: inverting the precedence reddens the
  callable-wins test; removing the missing-argument guard reddens the blank-value test; letting the
  renderer raise reddens four tests including the options-unchanged one.

### Rollback
Branch `loop/e5-confirm-prompt-field`, cut from `veyqon`. Nothing pushed. The doctype field is
additive and optional, so an unmigrated site is unaffected and a tool without a template behaves
exactly as before.

---
## Verify pass — what adversarial review changed

Two reviewers, fresh contexts. Security found **two HIGHs**, both proven live on the bench; code
review found **one HIGH** and several mediums. All fixed here. The approval gate itself was cleared
by both, at byte level: `_invoke`, `_resolve_confirmation`, `_has_denial` identical to `veyqon`,
options and `allow_other` unreachable from a template, `TestAgentConfirmation` unmodified and green.

**HIGH — a value could push the question out of sight.** The rendered body was cut at 2000
characters with no marker. Proven attack: the author writes "Update {{ customer }} and DELETE every
invoice they have." and the model sends a padded customer name; the person approves "Update Acme …"
and the delete runs. Worse, the JSON dump it replaces has no such limit, so this was a regression
*relative to the thing it improved on*. Fixed by capping each **value** instead, so the author's own
words always survive; and if the author's own text is still too long the question is refused rather
than cut, because a half-shown question reads as a whole one.

**HIGH — a value could forge a second question.** Values were interpolated as raw prose, so a model
could open a new line and write a reassuring second question underneath the real one
("NOTE: read-only preview, nothing will be written."). `json.dumps` escaped newlines; this path did
not. Fixed by flattening every value to one line before it enters the sentence.

**HIGH (deploy) — an unmigrated site lost every tool.** `doc.confirm_template` on a `Document`
raises rather than answering None, so on a site running this code before its migration *all* tool
resolution failed, not just templated ones. `doc.get(...)` now.

**MED — the question could read the database.** The template rendered in the platform's restricted
environment, which still carries globals enough to query ignoring permissions and to reach the
network — and it rendered **before** approval, in the approver's session, even when they went on to
refuse. Proven: `{{ frappe.db.sql(...) }}`, `{{ frappe.get_all(...) }}`, `{{ frappe.msgprint(...) }}`
all executed. The globals are now removed from the rendering environment and any name outside the
call's own arguments is refused.

**MED — a traceback reached the person.** A failed render queued a browser message containing
absolute server paths and library names — naming the platform to the user, against rule 3, at the
moment of approval. Rendering from a string rather than through the platform's helper removes that
path entirely.

**MED — good questions were refused.** `{% if note %}` on a declared-but-omitted optional argument
fell back to the JSON dump on every call that omitted it, which is the exact failure this feature
exists to remove. Declared parameters are now allowed and bound to nothing.

**MED — bad questions were shown.** `{{ customer.name }}` on a plain string printed the placeholder
back at the person, braces and all. Undefined is strict now, so it fails into the fallback.

**A correction to this spec's own Ship section above.** It says the `+ "\n"` trick is the fix for
the path-guessing problem. That was true of the first implementation; the renderer no longer goes
near that code path at all, so the trick is gone and the problem with it.

**Tests: 22 → 31.** Review showed 14 of the original 22 survived deleting the feature outright, and
that the "safety" tests asserted only that the JSON fallback appeared — which is also what happens
when the feature is absent. Every refusal test now carries a positive control in the identical form,
and the ones that could not discriminate assert the unit directly. Probed: unflattening values
reddens both HIGH tests; restoring the globals reddens seven; removing the code-callable precedence,
the missing-argument guard and the never-raises guarantee redden their own.
