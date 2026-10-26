---
type: spec
status: approved  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner, run 10
created: 2026-09-21
supersedes: /home/thivs/agent-proposals/research-2026-09-21-j/S20-spec.md
revised-by: adversarial review r10, 21 Sep 2026 (/home/thivs/agent-proposals/review-2026-09-21-r10/FINDINGS.md)
upstreamable: yes
base: veyqon = 04f4eabe50dadded5739ba0da052b9f369601547
origin: N2 adversarial review finding C-1 (/home/thivs/agent-proposals/review-2026-09-21-n2/FINDINGS.md)
note: read-only review. Nothing below was executed; every file:line was read at `veyqon`.
---
# Spec: S20 (v2) — a tool whose code says nothing about approval asks

## What changed from v1
1. **The fix is extended to Script tools (D2, new).** v1 proved that the `in_import` route defeats
   the doctype default, then closed it for the Imported bare-callable branch only. `_resolve_script`
   (`flow/lib/resolver.py:71-73`) passes no floor either, so a Script row imported through a fixture
   with `requires_confirmation` omitted resolves **ungated** — arbitrary sandboxed code the model can
   call with nobody asked. That is the worse half of the same hole.
2. **K3's "who can still create an ungated tool" is answered in full** — v1 stated two of three
   routes.
3. **AT7's positive control is written as code**, and AT2 gains the control that proves its flag
   restore happened. AT8 is new, for D2.

--------------------------------------------------------------------------------------------------
## Problem
--------------------------------------------------------------------------------------------------
`flow/lib/resolver.py:46-68` resolves an `Imported` Flow Tool row. Three branches:

```
55	if isinstance(obj, Tool):
56		return _build_tool(doc, obj.parameters, obj.func,
60			confirm_prompt=obj.confirm_prompt,
61			code_requires_confirmation=obj.requires_confirmation)   ← the floor S16b D5 added
63	if callable(obj):
64		return _build_tool(doc, build_schema(obj), obj)              ← no floor at all
65	frappe.throw(...)                                                ← not a Tool, not callable
```

and `_resolve_script` (`:71-73`) is a fourth with no floor either:

```
71	def _resolve_script(doc, *, restrict_commit_rollback=False):
72		runner = _make_script_runner(doc.code, doc.slug, restrict_commit_rollback=restrict_commit_rollback)
73		return _build_tool(doc, schema_from_code(doc.code), runner)
```

`_build_tool` (`:76-103`) defaults `code_requires_confirmation: bool = False` (`:82`) and computes
at `:96`:

```
96		requires_confirmation=bool(doc.requires_confirmation) or bool(code_requires_confirmation),
```

So for a **bare module-level callable** and for a **Script tool**, the code half of that `or` is
permanently `False`. The record is the only say. S16b D5's finding — "a record may turn an approval
ON; it may not take one OFF that the imported function declares for itself" — is wide open in the
two branches where the code has no voice at all.

### Who can create or edit such a row, at `veyqon`
| question | answer | where |
|---|---|---|
| who may create/write/delete a Flow Tool row | **System Manager only**, plus Administrator implicitly. No `"All"` role row, no `if_owner` row | `flow/flow/doctype/flow_tool/flow_tool.json:134-145` |
| who may set `import_path` | the same — an ordinary `Data` field, `mandatory_depends_on`, no permlevel | `flow_tool.json:108-115` |
| is `import_path` ever frozen | only on **system-generated** rows, and only when the caller is not `ignore_permissions` | `flow_tool.py:60` → `flow/utils/system_generated.py:18-38` (early return at `:21`) |
| is `import_path` restricted to an allowlist | **No.** Only a shape check | `flow_tool.py:26` `IMPORT_PATH_PATTERN`, enforced at `:147-153` |
| what resolves it | `frappe.get_attr(doc.import_path)` — any importable dotted path on the bench's Python path | `flow/lib/resolver.py:48` |

**Measured, not assumed.** `git grep -n "ALLOWED_IMPORT\|IMPORT_ALLOWLIST\|allowed_modules\|startswith(\"flow\."`
over `veyqon` returns no match. **Positive control:** the same grep form for `IMPORT_PATH_PATTERN`
returns `flow_tool.py:26` and `:147`.

### What a row could point at today
Anything `frappe.get_attr` can import — a helper in an installed app (`some_app.utils.purge_old_records`),
a framework function (`frappe.delete_doc`, `frappe.rename_doc`, `frappe.sendmail`), or the N2
review's C-1 scenario: a module-level `call_tool(server, tool_name, arguments)` in an MCP package,
reached directly so the package's own `__getattr__` guards never run.

### What saves it today, and exactly how far
`requires_confirmation` has `"default": "1"` on the doctype (`flow_tool.json:57-69`, S16b D4). A row
created **through the desk or `frappe.new_doc`** is gated unless someone unticks the box. That is a
real mitigation and this spec does not weaken it. It leaves three holes:

- **Unticking is permitted.** `FlowTool._validate_confirmation_not_removed` (`flow_tool.py:79-114`)
  refuses only for slugs in `WRITE_CAPABLE` (`flow/tools/builtins.py:588-595`) — the six shipped
  builtins. A row named anything else is free to be ungated.
- **`db.set_value` bypasses `validate` entirely**, as S16b's R1 records.
- **A fixture or data import gets no default at all.** VERIFIED in Frappe 16.31.0,
  `frappe/model/document.py:1069-1071`:

  ```
  1069	def _set_defaults(self):
  1070		if frappe.flags.in_import:
  1071			return
  ```

  `frappe.flags.in_import = True` is set by `frappe/core/doctype/data_import/importer.py:74` and by
  `frappe/modules/import_file.py:211` — the fixture / `bench migrate` path. A row imported with
  `requires_confirmation` **omitted** is inserted with the field falsy — **ungated** — and the
  doctype default never applies. This is the route an app ships, a migration replays, and nobody
  reviews as a tool definition.

--------------------------------------------------------------------------------------------------
## Contract
--------------------------------------------------------------------------------------------------
**A tool whose code says nothing about approval asks.** A Flow Tool row resolving to a bare callable,
or to a Script body, is gated, and the record may not take that gate off — exactly the rule
`flow/lib/resolver.py:61` already applies to an imported `Tool`, extended to the two branches where
the code has no voice.

Turning a gate **on** is never refused. One-directional, like every other gate rule in this engine.

--------------------------------------------------------------------------------------------------
## Design
--------------------------------------------------------------------------------------------------

### D1 — the bare-callable branch declares its own floor (`flow/lib/resolver.py:63-64`)
```python
if callable(obj):
    # A plain function says nothing about approval, and "nothing" is not "no". The record may
    # turn a gate ON; it cannot take one off that was never declared. `frappe.get_attr` will
    # import any dotted path a System Manager can type, so this branch is the widest surface in
    # the registry and the only one where the code has no voice at all.
    return _build_tool(doc, build_schema(obj), obj, code_requires_confirmation=True)
```

### D2 — the Script branch declares the same floor (`flow/lib/resolver.py:71-73`) — **new in v2**
```python
def _resolve_script(doc: FlowTool, *, restrict_commit_rollback: bool = False) -> Tool:
    runner = _make_script_runner(doc.code, doc.slug, restrict_commit_rollback=restrict_commit_rollback)
    # A Script tool is arbitrary code in a sandbox and declares nothing about itself at all. The
    # doctype default gates one created at a desk; a row imported as a fixture never sees a
    # default (frappe/model/document.py:1069-1071), and that is the row nobody reviews.
    return _build_tool(doc, schema_from_code(doc.code), runner, code_requires_confirmation=True)
```

After D2 a Script tool cannot be ungated by any route. That is what S16b D4's default already
intended and could not guarantee, and it is the stronger half of this spec: a bare callable is at
least code somebody wrote and installed, while a Script body is code a record carries.

**Cost, stated plainly:** an integrator who deliberately ran a read-only Script tool ungated now has
their tool ask. There is no override, on purpose. The escape hatch is to ship it as a decorated
`Tool` with `requires_confirmation=False`, which makes the ungating a reviewed code decision instead
of a checkbox. **R2 / Open question 2.**

### D3 — the default stays, and stops being the only thing
`flow_tool.json:58`'s `"default": "1"` is unchanged. D1 and D2 cover the three routes it misses
(untick, `db.set_value`, `in_import`), because they are computed at **resolve** time from the code,
not read from the row.

### D4 — what is deliberately NOT built
- **An `import_path` allowlist.** `frappe.get_attr` is the framework's own resolution, and an
  allowlist here would be a second, weaker copy of the app's install decision that would break every
  legitimate integration tool on the first deploy. The person who can create a Flow Tool row is a
  System Manager, who can already run server code. The threat S20 closes is not "a System Manager
  imports something dangerous" — it is "a tool the model can call fires with nobody asked", and a
  gate answers that where an allowlist does not.
- **Refusing a bare callable outright** (N2's "import_path must resolve to a `Tool` object"). A
  stronger rule and the wrong one for the engine: it breaks every existing row pointing at a plain
  function and pushes integrators toward a Script tool, which is strictly worse. It remains right for
  the MCP package specifically, where it is N2's own C-1 fix. **Open question 1.**
- **Anything about `execute`'s sandbox**, which injects builtin functions directly and is gated by
  its own row.

--------------------------------------------------------------------------------------------------
## Who can still create an ungated tool after S20 (K3, answered in full)
--------------------------------------------------------------------------------------------------
| route | still possible? | who | why it is acceptable |
|---|---|---|---|
| a row importing a **`Tool` object** declared `requires_confirmation=False` | **yes, by design** | anyone who can write a Flow Tool row (System Manager, `flow_tool.json:134-145`), using code shipped by an installed app | the code has a voice and used it; the ungating is a reviewed decision in a file, not a checkbox |
| a **bare callable** row, any insert route | **no** — D1 | — | — |
| a **Script** row, desk or `new_doc` | no (doctype default, S16b D4) | — | — |
| a **Script** row via fixture / data import (`in_import`) | **no after D2**; **yes without it** | an installed app's fixtures, replayed by `bench migrate` | this is S20-H1, and it is why D2 is in v2 |
| any row via `db.set_value` behind `validate` | the **column** can still be set to 0 | System Manager, or any server code | irrelevant after D1/D2: the floor is computed at resolve time, so the column merely disagrees with the runtime. It still matters for the `Tool`-object row in the first line |

--------------------------------------------------------------------------------------------------
## What this changes for existing tools and tests
--------------------------------------------------------------------------------------------------
**Existing shipped rows: nothing. VERIFIED by reading, not assumed.** All ten builtins are
module-level `Tool` objects — eight decorated with `@tool` (`flow/lib/tool.py:56-76`) and two
assigned from binders at module level: `search_knowledge = bind_search_knowledge([])`
(`flow/tools/builtins.py:144`) and `update_memory = bind_update_memory(None)` (`:303`). All ten are
in `BUILTIN_TOOLS` (`:601-612`), and `sync_builtin_tools` (`:615-641`) writes
`import_path = f"flow.tools.builtins.{name}"` (`:619`), which `frappe.get_attr` resolves to the
`Tool`, not to its `func`. Every shipped row therefore takes the `isinstance(obj, Tool)` branch at
`:55` and never reaches `:63`. The four read-only builtins (`find_doctypes`, `describe`, `read`,
`search_knowledge`, `:598`) stay ungated because their `Tool.requires_confirmation` is `False`.

**Existing rows in a site:** any `Imported` row pointing at a plain function, and any `Script` row
that was ungated, becomes gated. That is the intended behaviour change and the same inversion S16b
D4 made. **R2**, **Open question 2**.

**Tests — measured, and the upstream one survives.** `git grep -ln "import_path" veyqon --
flow/tests/ evals/` returns exactly three files: `flow/tests/test_ai_confirm_template.py` and
`flow/tests/test_write_tools_confirm.py` (both fork-owned) and `flow/tests/test_ai_resolver.py`
(upstream's — it is listed by `git ls-tree -r --name-only develop flow/tests/`). Positive control
for the search shape: the same grep for `IMPORT_PATH_PATTERN` returns `flow_tool.py:26` and `:147`.

`test_module_plain_callable_schema_from_hints` (`test_ai_resolver.py:154-161`) patches
`frappe.get_attr` to return `_plain_callable` (`:101-102`) and asserts **only the derived schema**;
`git grep -n "requires_confirmation" veyqon -- flow/tests/test_ai_resolver.py` returns no match, with
the positive control above. `test_module_tool_object_is_resolved` (`:143-152`),
`test_module_import_failure_throws` (`:163-167`) and `test_module_non_callable_throws` (`:169-173`)
are on branches D1 does not touch.

**D2 is the one to re-check before building:** `git grep -n "type.*Script" veyqon -- flow/tests/`
and the fork-owned Script tests must be read for any assertion that a Script tool resolves ungated.
None was found in the three files above, but D2 was added in review and its test surface has not
been grepped as exhaustively as D1's. **Build step 0.**

--------------------------------------------------------------------------------------------------
## Acceptance tests
--------------------------------------------------------------------------------------------------
New file `flow/tests/test_s20_bare_callables_are_gated.py`. Watched failing before passing.

**Every test runs as a named non-Administrator user.** `setUp` creates `s20-tester@example.com` with
the System Manager role and calls `frappe.set_user`; `tearDown` restores. Not decoration: Flow Tool's
only permission rule is the System Manager one (`flow_tool.json:134-145`), and a test running as
Administrator would pass even if that rule were deleted.

**AT1 — `test_a_row_pointing_at_a_bare_function_is_gated_even_with_the_box_unticked`**
Insert `{type: "Imported", slug: "s20_helper", import_path: "<test module>.a_plain_function",
requires_confirmation: 0}` and resolve via `flow/lib/resolver.py:35-43`. Assert
`tool.requires_confirmation is True`. *Mutation:* remove `code_requires_confirmation=True` from D1 →
`False`. **Pre-fix observation:** exactly that.

**AT2 — `test_the_import_default_does_not_save_us`**
The same row inserted with `frappe.flags.in_import = True` and `requires_confirmation` **omitted**.
Assert the stored column is falsy — pinning `frappe/model/document.py:1069-1071` — **and** that the
resolved tool is still gated. `frappe.flags.in_import` is restored to **`False`** in a `finally`
(not `del`; it is process-global and every later test in the process would lose its doctype
defaults). **Control, in the same test:** after the restore, insert one more row with the field
omitted and assert it *does* get the default — which is what proves the restore happened.
*Mutation:* remove D1 → the row is ungated and the model gets an ungated tool.

**AT3 — `test_a_decorated_tool_keeps_its_own_answer_in_both_directions`**
Two rows: one importing an ungated `@tool` with `requires_confirmation: 0` → resolves **ungated**;
one importing `@tool(requires_confirmation=True)` with `requires_confirmation: 0` → resolves
**gated** (S16b D5, unchanged). *Mutation:* apply D1's floor to the `isinstance(obj, Tool)` branch as
well → the first assertion goes red. The control that stops the fix gating every read-only tool.

**AT4 — `test_a_read_only_builtin_row_is_still_ungated`**
Resolve the shipped `read` row (`import_path = "flow.tools.builtins.read"`). Assert
`requires_confirmation is False`. *Mutation:* move D1's floor into `_build_tool`'s default
(`resolver.py:82`) → red. The likeliest wrong repair, and nothing else catches it.

**AT5 — `test_the_record_can_still_turn_a_gate_on`**
A bare callable with `requires_confirmation: 1` resolves gated. *Mutation:* replace `or` with `and`
at `resolver.py:96` → red here and red on S16b's existing tests.

**AT6 — `test_a_non_callable_import_path_is_still_refused`**
`import_path` pointing at a module-level constant raises through `frappe.throw` at `:65-68`.
*Mutation:* make D1's branch `if obj is not None` → the refusal is unreachable.

**AT7 — `test_the_refusal_and_the_gate_name_no_platform_or_vendor`** (CLAUDE.md rule 3)
The approval question built for AT1's tool (`flow/lib/agent.py:624-658`) contains none of `frappe`,
`erpnext`, `mariadb`, `openai`, `anthropic`, `gpt-`, `claude`, case-insensitively.
**The control is code, not prose:** the same helper applied to a string containing `frappe` is
wrapped in `with self.assertRaises(AssertionError):`, so the control itself can go red.
*Mutation:* put the module path into the question's title → red.

**AT8 — `test_a_script_tool_imported_as_a_fixture_is_still_gated`** (new, for D2)
Insert `{type: "Script", slug: "s20_script", code: "<a trivial main>"}` with
`requires_confirmation` **omitted** and `frappe.flags.in_import = True` (restored as AT2 does).
Assert the stored column is falsy **and** `resolve(...).requires_confirmation is True`.
*Mutation:* remove `code_requires_confirmation=True` from D2 → the resolved Script tool is **ungated**
and the model can run arbitrary sandboxed code with nobody asked. **This is the hole v1 proved and
left open.**

**Gate:** all eight are proved by `scripts/run-tests.sh` (`GATE=GREEN`). **No evals scenario
changes** — the evals runner builds `Tool` objects directly (`evals/run.py:140-177`) and never
touches the resolver, so it cannot see this change. Stated rather than implied.

--------------------------------------------------------------------------------------------------
## Size
--------------------------------------------------------------------------------------------------
| file | change | lines |
|---|---|---|
| `flow/lib/resolver.py` | D1 — one argument plus its comment | 6 |
| `flow/lib/resolver.py` | D2 — one argument plus its comment | 5 |
| `flow/tests/test_s20_bare_callables_are_gated.py` | new, AT1–AT8 | ~210 |

**Two engine lines.** One branch, `loop/s20-code-with-no-voice-is-gated`. It shares nothing with
S19 — after S19 v2 drops `write_capable`, S19 does not touch `flow/lib/resolver.py` at all — and
nothing with J2, so it can be built in parallel with either.

--------------------------------------------------------------------------------------------------
## Risks
--------------------------------------------------------------------------------------------------
- **R1 — a gate is not a permission.** D1/D2 stop a tool running *unasked*. They do not stop a person
  approving it, and they do not stop a System Manager creating the row. N2's C-1 is only fully closed
  by N2's own fix (no module-level callable in the MCP package). S20 is the engine floor beneath
  that, not a replacement for it.
- **R2 — an integration tool or a Script tool that was ungated on purpose now asks.** No override, on
  purpose: an override is a switch that turns approvals off, which is what S16b refused. The correct
  escape hatch is to ship it as a decorated `Tool` with `requires_confirmation=False`. Say so in the
  doctype's `import_path` and `code` field descriptions. **Open question 2.**
- **R3 — `db.set_value` still bypasses `validate`.** It no longer matters for the two floored
  branches: the floor is computed at resolve time, so a column written behind `validate`'s back
  produces a record that disagrees with the runtime rather than an ungated tool. It still matters for
  a row importing a `Tool` that declares itself ungated.
- **R4 — D2 is a wider behaviour change than D1** and was added in review rather than research. Its
  test surface has not been grepped as exhaustively (build step 0 above). If a fork-owned test
  asserts an ungated Script tool, that test — not D2 — is the thing to re-examine.
- **R5 — the `in_import` finding is read from Frappe 16.31.0 and was not executed.**
  `frappe/model/document.py:1069-1071` is unambiguous and its two setters were located
  (`importer.py:74`, `import_file.py:211`), but AT2 and AT8 are what turn a reading into a
  measurement, and neither has been run.

--------------------------------------------------------------------------------------------------
## Upstream position
--------------------------------------------------------------------------------------------------
**Upstreamable: yes, and the cleanest upstream candidate of the three specs in this batch.** Two
lines in `flow/lib/resolver.py`, depending on nothing this fork added beyond S16b D5's
`code_requires_confirmation` parameter, and changing no upstream test. Branch from `develop`, engine
plus its test only, conventional commit (`fix: an imported callable or script with no declared
approval is gated`).

**Check before carrying it up:** S16b D5 must already be upstream, or `code_requires_confirmation`
does not exist there and the diff is four lines instead of two.

--------------------------------------------------------------------------------------------------
## Open questions for the owner
--------------------------------------------------------------------------------------------------
1. **Should the MCP package additionally require `import_path` to resolve to a `Tool`?** S20 says no
   *for the engine* and yes *for that package* — N2's C-1 fix, enforced by a structural test over the
   package's own module-level names. Complementary; confirming the split is the owner's call.
2. **Does an integrator ever need an ungated imported callable or Script tool?** If yes, the answer
   is "ship it as a decorated `Tool`", and the doctype field descriptions should say so. If the
   answer is "and they cannot change their code", S20 needs an override and S16b's Open question 1
   comes back.
3. **v1's third question is withdrawn.** It asked whether `import_path` should join a
   `WRITE_CAPABLE`-style classification for S19 Part B. Under the owner's unattended rule there is no
   classification: a bare callable is gated after S20, and a gated tool is refused in an unattended
   run. The two specs now meet cleanly, and S19's R3 is closed rather than mirrored.

--------------------------------------------------------------------------------------------------
## Found in the build review (run 10, two fresh reviewers, read-only + one mutating)
--------------------------------------------------------------------------------------------------
Security auditor and QA adversary, separate contexts, neither having written any of this code.
**Neither found a HIGH, and neither found a route to an ungated runnable tool that D1/D2 miss.**
Both enumerated every construction of a `Tool` in non-test code — `flow/lib/tool.py`,
`flow/lib/resolver.py` and `evals/run.py` are the only three — and both confirmed the floor survives
to `flow/lib/agent.py`'s `_invoke`, which reads the RUNTIME tool and never the record. QA also
measured the routes v1 worried about: `db.set_value` forcing the column to 0 on a Script row gives
`SCRIPT_COLUMN: 0  RUNTIME: True`; `functools.partial`, a bound method, a module-level lambda and
the raw `.func` behind an ungated `Tool` all resolve **gated**.

**FIXED in this branch (review MEDIUM — the only finding inside this spec's files).**
`_build_tool`'s `code_requires_confirmation` defaulted to `False`, and after D1/D2 that default is
unreachable from every production call site — which is why the spec's named mutation for AT4 (move
the floor into the default) was GREEN. A default nobody reaches is a trap: a fourth resolution
branch written later and calling `_build_tool` without the argument would resolve ungated, exactly
as these two branches did before S20, and nothing would go red. The default is now the **safe**
answer, `True`: a branch that says nothing about the code builds a tool that ASKS. Two new tests,
both watched failing first (`TestTheFloorCannotBeForgotten`): the default is `True`, and a call
site that omits the argument builds a gated tool.

Removing the default outright — the reviewer's own proposal — was **tried and rejected, measured**:
it makes a forgotten argument a `TypeError`, and `flow/tests/test_ai_confirm_template.py:485`
calls `_build_tool` without it deliberately (it is testing a record written before the
`confirm_template` column existed). That call errored the gate. Making it green again would mean
editing a test to fit the code, which the workflow forbids; a safe default closes the same hole
without touching a test that was right.

**RECORDED FOR THE OWNER, NOT CHANGED — each is outside this spec's files.**
1. **MEDIUM (both reviewers, independently) — the tool panel is told the opposite of what the
   engine will do.** `flow/api/api.py:148-164` (`get_agent_tools`) reports
   `requires_confirmation` **from the row**, so for exactly the rows S20 changes — a bare-callable
   or Script row with the box unticked — the panel says "runs inline" while the engine pauses and
   asks. QA reproduced it (`API_MAP: {'qa_api_tool': False}  RUNTIME: True`). **Fail-safe
   direction**: no approval is skipped and a live pause still renders its card, because
   `AssistantMessage.vue` falls back to the question's presence. What it costs is a reloaded
   conversation: `frontend/src/store.js:440-445` recovers the "Denied" badge only from that map, so
   a refusal the person made can re-render as an ordinary tool result. Smallest fix: resolve
   instead of reading the column (`to_tool().requires_confirmation`, `True` if the resolve throws —
   an unresolvable tool must never be advertised as inline), with a test for an unticked
   bare-callable row. It touches `flow/api/api.py`, which this spec does not name, so it is the
   owner's to schedule.
2. **LOW — a fork-owned test now documents the opposite of the shipped rule.**
   `flow/tests/test_write_tools_confirm.py:363-370` says of a Script tool "its author decides".
   After D2 the author decides only by shipping a decorated `Tool`. The assertion is about the
   stored column and stays true; the docstring is what is now misleading, and a maintainer could
   read it as the contract.
3. **LOW — a legacy pause with no recorded questions.** `flow/lib/agent.py:288` falls back to the
   tool's CURRENT gate when a pause carries no `asked` record, and S20 flips exactly that class of
   tool from ungated to gated. A run that paused before this deploy on a Script tool's OWN question
   could, after it, execute on the literal answer "Approve". Upgrade-window only — current code
   always stores the questions — and narrowing it is a `_prepare_resume` change, which CLAUDE.md
   rule 4 says needs a spec that names it.
4. **LOW — R2's field descriptions were not written.** The escape hatch ("ship it as a decorated
   `Tool`") is in this spec and in the code comments, and nowhere an integrator reads.
   `flow_tool.json` is untouched by this branch on purpose: a doctype JSON edit is its own review.
5. **Pre-existing, outside S20 entirely** — `flow/assistant/assistant.py` names the platform in the
   assistant's own system instructions (a CLAUDE.md rule 3 violation already on `veyqon`) and tells
   the model to set `auto_approve=1` on triggers it creates. S19 Part B is what answers the second
   half; the first half is a separate one-line capture.
