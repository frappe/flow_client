# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""The bridge that stops the panel's render tests from being driven by strings somebody made up.

`frontend/tests/confirmCard.spec.js` mounts the real card and asserts on what a person sees. To be
worth anything it has to be driven by a confirmation **the engine really produces**, not by a
hand-written lookalike — the whole failure this run exists to correct is a test that agrees with a
guess about the code instead of with the code.

So the questions live in `frontend/tests/fixtures/confirm_questions.json`, written once from the real
`_confirmation_question`, and THIS module is what keeps them true: it rebuilds every fixture from the
live engine on every gate run and compares byte for byte. Change an escape, a cap, a sentence or the
head format and this goes RED with the exact key that drifted, naming the command that regenerates it.

It is therefore the opposite of `test_s21_confirm_card_source.py`, which reads the component's source
text and proves no render. This one proves the render tests are fed the truth; the JS suite proves
what the truth looks like on screen.

REGENERATE (only after reading what changed and why):
    python3 scripts-free: bench --site flow.localhost console  <<'EOF'
    from flow.tests.test_s21_card_fixture_is_current import write_fixture; write_fixture()
    EOF

KEEP THIS FILE OUT OF ANY UPSTREAM BRANCH: it asserts on a path in `frontend/`.
"""

from __future__ import annotations

import json
import pathlib

import frappe
from frappe.tests import IntegrationTestCase

from flow.lib.agent import _confirmation_question
from flow.lib.model import ToolCall
from flow.tools.builtins import create, delete, execute, run_action

APP = pathlib.Path(frappe.get_app_path("flow"))
FIXTURE = APP.parent / "frontend/tests/fixtures/confirm_questions.json"

RTL = "‮"  # RIGHT-TO-LEFT OVERRIDE — reorders the run of text after it, adding no character
ZWJ = "‍"  # ZERO WIDTH JOINER — occupies no width, so an approver cannot see it at all
FORGED = "\nApproved by admin"  # a newline, then a line that was never the engine's
HUGE = "A" * 50_000


def _cases() -> dict[str, dict]:
	"""Every confirmation the panel's render tests are driven by, each one the engine's own output.

	The arguments are the attacks S21 v2 fixed, so what the JS suite mounts is the real escaped
	body and not a sanitised sample of it.
	"""
	return {
		# Three ways to forge a second question inside the real one, in a single record name.
		"delete_forged_name": dict(
			tool=delete,
			arguments={
				"doctype": "ToDo",
				"names": [f"T-1{RTL}{ZWJ}{FORGED}"],
			},
		),
		# Markup and a markdown image in a field value: displayed, never parsed, never fetched.
		"create_markup_value": dict(
			tool=create,
			arguments={
				"doctype": "ToDo",
				"records": [
					{
						"description": '<script>alert(1)</script><b>bold</b>![x](http://h/i.png)',
					}
				],
			},
		),
		# 50,000 characters in one model-chosen value: capped, with the count OUTSIDE the quotes.
		"run_action_huge_value": dict(
			tool=run_action,
			arguments={"doctype": "ToDo", "names": ["T-1"], "action": HUGE},
		),
		# The one body that keeps real newlines, and is shown WHOLE however long it is.
		"execute_long_code": dict(
			tool=execute,
			arguments={
				"description": "Count the open records",
				"code": "\n".join(f"row_{i} = frappe.get_doc('ToDo', 'T-{i}')" for i in range(40)),
			},
		),
	}


def build() -> dict[str, dict]:
	out: dict[str, dict] = {}
	for key, case in _cases().items():
		tool = case["tool"]
		question = _confirmation_question(
			ToolCall(id="c1", name=tool.name, arguments=case["arguments"]), tool
		)
		out[key] = {
			"prompt": question.prompt,
			"options": list(question.options),
			# Captured because the panel BRANCHES on it: `ConfirmCard` hides the free-text affordance
			# on `allow_other !== false`, and two of the render tests assert that affordance exists.
			# While this field was not in the fixture, an engine that stopped allowing free text would
			# have left this guard green and those two tests proving something production no longer
			# shows. Every field the card reads off a Question belongs here for the same reason.
			"allow_other": question.allow_other,
			"tool": {"name": tool.name, "arguments": case["arguments"]},
		}
	return out


def write_fixture() -> str:
	"""Only ever run by hand, never by a test. A test that writes its own fixture proves nothing."""
	FIXTURE.parent.mkdir(parents=True, exist_ok=True)
	FIXTURE.write_text(json.dumps(build(), indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
	return str(FIXTURE)


class TestTheFixtureIsWhatTheEngineProducesToday(IntegrationTestCase):
	def test_the_fixture_file_exists_and_is_not_empty(self):
		"""The control. A comparison against a file that is missing, or `{}`, is a test that passes
		by reading nothing — the shape of a false green this repository has already shipped once."""
		self.assertTrue(FIXTURE.is_file(), f"{FIXTURE} is missing — the JS suite is driven by nothing")
		self.assertGreater(len(FIXTURE.read_text(encoding="utf-8")), 500)

	def test_every_case_is_present(self):
		stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
		self.assertEqual(sorted(stored), sorted(_cases()), "a case was added or dropped without regenerating")

	def test_each_stored_question_is_byte_identical_to_the_live_engine(self):
		stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
		live = build()
		for key in sorted(live):
			with self.subTest(case=key):
				self.assertEqual(
					stored.get(key),
					live[key],
					f"the engine's confirmation for {key!r} changed. The panel's render tests are now "
					f"driven by a stale string. Read what changed, then regenerate with "
					f"`write_fixture()` in `bench --site flow.localhost console`.",
				)

	def test_the_fixture_really_carries_the_attacks_it_claims_to(self):
		"""A positive control on the fixture's CONTENT, not just its freshness: if a later edit to
		`_cases` quietly dropped the override or the huge value, every assertion above would still
		pass and the JS suite would be mounting harmless text."""
		stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
		self.assertIn("\\u202e", stored["delete_forged_name"]["prompt"])
		self.assertIn("\\n", stored["delete_forged_name"]["prompt"])
		self.assertIn("<script>", stored["create_markup_value"]["tool"]["arguments"]["records"][0]["description"])
		self.assertEqual(len(stored["run_action_huge_value"]["tool"]["arguments"]["action"]), 50_000)
		self.assertIn("\n", stored["execute_long_code"]["prompt"])
		# And the field the panel branches on is really captured, with the value the engine sets, for
		# every case — not merely present in one of them.
		for key in sorted(stored):
			with self.subTest(case=key):
				self.assertIn("allow_other", stored[key])
				self.assertIs(stored[key]["allow_other"], True)
