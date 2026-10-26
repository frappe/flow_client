---
type: spec
status: implemented  # draft → approved (HUMAN ONLY) → in-progress → implemented
approved-by: owner pre-approval for unattended run 8 2026-09-21 — REVIEW BEFORE MERGE
created: 2026-09-21
implemented: 2026-09-21
upstreamable: yes
---
# Spec: S18 — knowledge search returns only what the asking user may read

## The contract, in one sentence

**A knowledge hit whose source record the asking user cannot read never reaches the model or the
caller — no excerpt, no title, no source, no score, no reference — and it is not counted.**

## Problem

`flow/knowledge/retriever.py` says the opposite out loud, and the code matches it. Re-verified in
THIS tree (`loop/s18-knowledge-read-filter`, cut from `veyqon` @ `3da5570`) before a line was
written:

1. **The module docstring declares that per-chunk permission is deliberately not checked**
   (`flow/knowledge/retriever.py:10-16`): *"Permission model — the knowledge base is the boundary…
   Retrieval is therefore not re-checked per chunk against the running user; the binding is the
   authorization."*
2. **`retrieve` never reads `frappe.session.user`** (`retriever.py:51-95`) and `_hydrate` reads with
   `frappe.get_all` (`retriever.py:104-110`), which applies no permission at all.
3. **The chunks already carry the record they came from.** A `DocType` knowledge source stamps
   `reference_doctype` and `reference_name` on every chunk it makes (`flow/knowledge/ingest.py:238-239`,
   from `flow/knowledge/extract.py:120`). A `Text`, `File` or `URL` source does not — that insert has
   no reference keys at all (`flow/knowledge/ingest.py:121-130`).
4. **The model's own tool goes straight down this path.** `search_knowledge` is
   `bind_search_knowledge(kbs)` → `retrieve(query, kbs=kbs)` and nothing else
   (`flow/tools/builtins.py:115-125`).

So `search_knowledge` returns an excerpt of any indexed record to anyone who can chat with the agent,
whether or not they may open that record.

**Why it matters now.** A separate app (`q_flow_tools`, not in this repository) indexes company notes
whose folders are restricted by role. Those restrictions are enforced by the standard
`has_permission` / `permission_query_conditions` hook pair, which the desk honours and which
`frappe.get_all` bypasses. Without this change the restriction is simply bypassed through search.
This spec closes that path **in the engine, for every DocType source**, not only for notes.

**The asymmetry is upstream's own**, which is the argument for fixing it here rather than in a tool:
the `read` builtin reads through `frappe.get_list` (`flow/tools/builtins.py:97`) and `find_doctypes`
filters through `frappe.has_permission` (`flow/tools/builtins.py:49`), while knowledge checks nothing.

## Goal

1. A hit whose source record the asking user may not read is dropped before anything about it is
   built, and contributes nothing to the returned structure.
2. Dropping is silent **to the asker**: no message, no toast, no raise, and no Error Log row *for a
   refusal*. "Some results were withheld" is itself information.
   **Amended after review (M1, run 9).** That argument is about the asker, and an Error Log row is
   visible only to an administrator, so it does not extend to one. A check that REFUSES and a check
   that CANNOT ANSWER are different events: the first is unremarkable and stays silent everywhere;
   the second is still fail-closed and still silent to the asker, but is written **once per search**
   to the Error Log, carrying no content, title, excerpt or record name. Without that, a lock-wait
   timeout empties every search while the asker is told "nothing matched" and nobody has a record.
3. The caller still gets up to `limit` **readable** hits when readable ones exist, bounded by a
   stated ceiling on how many candidates are examined.
4. A chunk with no reference behaves exactly as it does today — every existing `Text`, `File` and
   `URL` knowledge base is unaffected.
5. Every hit that survives carries its source record's own **title** and a **relative** desk path,
   both built only after the permission check.

## Non-goals

- `q_flow_tools`, the note doctypes, the folder tree, the role hooks, the proposing tools: N1 §1, §2,
  §3 and §6. None of them are in this repository.
- Tuning recall. The over-fetch factor is chosen, stated, and left for the owner to tune against a
  measurement (Open question 1).
- Changing the store schema, re-embedding, or rebuilding the index.
- `retrieve_attachments`. Its boundary is the session, enforced upstream of it
  (`retriever.py:31-48`, `:34`).

## Design

### D1 — the filter (N1-C4)

Inside `retrieve()`, in the loop over hits, a hit is kept only if the asking user may read its
source record:

```python
def _may_read(chunk: dict[str, Any]) -> bool:
	doctype, name = chunk.get("reference_doctype"), chunk.get("reference_name")
	if not doctype and not name:
		return True   # no record behind it — nothing to check against
	if not doctype or not name:
		return False  # half a reference is a chunk to distrust
	return frappe.has_permission(doctype, "read", name)
```

> **Corrected after review (L5, run 9).** This block previously read `if not doctype or not name:
> return True`, which fails **OPEN** for half a reference — the opposite of this spec's own prose
> sixty lines below, of the shipped code, and of probe P7. This spec is `upstreamable: yes`, and a
> code block is the part of a spec that gets copied.

- **The record, not the doctype.** `frappe.has_permission(doctype, "read", name)` takes the `doc`
  branch (`frappe/permissions.py:137-140`), which loads the row with `frappe.get_lazy_doc` — whose
  own comment is *"perf: Avoid loading child tables for perm checks"* (`frappe/permissions.py:139-140`)
  — and evaluates `get_doc_permissions` (`:227`) → `has_controller_permissions` (`:237`, defined
  `:481`) → the doctype's `has_permission` hook. The doctype-level form
  `frappe.has_permission(doctype, "read")` would answer the same for every row and check nothing.
- **`throw=True` is forbidden on this call, as a rule and not a note.** `frappe.has_permission`
  (`frappe/__init__.py:600-646`) forwards `print_logs=throw` (`frappe/__init__.py:632`), and with the
  default `throw=False` the `print_has_permission_check_logs` decorator never sets
  `frappe.flags["has_permission_check_logs"]` (`frappe/permissions.py:42-62`), so
  `push_perm_check_log` returns at its first statement (`frappe/permissions.py:798-803`) and the
  *"User X does not have access to this document"* message (`frappe/permissions.py:146`, pushed at
  `:151`) is never produced. With `throw=True` the messages come back **and** a
  `frappe.PermissionError` is raised out of the middle of a search (`frappe/__init__.py:638-644`).
  Test 4.7 is what pins this.
- **A check that cannot answer drops the hit, and says nothing.** Establishing the permission means
  loading the record (`frappe/permissions.py:139-140`), and the record can be gone:
  `ignore_links_on_delete` lists `Flow Knowledge Chunk` with the explicit comment that a chunk must
  never block deleting the record it indexes, and the sweep that removes the orphan is **daily**
  (`flow/hooks.py:39-43`, `:49-52`). So between a delete and the next sweep the store holds hits
  whose record no longer exists, and `load_from_db` raises `DoesNotExistError` **with a message
  naming the record** (`frappe/model/document.py:294-296`; `frappe.throw` appends to
  `frappe.message_log` before raising). A restriction hook belonging to another app can raise or
  `msgprint` for its own reasons. The check therefore snapshots `frappe.local.message_log`, catches
  `Exception`, returns **False**, and restores the snapshot in a `finally`. The broad catch is
  deliberate: on a read path, *failing to establish* permission and *being refused* must have the
  same outcome.
- **Half a reference is not "no record behind it".** A chunk that names a type but carries no record,
  or the reverse, is a chunk to distrust: `_may_read` returns True only when **both** are absent, and
  False when exactly one is. Today's ingest always sets both or neither
  (`flow/knowledge/ingest.py:121-130`, `:238-239`), so this is defence in depth, not a live path.
- **The asking user is whoever the run carries.** `_may_read` passes no `user`, so
  `frappe.permissions.has_permission` defaults to `frappe.session.user`. `Administrator` is allowed
  everything by that function's third statement, which is why **every** permission test in this spec
  runs as a named non-Administrator user and asserts `frappe.session.user` before searching.

### D2 — over-fetch, and the ceiling (N1-C5)

Filtering after a `limit`-sized fetch can leave one hit or none. So the store is asked for more, and
the loop stops at the first `limit` readable hits:

```python
OVERFETCH = 4
CANDIDATE_CEILING = 100  # = flow.knowledge.store.MAX_SEARCH_LIMIT
hits = store.search(vector, text=text, kbs=kbs, limit=min(limit * OVERFETCH, CANDIDATE_CEILING))
```

**The ceiling is 100, and the reason is that it is not ours.** `store.search` already clamps its
`limit` to `[1, 100]` (`flow/knowledge/store.py:132`, `MAX_SEARCH_LIMIT` at `:24`). Asking for more
than 100 would be silently truncated by the store, so a larger number would be a claim the code
cannot keep. 100 is therefore the honest ceiling rather than an invented one, and it bounds the added
work per search at **at most 100** `frappe.has_permission` calls — in practice at most
`min(limit * 4, 100)` = 20 for the default `limit` of 5 (`DEFAULT_LIMIT`, `retriever.py:28`).

**The ceiling is a real stopping condition, not a comment.** When every one of the candidates is
unreadable, the search ends and returns what it has — fewer than `limit` hits, or none — rather than
paging deeper. Test 4.11 measures that.

**The cost is recall, and it is the correct behaviour.** A user who may read one folder in ten gets
fewer than `limit` hits whenever the candidates are dominated by folders they cannot read.
**A user's search is as good as their access.** This must be stated to the owner, not tuned away.

### D3 — citations (N1-C6)

Every surviving hit gains two keys, built **after** `_may_read` has kept it:

- `title` — the source record's own title, read through `meta.get_title_field()`
  (`frappe/model/meta.py:371-377`, which returns `title_field`, else `title`, else `name`). For a
  chunk with no reference it falls back to the `Flow Knowledge Source.title`, which for a local file
  is the basename (`flow/knowledge/knowledge.py:41`) — the opaque `Flow Knowledge Source` docname is
  useless here, the doctype being `autoname: hash`.
- `url` — a **relative** desk path, `/desk/<doctype-slug>/<name>`, with the name percent-quoted. For
  a chunk with no reference it is `None`. The prefix is the single constant `DESK_PATH` in
  `flow/knowledge/retriever.py`.
  **Owner decision, run 9** (open question 2, now closed): Frappe's canonical desk route is
  `/desk/<path:app_path>` (`frappe/hooks.py:65`); `/app/(.*)` reaches the same form only through a
  redirect (`frappe/hooks.py:69`). The link handed to a caller is the one that resolves directly.

**Relative, deliberately.** `frappe.utils.get_url_to_form` (`frappe/utils/data.py:2000-2011`) returns
an absolute URL including the site host. A host name in model-facing text is both noise and an
avoidable leak.

**Titles are batched and fetched only for kept hits**: one `frappe.get_all` per distinct
`reference_doctype` in the kept set, never one query per hit. `frappe.get_all` is correct here
precisely because the rows it reads have already passed `_may_read`.

**CLAUDE.md rule 3 check — this is the rule's exact edge.** `title` is the record's own title
(company words). The path segments are `/app`, a doctype slug, and a docname; no vendor, platform or
model name appears. It is forbidden, now and later, to put the site URL, the app name, or a label
like "Flow Knowledge Source" into either field.

**Ordering is what makes the contract true.** A title is content. Test 4.1 asserts that no title
reaches a user who may not read the record, and only the ordering makes that assertion hold.

### D4 — the docstring

`retriever.py:10-16` currently states the design this spec removes. It is rewritten in the same
commit. A defence whose own file says it is deliberately absent is the F2 failure class.

### D5 — the test fixture is a core doctype in THIS bench

`ls /home/thivs/code/flow-bench/apps/` → `flow`, `frappe`. No ERPNext, no `q_flow_tools`. So the
fixture must be `frappe` or `flow`.

**`Note` fits, and was verified rather than assumed.** It appears in **both** hooks —
`permission_query_conditions` (`frappe/hooks.py:122`) and `has_permission`
(`frappe/hooks.py:138`) — and its controller hook is
`return bool(doc.public or doc.owner == user)` (`frappe/desk/doctype/note/note.py:81-82`). Its
`title_field` is `title` and its `autoname` is `hash`
(`frappe/desk/doctype/note/note.json`), and role `Desk User` has doctype-level `read`.

So: a **non-public `Note` owned by user A** is readable by A (owner) and not by B — a per-record
restriction enforced through the same controller-hook path `q_flow_tools`' folder rule will use, with
no restriction invented inside the test. No fallback fixture is needed.

## Acceptance criteria

Every test is watched failing first. Every permission test runs as a named non-Administrator user via
the upstream `set_user` context manager (`frappe/tests/classes/context_managers.py:47-56`, registered
on `UnitTestCase`) and asserts `frappe.session.user` **before** searching.

| # | Statement |
|---|---|
| 4.1 | A user who may not read the record gets `[]`: `len(results) == 0`, asserted field by field over the whole structure — no excerpt, no title, no source, no score, no reference anywhere in it. |
| 4.2 | Control: the same query as the user who **may** read it returns the record. Without this, 4.1 passes by returning nothing to anybody. |
| 4.3 | A chunk with `reference_doctype is None` (a `Text` source) is returned exactly as before, to a user with no extra roles. **Backwards compatibility.** |
| 4.5 | Over-fetch: with unreadable records ranking above readable ones, the user still gets up to `limit` readable hits. |
| 4.7a | A hit whose source record has been deleted is dropped, the rest of the search still returns, and nothing names the missing record. |
| 4.7b | A permission check that raises or speaks for any reason drops the hit and reaches the asker with neither. |
| 4.7c | A chunk that names a type but carries no record (or the reverse) is dropped, not kept. |
| 4.7 | A dropped hit produces no message and no raise: `frappe.local.message_log` is empty after a search over a fully-unreadable set, and the call returns `[]`. |
| 4.8 | The tool result the model is handed (`_serialize_tool_result`, `flow/lib/agent.py:728`) contains no substring of the unreadable record — a sweep over the **serialized** JSON, not the dict. |
| 4.11 | The ceiling holds: with more unreadable candidates than the ceiling, the search ends and returns what it has, and the store was asked for no more than `CANDIDATE_CEILING`. |
| 4.12 | `search_knowledge` — the builtin the model calls — goes through this path: the same user gets nothing through the tool either. |
| 5.1 | Every hit from a DocType source carries a non-empty `title` equal to the record's own title field. |
| 5.2 | Every such hit carries `url == "/desk/<doctype-slug>/<name>"` (owner decision, run 9; was `/app/`). |
| 5.3 | A hit from a `Text` source carries the source row's `title` and `url is None`, and does not raise. |
| 5.4 | No returned field contains the site host or any platform, vendor or model name — a literal sweep over the serialized result, with a positive control. |
| 4.10 | `flow/tests/test_knowledge.py` stays green **unmodified**, in particular `test_retrieve_requires_a_knowledge_base` and `test_retrieve_skips_disabled_knowledge_base`. |

## Must not change (N1 §4.5, as it applies in THIS tree)

1. **The write-confirmation path.** `flow/lib/agent.py` `_invoke`, `_resolve_confirmation`,
   `_confirmation_question`, `_has_denial` (CLAUDE.md rule 4). Nothing here goes near them, and
   upstream's `TestAgentConfirmation` stays unmodified and green.
2. **The two existing retrieval gates stay exactly as they are** and the new filter is a third gate,
   never a replacement: an empty `kbs` still throws (`retriever.py:56-60`), and `_enabled_kbs` still
   filters to enabled, existing KBs (`retriever.py:98-101`).
3. **`retrieve_attachments` is not touched** (`retriever.py:31-48`).
4. **No content, title, count, score or existence** of a dropped hit appears anywhere the user or the
   model can see it.
5. **The store schema does not change.** No new LanceDB column, no re-embedding, no rebuild. The
   filter runs after hydration, on MariaDB fields that already exist
   (`flow/knowledge/ingest.py:238-239`).
6. **`frappe.get_all` stays in `_hydrate`** (`retriever.py:105-109`). The permission decision is made
   explicitly in `_may_read`, not smuggled in by switching a query helper: a `get_list` there would
   silently apply a *different* rule — doctype-level `read` on `Flow Knowledge Chunk` — and read as
   if it had solved this.
7. **`search_knowledge`'s signature and description do not change.** The model still sees only
   `query` (`flow/tools/builtins.py:115-125`) and still cannot widen the scope. It must not learn
   that filtering exists.
8. **`search_knowledge` stays in `READ_ONLY`** (`flow/tools/builtins.py:598` — the spec's lead said
   `:579`; it has moved). It reads.

## Files

- `flow/knowledge/retriever.py` — the filter, the over-fetch, the two citation helpers, the docstring.
- `flow/tests/test_knowledge_permissions.py` — new.
- `brain/10-specs/s18-knowledge-read-filter.md`, `.features.json` — this spec and its contract.

## Measured (this laptop, 21 Sep 2026 — not a benchmark)

One search, seven rounds, median, on a fixture of 20 indexed notes (10 the asker may not read,
ranked first, 10 they may), `limit=5`, with a fake embedder so no network call is in the number:

| | median |
|---|---|
| before, as the code shipped (no check, no over-fetch) | **18.25 ms** |
| before, over-fetch present, check neutralised | **20.08 ms** |
| **after, as committed** | **31.52 ms** |

So on this fixture the change costs about **13 ms**: roughly 2 ms of over-fetch (hydrating 20 rows
instead of 5) and roughly 11 ms for the 15 record permission checks it took to collect 5 readable
hits — about **0.7 ms per check**. One laptop, one process, a rolled-back fixture: it says the added
work is bounded and small next to the embedding call a real search makes over the network, and it
says nothing about production data. The five hits the "before" rows returned included records the
asker may not read; the five the "after" row returned did not.

## What this change does NOT close (found in review, recorded not fixed)

1. **`Flow Knowledge Chunk` is readable around the filter by anyone with doctype-level read on it.**
   The doctype grants `{"read": 1, "report": 1, "role": "System Manager"}`, and the generic `read`
   builtin goes through `frappe.get_list` (`flow/tools/builtins.py:97`), which does **not** run
   controller `has_permission` hooks. So a System Manager who may not open another user's private
   record can still ask for that record's indexed chunk content by name. The desk list view and the
   `execute` sandbox are the same door. **Pre-existing, and the remaining path to exactly the data
   this spec promises to withhold.** The fix is its own spec: a
   `permission_query_conditions` + `has_permission` pair on `Flow Knowledge Chunk` applying the same
   reference check, or dropping `read`/`report` on it to Administrator. **A green suite here does not
   mean the one-sentence contract holds against a System Manager.**
   **Run 9 (M2): re-verified and now carried in the machine-readable record too.** The doctype's
   permissions block is exactly `[{"read": 1, "report": 1, "role": "System Manager"}]` and
   `flow/hooks.py` registers **no** `permission_query_conditions` for `Flow Knowledge Chunk` — both
   checked at this branch. The prose above said this; `features.json` did not, and `features.json`
   exists precisely to be the short checkable contract. It now carries **feature 16,
   `"passes": false`**, naming this path open. Feature 1's wording is unchanged and its scope is
   `retrieve()` and `search_knowledge`, which is where it holds.
2. **A count oracle.** The caller learns how many of the top `min(limit * OVERFETCH, ceiling)`
   candidates were withheld, because a short result list can only mean "withheld" or "no more
   matches". Repeated narrowing turns that into existence probing. Open question 3 documents the
   single-hit direction only; this is the aggregate one. Paging deeper until `limit` survivors would
   remove the signal in every case but the ceiling — a product decision, not a test.
3. **`_may_read` is not memoised.** A long record becomes many chunks, and each one pays a full
   check. Bounded by the ceiling, so not a hazard, but a per-`retrieve` cache keyed on
   `(doctype, name)` is the obvious next improvement. Not done here because the ceiling test measures
   the *count* of checks and would have to be rewritten around 100 distinct records.
4. **Over-fetch changes hybrid ranking.** Rank fusion depends on the candidate-set size
   (`flow/knowledge/store.py:135-152`), so "a Text-source hit is returned exactly as before" is
   exactly true only under `search_type = "Vector"`. The keys and values of a given hit are
   unchanged; its position among four times as many candidates may not be.
5. **Field-level (permlevel) read is not applied to the title.** `_may_read` establishes
   document-level read; a title field at `permlevel > 0` would still be returned.
6. **Two messages already reaching the model on this path name the platform** — `store._open_table`'s
   *"Configure Flow Knowledge Settings and ingest a source"* (`flow/knowledge/store.py:165-168`) is a
   live CLAUDE.md rule 3 violation, not introduced here and not fixed here.
7. **Nothing pins the identity inside a trigger run.** Every test drives `retrieve` under
   `set_user`. `flow/triggers/triggers.py:75` runs the agent as `run_as or owner`, so the filter
   should use that identity — read and believed, not measured. A test that runs a trigger with
   `run_as` set to a restricted user is the missing one.

## Open questions (for the owner — not decided here)

1. **`OVERFETCH = 4` is a guess, and the per-call cost of `frappe.has_permission` on real data is
   unmeasured** (N1 §8.1, §8.5). This run measures one search before and after on a test fixture on
   this laptop; that is not a benchmark and must not be read as one. The recall cost (D2) is the
   number that matters and it needs production data.
2. ~~**`/app` versus `/desk`.**~~ **CLOSED by the owner, run 9: `/desk`.** Frappe's canonical desk
   route is `/desk/<path:app_path>` (`frappe/hooks.py:65`) and `/app/(.*)` is a **redirect** to it
   (`frappe/hooks.py:69`) — re-verified in this bench at v16.31.0. `_url_of` now builds
   `{DESK_PATH}/<slug>/<quoted name>` from one constant, and two tests assert the `/desk` form
   (probe PA5: setting `DESK_PATH = "/app"` reddens exactly those two).
3. **A hit dropped for permission is indistinguishable from no match.** That is deliberate (Goal 2),
   but it means a person cannot be told "ask someone who can see that folder". Whether that hand-off
   should exist at all is a product decision.
