---
type: spec
status: implemented     # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 2 2026-09-19 — REVIEW BEFORE MERGE
created: 2026-09-19
implemented: 2026-09-19
supersedes: e5-confirm-prompt-field
upstreamable: yes
---
# Spec: E5 v2 — an approval question a caller cannot steer

## Why there is a v2
[[e5-confirm-prompt-field|E5 v1]] rendered the administrator's approval question with the platform's
own template engine. Security review found three HIGH issues against it, and all three are the same
mistake seen three times: **a general template engine in the approval path**.
1. The body was cut at a fixed length with no marker, so a long enough argument value pushed
   "and DELETE every invoice" off the end of the sentence.
2. A value containing a newline opened a line of its own and wrote a second, friendlier question
   underneath the real one.
3. The engine's environment reached the database: `{{ frappe.db.sql(...) }}` ran inside the
   question — before anyone had approved anything, and even if they went on to refuse.

v1 was patched: values were flattened and capped, and the engine's globals were stripped. That fixed
the symptoms. It did not fix the design. An engine that can evaluate is an engine someone can steer,
and the thing being steered is what a person sees at the moment they authorise a write. The owner's
original spec allowed "the platform's sandboxed templating" and that permission was wrong.

## Goals
- The question is **substituted, not evaluated**. There is no engine on this path at all.
- A value chosen by the model can never change the SHAPE of what is asked — only fill a slot.
- The exact arguments that will execute are shown every time, whatever the sentence says.
- Rendering cannot raise, cannot read anything, and can never stop a person being asked.

## Non-goals
- **Anything about what executes.** Options stay exactly `["Approve", "Deny"]`, `allow_other` is
  unchanged, only the exact answer "Approve" runs the tool. Wording only.
- Changing the JSON fallback's format.
- Expressions, conditionals or loops in the field. Their absence is the feature.

## Proposed behaviour (the design is fixed; it is not open to substitution)

### The grammar
The field holds plain text. `{argument_name}` is replaced by the argument of that name. That is the
whole grammar. The substitution is one regex and nothing else:

    CONFIRM_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]{0,63})\}")

There are no expressions, filters, attribute access, indexing, loops or conditionals. No jinja, no
`str.format`, no `frappe.render_template`, no `safe_eval` anywhere on this path.

Anything that is not exactly that shape is literal text and stays visible: `{{ amount }}`,
`{amount|upper}`, `{amount.__class__}`, `{amount[0]}`, `{% if %}`, `{0}`, `{amount!r}`,
`{amount:>20}`, `{AMOUNT}`. A reader who writes one of those sees their own words back, which is the
correct feedback.

### Values
Every substituted value is shown **verbatim, wrapped in quotes**, with every control and format
character (Unicode categories Cc and Cf, bidi overrides included) printed as an escape — `\n`,
`\r`, `\t`, `\uXXXX` — never interpreted. The backslash and the double quote are escaped too:
without that, `\n` in the output would be ambiguous between a real line break and those two
characters, and a quote inside a value could close the pair holding it. The escaping is injective,
so the reader can always tell exactly what the value was. **This is a deliberate departure from
"verbatim" and the owner should confirm it.**

### No silent truncation, ever
Nothing is ever shortened. The whole sentence is abandoned — and the question falls back to today's
JSON dump — if any of these hold:
- a substituted value is longer than 200 characters once escaped (escaping only lengthens, so this
  single cap also refuses any raw value over 200);
- the sentence names an argument the call did not supply;
- the named argument is not a single value (`None`, a list or an object);
- the finished sentence is longer than 2000 characters.
A question showing part of a value reads exactly like one showing all of it, and the part left out
is the part someone needed to see.

### The arguments are always shown
Below the plain-language line, the question **always** shows the exact arguments that will execute,
in today's JSON format. An administrator's wording is never the only thing a person sees, so a
sentence reading "Read the invoices" over a call that deletes them cannot mislead anyone. This rules
out the misleading question as a CLASS, rather than trying to detect one.

**The one exception, and it is deliberate:** the code attribute `confirm_prompt` still wins when
present and the arguments are NOT appended under it. `confirm_prompt` is code, written and reviewed
alongside the tool, not data on a record — and upstream's own
`test_confirm_prompt_renders_plain_english_body` asserts that the argument shape does not appear
beneath it. Appending there would edit an upstream test to make our feature fit, which rule 6
forbids and which would be the wrong trade anyway. **Owner: this is the judgement call to check first.**

### Reads nothing
Rendering touches `template` and `arguments` and nothing else — no record, no session, no database,
no disk — and cannot raise.

### The first line
Uses the tool's human title when it has one, else the slug, as in v1. The title is a person's words
too and is flattened and escaped the same way, so it cannot open a line of its own.

## Model-facing impact
**None.** The confirmation question is shown to the person approving and is never sent to the model.

## Acceptance criteria
See `e5-confirm-prompt-field-v2.features.json`. Every attack found against v1 is its own named test.

## Files this work may touch
- `flow/lib/agent.py` — the question builder and its three helpers, and nothing else in the file.
- `flow/lib/tool.py`, `flow/lib/resolver.py` — carrying `title` and `confirm_template` through.
- `flow/flow/doctype/flow_tool/flow_tool.{py,json}` — the field and its save-time length cap.
- `flow/tests/test_ai_confirm_template.py` — ours, from v1; rewritten here.
- `brain/` and this spec's own features file.

## DO NOT CHANGE
- `_invoke`, `_resolve_confirmation`, `_has_denial` in `flow/lib/agent.py`.
- `options`, `allow_other`, and which answer executes.
- Any test under `flow/tests/` that exists on `veyqon` — `TestAgentConfirmation` above all.
- The JSON dump's format.
- Anything under `frontend/` (see the Open questions).

## Risks
- **The sentence now costs a line more than the arguments alone.** Accepted: the arguments were
  always the ground truth and are now always present.
- **A lowercase-only placeholder grammar** means `{Customer}` silently reads as literal text rather
  than erroring. Chosen over erroring because a visible `{Customer}` in the question tells the author
  exactly what is wrong, and an error at approval time would not.
- **An administrator can still write a sentence that reads oddly.** They cannot write one that
  hides what executes.
- **Combining marks (category Mn) are not escaped**, so a value can stack diacritics over the text
  beside it. Bounded by the 200-character cap — about 150 marks fit, 250 abandons the sentence — and
  it cannot move the cursor or reorder anything. Measured during verify, accepted, not fixed.
- **The 1000-character save cap runs in `validate()`**, so `frappe.db.set_value` or a fixture import
  goes round it. The enforceable bound is the render-time 2000-character cap, which holds regardless
  of what is stored. Writing a tool record is System Manager-only, so this is hardening, not a
  boundary.

## Open questions for the owner
1. The backslash/quote escaping above — "verbatim" versus unambiguous. I chose unambiguous.
2. Whether `confirm_prompt` should also carry the arguments beneath it. That requires changing an
   upstream test, so it is not something this run can decide.
3. Whether the 200-character value cap is the right number. It is a judgement, not a measurement.
4. **The sentence never reaches the person in the bundled client.** `ConfirmCard.vue` discards
   `question.prompt` for tool confirmations and builds its own title from the slug. E5 is engine-only
   in that UI, and was equally so in v1. Captured as
   [[00-inbox/approval-question-never-reaches-the-approver]]. Not fixed here: it is a client change
   outside this spec's file list and the card already shows the arguments, so what it should display
   is a product decision.
5. **A model can make the sentence disappear** by passing a list, `None` or a 201-character value,
   because that is what "abandon the whole sentence" means. Nothing false is ever shown and the
   arguments always are, but the operator gets no signal that a warning was written and dropped.
   Captured as [[00-inbox/a-model-can-drop-the-approval-sentence]]. Not fixed here because the
   fallback is part of the design this run was told not to substitute.
