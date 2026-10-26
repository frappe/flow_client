---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 6 2026-09-20 — REVIEW BEFORE MERGE
created: 2026-09-20
implemented: 2026-09-20
upstreamable: yes
---
# Spec: S16b — an approval switch cannot be turned off by accident

## Problem
Every approval gate in this engine is one checkbox, and the checkbox is editable.

Re-verified in this repository before a line was written:

1. **`requires_confirmation` is an ordinary `Check` on Flow Tool with no default**, so a row created
   by clicking "new" is created **unchecked** (`flow_tool.json`).
2. **`FlowTool.validate` calls `validate_immutable(self, ("type", "import_path"))`** — only those two
   fields are frozen on system-generated rows. `requires_confirmation` is not among them, so it
   stays editable on the builtin rows.
3. **The runtime reads the ROW, not the code**: `resolver._build_tool` takes
   `bool(doc.requires_confirmation)`. So unchecking the box on `delete` means the model deletes
   records with no approval question from the very next turn.
4. **What partially saves it is a deploy.** `after_migrate` → `sync_builtin_tools` rewrites each
   builtin row's flag from the code's value. Between two migrations the gate stays off, silently.
5. **A Script tool is arbitrary Python** run through the platform's own server-script sandbox, and
   its checkbox defaults to unchecked. The default for a hand-written tool that can write anything
   is therefore *ungated*.
6. **No test anywhere asserts the flag for the registry as a whole.** The existing suite pins
   `create`, `update` and `delete` individually and does not pin `run_action`, `execute` or
   `update_memory` at all.

The consequence is worse than "a tool without a prompt", because of how the loop works: a gated
call in an assistant turn becomes a question and is `continue`d — the loop does not break — so an
**ungated call later in the same turn executes while the person is reading the question about the
gated one**. An ungated write tool is a tool that fires at the worst possible moment.

## Goal
The gates on the write tools this engine ships cannot be turned off by editing a record, and a
hand-written tool is gated until its author deliberately turns the gate off.

## Non-goals
- An administrator override. Deliberately not built — **Open question 1**.
- Classifying a Script or third-party Imported tool as writing or not. Nothing in the engine can
  know that, and a check that can be evaded teaches people to evade it.
- `auto_approve`. A trigger run with `auto_approve` still runs every gated tool inline. Nothing here
  changes that, and the new test says so in its own docstring rather than implying coverage.
- Anything inside `execute`'s sandbox. It injects each builtin's raw function, so an approved
  `execute` calls the write tools with no further check. That is the design — the code is shown in
  full and the person approved it — and the `execute` row's own checkbox is the gate, which this
  spec is what protects.

## Design

### D1 — the write-capable builtins are named in code, once
`flow/tools/builtins.py` gains `WRITE_CAPABLE`, a mapping of slug → the write it performs, in
words. It is maintained by hand and that is the point: there is no machine-readable definition of
"writes" available here except `requires_confirmation` itself, and a test deriving one from the
other would assert that True implies True.

The gate that makes it real is a test asserting the classification is **total**: a tool added to
`BUILTIN_TOOLS` and to neither list turns the suite red. Nobody can add a write tool without
deciding, in writing, that it writes.

### D2 — unsetting the gate on one of those rows is refused
`FlowTool.validate` refuses to save a row whose slug is in `WRITE_CAPABLE` with
`requires_confirmation` unchecked, with a plain message naming the tool and saying what the gate is
for. It refuses on insert as well as on save, and it refuses **regardless of `ignore_permissions`** —
unlike `validate_immutable`, which skips for the owning app.

That difference is deliberate and is the one judgement call in this spec. A gate on a write tool
this engine ships is not an app-configurable value; there is no legitimate caller that turns it off.
`sync_builtin_tools` is unaffected because it writes the gate ON, and because it updates through
`db.set_value`, which bypasses `validate` entirely.

### D3 — a deploy still repairs a row that was changed before this fix
`sync_builtin_tools` already rewrites every builtin row's flag from the code value on every
migrate, so a row unchecked before this fix is restored by the next deploy. That behaviour is not
changed; it is **pinned by a test**, because it is the only thing that repairs a site rather than
preventing the next mistake, and nothing asserted it.

### D4 — a new tool is gated until someone turns the gate off
`requires_confirmation` gets `"default": "1"` on the doctype. A Script tool written in the desk is
arbitrary Python in a sandbox that can write, so the safe default is the gated one. This inverts an
unsafe default rather than adding a rule, which is why it is worth doing even though it protects
nothing that already exists.

Builtin rows are unaffected: `sync_builtin_tools` passes the flag explicitly on insert, so a read
tool is still created ungated.

### D5 — a code-declared approval is a floor a record cannot lower
Added during verification, and it is what makes D2's claim true rather than nearly true.

The refusal keys on the **slug**; the runtime executes the **import path**; nothing tied the two.
So a second Flow Tool record importing `flow.tools.builtins.delete` under a name the
classification has never heard of ran it **ungated, permanently** — the sync only ever visits
records named for a builtin, so no deploy repaired it. Both routes to it are ordinary desk saves.

`resolver._build_tool` now takes the imported object's own `requires_confirmation` as a floor:
a record may turn an approval **on**, and may not take one **off** that the function declares for
itself. `_resolve_module` already forwarded the imported tool's `confirm_prompt` and pointedly did
not forward its approval; that asymmetry was the whole defect.

One line, and it closes three things at once: the alias record above, the slug rename below, and
most of **R1** — a `db.set_value` that unchecks a builtin's record now produces a record that
disagrees with its own code until the next deploy, rather than an ungated write tool.

`slug` also joins `validate_immutable`'s frozen tuple. It was editable on a system-generated
record, and the refusal keys on it: renaming the shipped `delete` record's slug moved it out of the
classification and unchecked the approval **in the same save**, and the rename guard never fired
because a record keeps its name when its slug changes.

### D6 — the classification cannot be repaired the easy wrong way
Totality is not enough, and this was demonstrated, not imagined: with `execute` moved from
`WRITE_CAPABLE` into `READ_ONLY` — the first thing a hurried maintainer does to a failing
classification test — **the whole module stayed green** while arbitrary code execution lost its
refusal.

So the two lists are tied to the shipped flags: every write-capable tool ships gated and **every
read-only one ships ungated**. Moving a tool between the lists now contradicts its own code and
goes red on the next run.

### D7 — the registry test
A new file, adapted from the audit's proposal, asserting both halves separately because they are
different values: the **code** flag (what ships, and what a migrate copies) and the **row** flag
(what production reads). It carries two controls — the registry is not empty, and a read tool is
not gated — so neither assertion can pass vacuously, and it performs its own mutation in-process
and rolls it back, so the gate is proven red inside the run that proves it green.

## Acceptance criteria
See `s16b-gates-cannot-be-unset.features.json`.

> **D5 and D6 arrived during verification, after the contract was written and committed, and are
> deliberately NOT in `features.json`** — that file may only have its `passes` values flipped
> (workflow rule 4). Each is proved by a named test and by a probe that turned it red:
> `test_a_second_record_importing_a_write_function_is_still_gated` and
> `test_a_shipped_records_slug_cannot_be_changed` for D5,
> `test_nothing_gated_can_be_called_read_only` for D6, plus
> `test_the_shipped_doctype_declares_the_gated_default` and
> `test_an_explicit_choice_still_beats_the_default`. **Adding the five entries is a one-line change
> for a human.**

## What a real migrate showed
D4's default only takes effect once the doctype is applied to a site, so the change was measured
against one rather than asserted. `bench --site flow.localhost migrate`, then reading the site back:

    Flow Tool rows: create 1 · delete 1 · execute 1 · run_action 1 · update 1 · update_memory 1
                    describe 0 · find_doctypes 0 · read 0 · search_knowledge 0
    requires_confirmation default: 1

Two things at once. Every write-capable tool is gated on the site and every read-only one is not —
so the sync writes the classification, not a constant. And **S16a's gate on `update_memory` survived
a real migrate**, which is the claim that change depends on: had the gate been set on the row rather
than in code, this is where it would have been silently undone.

The Script-tool default was measured the same way: the test read **red** before the migrate ("a
hand-written tool that can write anything was created ungated") and **green** after it, with the
doctype JSON as the only change in between.

## Risks
- **R1 — `db.set_value` bypasses `validate`, and that is now much less interesting.** Anything that
  writes the column directly is not refused — including `sync_builtin_tools`, which is why the sync
  still works. **But since D5 the record is no longer the only say:** an imported tool that declares
  its own approval keeps it, so a column written behind `validate`'s back produces a record that
  disagrees with its own code until the next deploy, not an ungated write tool. What remains
  genuinely open is a Script tool, whose code nothing can classify, and anyone who can run server
  code, who was never contained by any of this. **The first version of this Risk was wrong in the
  other direction** — it claimed `db.set_value` was "the one route this does not close" while two
  ordinary desk saves were open. The security review found both.
- **R2 — the classification is by hand.** `WRITE_CAPABLE` is a list a person maintains. Two tests
  keep it honest, and it took a reviewer to show that one was not enough: totality (a builtin in
  neither list is red) **and** agreement with the shipped flags (a read-only tool that ships gated
  is red). Without the second, the repair for a red classification test was to move the tool.
- **R5 — a slug listed in `WRITE_CAPABLE` whose tool ships ungated aborts the sync.** The insert
  branch of `sync_builtin_tools` passes the code flag straight to `insert`, which runs `validate`,
  which would throw — during `after_migrate`. It cannot happen here (every listed tool ships
  gated, asserted) but it is the failure mode to know about before adding an entry, and it is why
  **this change cannot be taken upstream without S16a**: upstream's memory tool ships ungated, so
  `update_memory` in this list would abort an install there.
- **R3 — an administrator who genuinely wants a tool ungated now cannot have it.** No override is
  built. **Open question 1.**
- **R4 — the new default changes what "new Flow Tool" means.** Any existing flow that created a
  Script tool and expected it ungated now gets a gated one. That is the intended inversion, but it
  is a behaviour change for anyone automating tool creation.

## Open questions for the owner
1. **Should an administrator ever be able to override a builtin's gate — say, a System Manager-only
   setting, or a site config key?** Not built here, on purpose. Arguments both ways: an engine
   whose gates cannot be configured is one people work around; an engine whose gates can be
   configured has a switch that turns off every approval in it. If an override is wanted it should
   be per-tool, logged, and require something more deliberate than a checkbox.
2. **Should `validate_immutable`'s tuple gain `requires_confirmation` as well?** That would freeze
   the field in both directions on every system-generated row, including turning a gate ON. D2
   refuses only the unsafe direction and only for the write tools. The wider rule is simpler to
   state and harder to reason about.
3. **Should the same protection cover a Script tool an administrator has marked as writing?** There
   is no such marking today, and inventing one is a bigger spec.
