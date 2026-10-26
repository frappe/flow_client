# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""Every tool that WRITES pauses for confirmation, and that cannot be switched off.

Why this file exists, and not just a flag on each tool: the agent loop walks every tool call in one
assistant turn, and a gated call only `continue`s. An ungated call later in the same turn RUNS
while the person is being asked about the gated one. So an ungated write tool is not "a tool
without a prompt" — it is a tool that fires at the worst possible moment.

WHAT "WRITES" MEANS HERE. It is declared, not detected. The only machine-readable signal available
is `requires_confirmation` itself, and a test that derived "writes" from it would assert that True
implies True. `WRITE_CAPABLE` is maintained by hand in the module it describes, and
`test_every_builtin_is_classified` fails the moment a tool is added to `BUILTIN_TOOLS` without
being put in one list or the other. That failure IS the gate; the assertions below are what it
protects.

WHAT THIS FILE DOES NOT COVER, said plainly rather than left to be assumed:
  - auto_approve. An unattended run with auto_approve set executes every gated tool inline.
    Nothing here asserts anything about that, by design.
  - What happens INSIDE the code-running tool. Its sandbox holds each builtin's raw function, so an
    approved run of it calls the write tools with no further check. That is the design — the code
    is shown in full and the person approved it — and the gate is that tool's own row, asserted
    below.
  - A Script tool written by an administrator. Nothing in the engine can know whether stored Python
    writes. `test_a_new_script_tool_is_gated_by_default` records the exposure and the default that
    now covers it, rather than implying coverage that does not exist.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from flow.tools.builtins import BUILTIN_TOOLS, READ_ONLY, WRITE_CAPABLE, sync_builtin_tools


class TestTheClassificationIsTotal(UnitTestCase):
	"""THE GATE. Everything else in this file asserts a property of a list; only this fails when
	somebody adds a tool."""

	def test_every_builtin_is_classified(self):
		registered = {t.name for t in BUILTIN_TOOLS}
		classified = set(WRITE_CAPABLE) | set(READ_ONLY)

		self.assertEqual(
			registered - classified,
			set(),
			"a builtin is classified nowhere — add it to WRITE_CAPABLE or READ_ONLY and say which",
		)
		self.assertEqual(
			classified - registered,
			set(),
			"a classified tool is no longer registered — remove it from the list",
		)

	def test_the_two_lists_do_not_overlap(self):
		self.assertEqual(set(WRITE_CAPABLE) & set(READ_ONLY), set())

	def test_nothing_gated_can_be_called_read_only(self):
		"""The other half of the gate, and the half that was missing.

		Totality alone is not enough. A maintainer whose classification test has gone red reaches
		first for the quickest repair, which is to move the offending tool into READ_ONLY — and
		that was silent: the whole module stayed green with `execute` (arbitrary code) moved
		across, with its refusal gone. Demonstrated by the code reviewer, not imagined.

		Tying the two lists to the shipped flags closes it. Every write-capable tool ships gated
		and every read-only one ships ungated, so moving a tool between them contradicts its own
		code and goes red on the next run."""
		by_name = {t.name: t for t in BUILTIN_TOOLS}
		mislabelled = sorted(slug for slug in READ_ONLY if by_name[slug].requires_confirmation)
		self.assertEqual(
			mislabelled,
			[],
			f"these are classified read-only but ship gated, so one of the two is wrong: {mislabelled}",
		)

	def test_control_the_registry_is_not_empty(self):
		"""Without this, every assertion in this file passes vacuously on an empty registry."""
		self.assertTrue(BUILTIN_TOOLS)
		self.assertIn("delete", {t.name for t in BUILTIN_TOOLS})

	def test_each_write_is_described_in_words(self):
		"""A classification a reader cannot check is a classification nobody checks."""
		for slug, what in WRITE_CAPABLE.items():
			self.assertTrue(what.strip(), f"{slug} is classified as writing without saying what it writes")


class TestTheShippedCodeGatesEveryWriteTool(UnitTestCase):
	def test_the_shipped_code_gates_every_write_tool(self):
		"""What the module defines — the seed value the sync copies onto each row."""
		ungated = sorted(
			t.name for t in BUILTIN_TOOLS if t.name in WRITE_CAPABLE and not t.requires_confirmation
		)
		self.assertEqual(
			ungated,
			[],
			f"write-capable builtins ship ungated: {ungated}. An ungated write beside a gated one "
			f"executes during the turn that pauses.",
		)

	def test_control_a_read_tool_is_not_gated(self):
		"""Proves the flag being read is the real one and is not True for everything — without
		this, the assertion above would pass on a constant."""
		by_name = {t.name: t for t in BUILTIN_TOOLS}
		self.assertIn("read", by_name)
		self.assertFalse(by_name["read"].requires_confirmation)


class TestTheRowsThatActuallyRun(IntegrationTestCase):
	"""What PRODUCTION uses. The runtime takes the ROW's checkbox, not the code's flag, so the
	assertions above do not cover this and an administrator's edit would not be caught by them."""

	def tearDown(self):
		frappe.db.rollback()

	def test_the_rows_gate_every_write_tool(self):
		sync_builtin_tools()
		rows = frappe.get_all(
			"Flow Tool",
			filters={"name": ["in", sorted(WRITE_CAPABLE)]},
			fields=["name", "requires_confirmation"],
		)

		self.assertEqual({r.name for r in rows}, set(WRITE_CAPABLE), "the sync did not create every row")
		ungated = sorted(r.name for r in rows if not r.requires_confirmation)
		self.assertEqual(ungated, [], f"rows that write but do not confirm: {ungated}")

	def test_the_runtime_tool_resolved_from_the_row_is_gated(self):
		"""End to end, through the path an agent actually takes: row -> to_tool()."""
		sync_builtin_tools()
		for slug in sorted(WRITE_CAPABLE):
			self.assertTrue(
				frappe.get_doc("Flow Tool", slug).to_tool().requires_confirmation, f"{slug} resolves ungated"
			)

	def test_probe_unchecking_a_row_is_what_this_would_catch(self):
		"""THE MUTATION, performed in-process and rolled back. A gate whose failure mode has never
		been observed is a comment: this makes the failure happen on purpose, proves the row
		assertion above sees it, and leaves the row as it was.

		It writes through db.set_value on purpose — that is how the sync writes the field, and it
		is the one route that does not pass through the refusal, so it is also the honest
		demonstration of what the refusal does not cover.

		And then the half that is new: the RUNTIME does not follow the record down. The record now
		says no approval and the tool resolved from it still asks, because an imported function
		that declares its own approval keeps it whatever a record says. So the route the refusal
		cannot close is no longer a route to an ungated write — it is a record that disagrees with
		its own code until the next deploy corrects it."""
		sync_builtin_tools()
		frappe.db.set_value("Flow Tool", "delete", "requires_confirmation", 0)

		rows = frappe.get_all(
			"Flow Tool",
			filters={"name": ["in", sorted(WRITE_CAPABLE)]},
			fields=["name", "requires_confirmation"],
		)
		self.assertEqual(sorted(r.name for r in rows if not r.requires_confirmation), ["delete"])
		self.assertTrue(frappe.get_doc("Flow Tool", "delete").to_tool().requires_confirmation)
		# tearDown's rollback restores the row.

	def test_the_sync_repairs_a_row_that_was_turned_off(self):
		"""The only thing that repairs a site rather than preventing the next mistake. Nothing
		asserted it before, so a gate could have been turned off and silently stayed off."""
		sync_builtin_tools()
		frappe.db.set_value("Flow Tool", "delete", "requires_confirmation", 0)
		self.assertFalse(frappe.db.get_value("Flow Tool", "delete", "requires_confirmation"))

		sync_builtin_tools()

		self.assertTrue(frappe.db.get_value("Flow Tool", "delete", "requires_confirmation"))


class TestTheGateCannotBeUnsetFromARecord(IntegrationTestCase):
	"""The desk edit this spec exists to refuse: one checkbox, one save, and from the next turn the
	model deletes records with nobody asked."""

	def tearDown(self):
		frappe.db.rollback()

	def test_saving_a_write_tool_ungated_is_refused(self):
		sync_builtin_tools()
		row = frappe.get_doc("Flow Tool", "delete")
		row.requires_confirmation = 0

		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)

	def test_the_refusal_names_the_tool(self):
		sync_builtin_tools()
		row = frappe.get_doc("Flow Tool", "run_action")
		row.requires_confirmation = 0

		with self.assertRaisesRegex(frappe.ValidationError, "run_action"):
			row.save(ignore_permissions=True)

	def test_it_holds_for_every_write_capable_builtin(self):
		"""No rollback inside the loop: in an integration test that unwinds the runner's own
		transaction, not a savepoint, and would discard fixtures a later test depends on. The
		throw leaves the row untouched in the database anyway, so a fresh read is all that is
		needed between slugs."""
		sync_builtin_tools()
		for slug in sorted(WRITE_CAPABLE):
			with self.subTest(slug=slug):
				row = frappe.get_doc("Flow Tool", slug)
				row.requires_confirmation = 0
				with self.assertRaises(frappe.ValidationError, msg=f"{slug} could be unset"):
					row.save(ignore_permissions=True)
				self.assertTrue(frappe.db.get_value("Flow Tool", slug, "requires_confirmation"))

	def test_it_holds_on_insert_too(self):
		"""A row created ungated under one of those slugs would be the same hole, reached by a
		different verb."""
		# The row is not deleted first: these rows cannot be deleted (block_delete(always=True)),
		# and they do not need to be. `insert` runs validate before it writes, so the refusal is
		# reached on the insert path exactly as it is on the save path — which is the thing being
		# asserted. A duplicate would be a different error and would fail this test.
		with self.assertRaisesRegex(frappe.ValidationError, "delete"):
			frappe.get_doc(
				{
					"doctype": "Flow Tool",
					"slug": "delete",
					"title": "Delete",
					"type": "Imported",
					"import_path": "flow.tools.builtins.delete",
					"description": "Delete records.",
					"requires_confirmation": 0,
				}
			).insert(ignore_permissions=True)

	def test_control_a_read_tool_can_still_be_saved_ungated(self):
		"""Without this the refusal above could be refusing every save of every row."""
		sync_builtin_tools()
		row = frappe.get_doc("Flow Tool", "read")
		row.requires_confirmation = 0
		row.save(ignore_permissions=True)

		self.assertFalse(frappe.db.get_value("Flow Tool", "read", "requires_confirmation"))

	def test_turning_the_gate_ON_is_never_refused(self):
		"""The rule is one-directional on purpose: it refuses the unsafe change only."""
		sync_builtin_tools()
		row = frappe.get_doc("Flow Tool", "read")
		row.requires_confirmation = 1
		row.save(ignore_permissions=True)

		self.assertTrue(frappe.db.get_value("Flow Tool", "read", "requires_confirmation"))


class TestTheGateSurvivesBeingRenamedOrCopied(IntegrationTestCase):
	"""Two routes the security review found, both ordinary record saves — no script, no raw SQL.

	The refusal keys on the slug; the runtime executes the import path. Nothing tied the two, so a
	name was enough to step outside the classification. One route was never repaired by a deploy,
	because the sync only ever visits records named for a builtin."""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_second_record_importing_a_write_function_is_still_gated(self):
		"""The same function object under a name this list has never heard of."""
		alias = frappe.get_doc(
			{
				"doctype": "Flow Tool",
				"slug": "purge_records",
				"title": "Purge Records",
				"type": "Imported",
				"import_path": "flow.tools.builtins.delete",
				"description": "Delete records.",
				"requires_confirmation": 0,
			}
		).insert(ignore_permissions=True)

		# The record says no approval. What runs is the shipped delete, which says otherwise.
		self.assertFalse(alias.requires_confirmation)
		self.assertTrue(alias.to_tool().requires_confirmation)

	def test_control_a_read_function_imported_under_a_new_name_is_not_gated(self):
		"""Without this the assertion above would pass on a runtime that gated everything."""
		alias = frappe.get_doc(
			{
				"doctype": "Flow Tool",
				"slug": "peek_records",
				"title": "Peek Records",
				"type": "Imported",
				"import_path": "flow.tools.builtins.read",
				"description": "Read records.",
				"requires_confirmation": 0,
			}
		).insert(ignore_permissions=True)

		self.assertFalse(alias.to_tool().requires_confirmation)

	def test_a_shipped_records_slug_cannot_be_changed(self):
		"""The other route: the record keeps its name when its slug changes, so the rename guard
		never fired — and one save both moved the record out of the classification and unchecked
		the approval."""
		sync_builtin_tools()
		row = frappe.get_doc("Flow Tool", "delete")
		row.slug = "zap"
		row.requires_confirmation = 0

		# A desk save, not `ignore_permissions`: the immutability guard steps aside for the owning
		# app on purpose, and the route being closed here is a person editing the record.
		with self.assertRaises(frappe.ValidationError):
			row.save()


class TestANewToolIsGatedUntilSomebodySaysOtherwise(IntegrationTestCase):
	"""A Script tool is arbitrary Python in a sandbox that can write, and nothing in the engine can
	classify it. The default is the only protection available, so it is the gated one."""

	def tearDown(self):
		frappe.db.rollback()

	def _script(self, slug: str, **overrides) -> dict:
		doc = {
			"doctype": "Flow Tool",
			"slug": slug,
			"title": slug.replace("_", " ").title(),
			"type": "Script",
			"description": "A hand-written tool.",
			"code": "def main(x: str):\n\treturn x\n",
		}
		doc.update(overrides)
		return doc

	def test_the_shipped_doctype_declares_the_gated_default(self):
		"""Feature 9 on the FILE. The behavioural test below reads the site, and a site only gets
		the default when it migrates — so reverting the line in the repository would leave that
		test green until somebody deployed. One pins the artefact, the other pins the site."""
		import json
		from pathlib import Path as _Path

		import flow

		schema = json.loads(
			(_Path(flow.__file__).parent / "flow" / "doctype" / "flow_tool" / "flow_tool.json").read_text()
		)
		field = next(f for f in schema["fields"] if f["fieldname"] == "requires_confirmation")
		self.assertEqual(field.get("default"), "1")

	def test_an_explicit_choice_still_beats_the_default(self):
		"""The mechanism D4's "builtin rows are unaffected" rests on: a default fills a field that
		was not given, and never overrides one that was. Without this the claim is a comment, and
		the sync creating read tools ungated on a fresh install depends on it."""
		doc = frappe.get_doc(self._script("s16b_explicit_zero", requires_confirmation=0)).insert(
			ignore_permissions=True
		)

		self.assertFalse(doc.requires_confirmation)

	def test_a_new_script_tool_is_gated_by_default(self):
		doc = frappe.get_doc(self._script("s16b_default_probe")).insert(ignore_permissions=True)

		self.assertTrue(
			doc.requires_confirmation,
			"a hand-written tool that can write anything was created ungated",
		)

	def test_its_author_can_still_turn_the_gate_off(self):
		"""The default is a default, not a rule. A Script tool is not in WRITE_CAPABLE — nothing
		can know whether it writes — so its author decides."""
		doc = frappe.get_doc(self._script("s16b_optout_probe")).insert(ignore_permissions=True)
		doc.requires_confirmation = 0
		doc.save(ignore_permissions=True)

		self.assertFalse(frappe.db.get_value("Flow Tool", "s16b_optout_probe", "requires_confirmation"))


class TestNothingNamesThePlatform(UnitTestCase):
	"""CLAUDE.md rule 3, over the one new string a person reads."""

	FORBIDDEN = ("frappe", "flow", "erpnext", "mariadb", "openai", "anthropic", "gpt", "claude")

	def test_the_refusal_message_names_no_platform(self):
		from flow.flow.doctype.flow_tool.flow_tool import GATE_REQUIRED_MESSAGE

		for word in self.FORBIDDEN:
			self.assertNotIn(word, GATE_REQUIRED_MESSAGE.lower())

	def test_control_the_message_is_not_empty(self):
		from flow.flow.doctype.flow_tool.flow_tool import GATE_REQUIRED_MESSAGE

		self.assertTrue(GATE_REQUIRED_MESSAGE.strip())
		self.assertIn("{0}", GATE_REQUIRED_MESSAGE)
