# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt
"""How an approval question is worded.

Nothing here touches what executes, or on which answer. That is `TestAgentConfirmation` in
test_ai_agent.py, which stays green and unmodified.

The question is assembled by substitution, not by an engine. The tests below are mostly attacks:
each one is a way someone tried, or could try, to make a person approve something other than what
they were shown.
"""

import json
import pathlib
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flow.lib.agent import CONFIRM_VALUE_LIMIT

ARGUMENTS = {"amount": 4200, "customer": "Acme"}
DUMP = json.dumps(ARGUMENTS, indent=2, default=str)


class TestTheSentenceIsSubstitutedNotEvaluated(IntegrationTestCase):
	"""`{name}` is replaced by the argument called `name`. That is the whole grammar."""

	def _render(self, template, arguments=None):
		from flow.lib.agent import _render_confirm_template

		return _render_confirm_template(template, ARGUMENTS if arguments is None else arguments)

	def test_a_placeholder_is_replaced_by_its_argument_in_quotes(self):
		"""The positive control every refusal below is measured against."""
		self.assertEqual(self._render("Post {amount} for {customer}."), 'Post "4200" for "Acme".')

	def test_the_sentence_is_one_line_however_the_author_wrote_it(self):
		self.assertEqual(self._render("Post\n\t{amount}\n  for  {customer}."), 'Post "4200" for "Acme".')

	def test_an_empty_or_whitespace_only_sentence_is_no_sentence(self):
		for template in ("", "   ", "\n\n", "\t"):
			with self.subTest(template=repr(template)):
				self.assertIsNone(self._render(template))
		self.assertIsNotNone(self._render("Post {amount}."))  # positive control

	def test_an_expression_is_not_evaluated_it_is_literal_text(self):
		"""The grammar has no expressions, so there is nothing for these to be interpreted as."""
		for template, must_survive in (
			("Post {{ amount }}.", "{{ amount }}"),
			("Post {amount * 2}.", "{amount * 2}"),
			("Post {amount|upper}.", "{amount|upper}"),
			("Post {amount.__class__}.", "{amount.__class__}"),
			("Post {amount[0]}.", "{amount[0]}"),
			("Post {% if amount %}yes{% endif %}.", "{% if amount %}yes{% endif %}"),
			("Post {0} and {1}.", "{0}"),
			("Post {amount!r}.", "{amount!r}"),
			("Post {amount:>20}.", "{amount:>20}"),
			("Post {AMOUNT}.", "{AMOUNT}"),
		):
			with self.subTest(template=template):
				rendered = self._render(template)
				self.assertIsNotNone(rendered)
				self.assertIn(must_survive, rendered)
				self.assertNotIn("4200", rendered)

	def test_a_doubled_brace_substitutes_its_inner_name_and_shows_the_outer_braces(self):
		"""Said plainly rather than left to be discovered: `{{amount}}` is `{` then `{amount}`
		then `}`, so the name is substituted and the surviving braces show it was not an
		expression. Only `{{ amount }}`, with the spaces jinja is written with, stays whole."""
		self.assertEqual(self._render("Post {{amount}}."), 'Post {"4200"}.')
		self.assertEqual(self._render("Post {{ amount }}."), "Post {{ amount }}.")

	def test_a_database_call_written_into_the_field_stays_literal_text(self):
		"""An earlier design rendered this with a template engine, and it ran. `{{ frappe.db.sql(...) }}` executed inside the question —
		before anyone approved anything, and even if they went on to refuse."""
		template = "Delete {{ frappe.db.sql('DROP TABLE tabUser') }} for {customer}."

		def never(*args, **kwargs):
			raise AssertionError("the question reached the database")

		with (
			patch.object(frappe.db, "sql", side_effect=never),
			patch.object(frappe.db, "get_value", side_effect=never),
			patch.object(frappe.db, "get_all", side_effect=never),
			patch.object(frappe, "get_all", side_effect=never),
			patch.object(frappe, "get_doc", side_effect=never),
		):
			rendered = self._render(template)

		self.assertEqual(rendered, "Delete {{ frappe.db.sql('DROP TABLE tabUser') }} for \"Acme\".")

	def test_rendering_reads_nothing_at_all_beyond_its_two_arguments(self):
		"""Not the database, not the session, not the record. Patched to raise, so a read is a
		failure rather than a silently different answer."""

		def never(*args, **kwargs):
			raise AssertionError("the question read something it should not have")

		with (
			patch.object(frappe.db, "sql", side_effect=never),
			patch.object(frappe.db, "get_value", side_effect=never),
			patch.object(frappe.db, "get_all", side_effect=never),
			patch.object(frappe, "get_all", side_effect=never),
			patch.object(frappe, "get_doc", side_effect=never),
			patch.object(frappe, "get_cached_doc", side_effect=never),
		):
			self.assertEqual(self._render("Post {amount} for {customer}."), 'Post "4200" for "Acme".')

	def test_rendering_never_raises(self):
		"""A badly written question must not be able to stop a person being asked.

		The first two cases are the ones that actually reach the guard: `json.dumps` refuses an
		integer of more than 4300 digits, and `arguments` that is not a mapping fails the lookup.
		Without the `try`, each of them raises out of the approval path. Called directly rather
		than through the helper, whose default would turn `None` back into real arguments.
		"""
		from flow.lib.agent import _render_confirm_template

		for template, arguments in (
			("{amount}", {"amount": 10**5000}),
			("{amount}", None),
			("{amount}", ["not", "a", "mapping"]),
			("{amount}", {"amount": object()}),
			("{amount}", {}),
			("{amount}", {"amount": b"bytes"}),
		):
			with self.subTest(refused=template[:20], arguments=type(arguments).__name__):
				self.assertIsNone(_render_confirm_template(template, arguments))

		# Not refusals — these render. They are here because they are the shapes most likely to
		# blow up a renderer, and they must come back as text rather than as an exception.
		self.assertEqual(self._render("{amount}", {"amount": float("nan")}), '"NaN"')
		self.assertIsNotNone(self._render("{" * 500 + "amount" + "}" * 500, ARGUMENTS))

	def test_a_sentence_too_long_once_filled_in_is_abandoned_not_cut(self):
		"""The fourth abandon condition. A short sentence can still be long once filled in."""
		from flow.lib.agent import CONFIRM_BODY_LIMIT

		value = "B" * (CONFIRM_VALUE_LIMIT - 1)
		per_slot = CONFIRM_VALUE_LIMIT + 1  # the two quotes are outside the value's own cap
		slots = CONFIRM_BODY_LIMIT // per_slot + 1
		self.assertGreater(slots * per_slot, CONFIRM_BODY_LIMIT)
		self.assertIsNone(self._render("{c}" * slots, {"c": value}))
		self.assertIsNotNone(self._render("{c}" * (slots - 1), {"c": value}))  # positive control

	def test_no_template_engine_is_reachable_from_this_path(self):
		"""A zero-hits search proves nothing on its own, so the same search is run against a
		string that must match. The point of this test is that it fails the day someone reaches
		for an engine again."""
		import re

		banned = re.compile(r"jinja|get_jenv|render_template|safe_eval|from_string|StrictUndefined")
		self.assertTrue(banned.search("from frappe.utils.jinja import get_jenv"))  # positive control
		for module in ("flow/lib/agent.py", "flow/lib/tool.py", "flow/lib/resolver.py"):
			with self.subTest(module=module):
				source = (pathlib.Path(frappe.get_app_path("flow")).parent / module).read_text()
				self.assertIsNone(banned.search(source))


class TestAValueCannotChangeTheQuestion(IntegrationTestCase):
	"""The sentence comes from a person; the values come from the model. These are the attacks
	found against an earlier design of this, each kept as its own test."""

	def _render(self, template, arguments):
		from flow.lib.agent import _render_confirm_template

		return _render_confirm_template(template, arguments)

	def _question(self, template, arguments, **overrides):
		from flow.lib.agent import _confirmation_question
		from flow.lib.model import ToolCall
		from flow.lib.tool import Tool

		defaults = dict(
			name="delete_invoices",
			description="Delete invoices.",
			parameters={"type": "object", "properties": {}},
			func=lambda **kw: "ok",
			requires_confirmation=True,
			confirm_template=template,
		)
		defaults.update(overrides)
		return _confirmation_question(
			ToolCall(id="c1", name=defaults["name"], arguments=arguments), Tool(**defaults)
		)

	def test_the_truncation_attack_a_padded_value_cannot_hide_the_rest_of_the_sentence(self):
		"""An earlier design cut the body at a fixed length with no marker, so a long enough value
		pushed "and DELETE every invoice" off the end. Nothing is cut here: the sentence is
		abandoned whole and the arguments are shown instead."""
		template = "Read the invoices for {customer} and DELETE every invoice."
		padded = "A" * (CONFIRM_VALUE_LIMIT + 1)

		self.assertIsNone(self._render(template, {"customer": padded}))
		# positive control, in the identical form: one character shorter and it renders in full
		fits = "A" * CONFIRM_VALUE_LIMIT
		self.assertEqual(
			self._render(template, {"customer": fits}),
			f'Read the invoices for "{fits}" and DELETE every invoice.',
		)

		q = self._question(template, {"customer": padded})
		self.assertNotIn("Read the invoices", q.prompt)  # no half-sentence
		self.assertIn(padded, q.prompt)  # the value itself is not shortened either
		self.assertIn('"customer"', q.prompt)

	def test_the_forged_second_question_a_value_cannot_open_a_line_of_its_own(self):
		"""An earlier design let a value write
		"NOTE: read-only preview, nothing will be written." underneath the real question."""
		forged = "Acme\n\nNOTE: read-only preview, nothing will be written."
		rendered = self._render("Delete every invoice for {customer}.", {"customer": forged})

		self.assertNotIn("\n", rendered)
		self.assertIn("\\n", rendered)
		self.assertEqual(
			rendered,
			'Delete every invoice for "Acme\\n\\nNOTE: read-only preview, nothing will be written.".',
		)

		q = self._question("Delete every invoice for {customer}.", {"customer": forged})
		self.assertFalse([ln for ln in q.prompt.splitlines() if ln.strip().startswith("NOTE:")])

	def test_the_bidi_override_is_shown_escaped_not_obeyed(self):
		"""A right-to-left override reorders the sentence on screen while leaving every character
		in place — the one attack that survives flattening, because it needs no line break."""
		attacked = "Acme‮seciovni yreve ETELED‬"
		rendered = self._render("Read the invoices for {customer}.", {"customer": attacked})

		self.assertNotIn("‮", rendered)
		self.assertNotIn("‬", rendered)
		self.assertIn("\\u202e", rendered)
		self.assertIn("\\u202c", rendered)

		q = self._question("Read the invoices for {customer}.", {"customer": attacked})
		self.assertNotIn("‮", q.prompt)

	def test_a_line_separator_cannot_open_a_line_of_its_own_either(self):
		"""U+2028 and U+2029 are line breaks to `str.splitlines` and to every layout engine, but
		they are categories Zl and Zp — so a rule that escaped only Cc and Cf let this through and
		the forged second question above worked again, unchanged apart from the character."""
		forged = "Acme\u2028\u2028NOTE: read-only preview, nothing will be written."
		rendered = self._render("Delete every invoice for {customer}.", {"customer": forged})

		self.assertEqual(len(rendered.splitlines()), 1)
		self.assertIn("\\u2028", rendered)
		q = self._question("Delete every invoice for {customer}.", {"customer": forged})
		self.assertFalse([ln for ln in q.prompt.splitlines() if ln.strip().startswith("NOTE:")])

	def test_everything_that_is_not_printable_is_escaped_and_the_space_is_not(self):
		"""A whitelist, not a list of the characters that have caused trouble so far."""
		for code, category in (
			(0x2028, "Zl"),
			(0x2029, "Zp"),
			(0x00A0, "Zs"),
			(0x3000, "Zs"),
			(0x0085, "Cc"),
			(0x200B, "Cf"),
			(0x202E, "Cf"),
			(0xD800, "Cs"),
			(0xE000, "Co"),
			(0x0378, "Cn"),
		):
			with self.subTest(code=hex(code), category=category):
				import unicodedata

				self.assertEqual(unicodedata.category(chr(code)), category)
				rendered = self._render("Post {c}.", {"c": f"a{chr(code)}b"})
				# Compared as ascii: a lone surrogate in a FAILURE message cannot be printed at
				# all, and a test that crashes the runner when it fails is not a test.
				self.assertEqual(ascii(rendered), ascii(f'Post "a\\u{code:04x}b".'))
		self.assertEqual(self._render("Post {c}.", {"c": "a b"}), 'Post "a b".')  # positive control

	def test_an_astral_format_character_is_escaped_unambiguously(self):
		"""U+E0001 is a tag character — invisible, and the shape a hidden instruction takes. Above
		the BMP it needs eight digits: four would read as U+E000 followed by "1"."""
		self.assertEqual(self._render("Post {c}.", {"c": "hi\U000e0001"}), 'Post "hi\\U000e0001".')

	def test_a_value_shaped_like_a_format_specifier_is_only_text(self):
		"""The body is joined to the first line, never passed to a formatter."""
		for value in ("{0}", "{1}", "%s", "%(customer)s", "{body}", "{{0}}"):
			with self.subTest(value=value):
				q = self._question("Post {customer}.", {"customer": value})
				self.assertIn(f'Post "{value}".', q.prompt)

	def test_a_tab_and_a_carriage_return_are_shown_escaped_too(self):
		rendered = self._render("Post {customer}.", {"customer": "a\tb\rc\x00d"})
		self.assertEqual(rendered, 'Post "a\\tb\\rc\\u0000d".')

	def test_a_value_cannot_close_the_quotes_that_hold_it(self):
		rendered = self._render("Post {customer}.", {"customer": 'Acme" and DELETE all "x'})
		self.assertEqual(rendered, 'Post "Acme\\" and DELETE all \\"x".')

	def test_a_backslash_in_a_value_is_unambiguous(self):
		"""Without escaping the backslash, a value containing the two characters `\\n` and a value
		containing a real newline would read identically."""
		literal = self._render("Post {customer}.", {"customer": "a\\nb"})
		real = self._render("Post {customer}.", {"customer": "a\nb"})
		self.assertEqual(literal, 'Post "a\\\\nb".')
		self.assertEqual(real, 'Post "a\\nb".')
		self.assertNotEqual(literal, real)

	def test_a_value_of_201_characters_drops_the_sentence_and_200_does_not(self):
		self.assertIsNone(self._render("Post {customer}.", {"customer": "A" * 201}))
		self.assertIsNotNone(self._render("Post {customer}.", {"customer": "A" * 200}))

	def test_a_value_that_escapes_past_the_cap_drops_the_sentence(self):
		"""The cap is on what is SHOWN, and escaping only lengthens."""
		self.assertIsNone(self._render("Post {customer}.", {"customer": "\n" * 101}))
		self.assertIsNotNone(self._render("Post {customer}.", {"customer": "\n" * 100}))

	def test_a_missing_argument_drops_the_sentence_rather_than_leaving_a_hole(self):
		self.assertIsNone(self._render("Post {amount} to {nobody_supplied_this}.", ARGUMENTS))
		q = self._question("Post {amount} to {nobody_supplied_this}.", ARGUMENTS)
		self.assertNotIn("Post ", q.prompt)
		self.assertIn('"amount": 4200', q.prompt)

	def test_an_argument_that_is_not_a_single_value_drops_the_sentence(self):
		for value in ([1, 2], {"a": 1}, None, object()):
			with self.subTest(value=type(value).__name__):
				self.assertIsNone(self._render("Post {amount}.", {"amount": value}))
		for value in ("Acme", 4200, 42.5, True):  # positive controls, identical form
			with self.subTest(value=type(value).__name__):
				self.assertIsNotNone(self._render("Post {amount}.", {"amount": value}))

	def test_a_number_and_a_boolean_read_the_way_they_will_execute(self):
		self.assertEqual(self._render("Post {amount}.", {"amount": True}), 'Post "true".')
		self.assertEqual(self._render("Post {amount}.", {"amount": 42.5}), 'Post "42.5".')


class TestTheArgumentsAreAlwaysShown(IntegrationTestCase):
	"""An administrator's wording is never the only thing a person sees. This rules out the
	misleading question as a class of attack, rather than trying to detect one."""

	def _question(self, arguments=None, **overrides):
		from flow.lib.agent import _confirmation_question
		from flow.lib.model import ToolCall
		from flow.lib.tool import Tool

		defaults = dict(
			name="delete_invoices",
			description="Delete invoices.",
			parameters={"type": "object", "properties": {}},
			func=lambda **kw: "ok",
			requires_confirmation=True,
		)
		defaults.update(overrides)
		return _confirmation_question(
			ToolCall(id="c1", name=defaults["name"], arguments=ARGUMENTS if arguments is None else arguments),
			Tool(**defaults),
		)

	def test_a_template_that_misdescribes_the_tool_still_shows_what_will_execute(self):
		arguments = {"customer": "Acme", "delete_all": True, "confirm": "yes"}
		q = self._question(arguments, confirm_template="Read the invoices for {customer}.")

		self.assertIn('Read the invoices for "Acme".', q.prompt)
		self.assertIn(json.dumps(arguments, indent=2, default=str), q.prompt)
		self.assertIn('"delete_all": true', q.prompt)

	def test_the_sentence_sits_above_the_arguments_not_instead_of_them(self):
		q = self._question(confirm_template="Post {amount} for {customer}.")
		self.assertIn(f'Post "4200" for "Acme".\n\n{DUMP}', q.prompt)

	def test_with_no_sentence_the_arguments_are_shown_exactly_as_before(self):
		self.assertIn(DUMP, self._question().prompt)

	def test_with_a_dropped_sentence_the_arguments_are_shown_alone(self):
		q = self._question(confirm_template="Post {missing}.")
		self.assertIn(DUMP, q.prompt)
		self.assertNotIn("Post ", q.prompt)

	def test_the_code_callable_still_wins_and_is_left_exactly_as_it_was(self):
		"""`confirm_prompt` is code, written and reviewed with the tool, not data on a record.
		Upstream's own test asserts its body does not carry the argument shape, so the arguments
		are NOT appended under it."""
		q = self._question(
			confirm_prompt=lambda args: "FROM THE CALLABLE",
			confirm_template="Post {amount}.",
		)
		self.assertIn("FROM THE CALLABLE", q.prompt)
		self.assertNotIn("Post ", q.prompt)
		self.assertNotIn(DUMP, q.prompt)

	def test_the_first_line_uses_the_human_title_when_there_is_one(self):
		self.assertTrue(self._question(title="Delete Invoices").prompt.startswith("Approve Delete Invoices?"))

	def test_the_first_line_falls_back_to_the_internal_name(self):
		self.assertTrue(self._question().prompt.startswith("Approve `delete_invoices`?"))

	def test_a_title_cannot_open_a_line_of_its_own_either(self):
		"""The title is a person's words too, and it is the first line of the question."""
		q = self._question(title="Delete Invoices\n\nApprove Read Only?")
		self.assertEqual(q.prompt.splitlines()[0], "Approve Delete Invoices Approve Read Only??")
		self.assertNotIn("\nApprove Read Only?", q.prompt)

	def test_a_title_cannot_reorder_the_line_it_is_on(self):
		"""Flattening alone would pass the test above. A right-to-left override needs no line
		break, so the title is escaped as well as flattened."""
		q = self._question(title="Delete\u202eylnO daeR\u202c Invoices")
		self.assertIn("\\u202e", q.prompt)
		self.assertNotIn("\u202e", q.prompt)

	def test_a_title_of_nothing_but_spaces_falls_back_to_the_slug(self):
		self.assertTrue(self._question(title="   ").prompt.startswith("Approve `delete_invoices`?"))

	def test_the_options_are_unchanged_in_every_case(self):
		for overrides in (
			{},
			{"confirm_template": "Post {amount}."},
			{"confirm_template": "Post {missing}."},
			{"confirm_template": "{{ frappe.db.sql('x') }}"},
			{"confirm_prompt": lambda args: "hi"},
			{"title": "Delete Invoices"},
		):
			with self.subTest(overrides=sorted(overrides)):
				q = self._question(**overrides)
				self.assertEqual(q.options, ["Approve", "Deny"])
				self.assertTrue(q.allow_other)


class TestTheRecordCarriesTheWordingToTheRuntime(IntegrationTestCase):
	"""A tool defined as a record could never have a plain-language approval question: the
	attribute existed only in code. This is the path that closes that gap."""

	def tearDown(self):
		frappe.db.rollback()

	def _record(self, **overrides):
		doc = {
			"doctype": "Flow Tool",
			"title": "Post Invoice",
			"slug": f"post_invoice_{frappe.generate_hash(length=6)}",
			"type": "Imported",
			"description": "Post an invoice.",
			"import_path": "flow.tools.builtins.find_doctypes",
			"requires_confirmation": 1,
		}
		doc.update(overrides)
		return frappe.get_doc(doc).insert(ignore_permissions=True)

	def test_the_field_persists_and_is_optional(self):
		with_template = self._record(confirm_template="Post {amount}.")
		without = self._record()
		self.assertEqual(
			frappe.db.get_value("Flow Tool", with_template.name, "confirm_template"), "Post {amount}."
		)
		self.assertFalse(frappe.db.get_value("Flow Tool", without.name, "confirm_template"))

	def test_the_runtime_tool_carries_the_title_and_the_sentence(self):
		runtime = self._record(confirm_template="Post {amount}.").to_tool()
		self.assertEqual(runtime.title, "Post Invoice")
		self.assertEqual(runtime.confirm_template, "Post {amount}.")
		self.assertTrue(runtime.requires_confirmation)

	def test_a_tool_defined_in_code_carries_neither(self):
		from flow.lib.tool import tool

		@tool(requires_confirmation=True)
		def write_file(path: str) -> str:
			"""Write a file."""
			return path

		self.assertIsNone(write_file.title)
		self.assertIsNone(write_file.confirm_template)

	def test_a_script_tool_can_have_one_too(self):
		"""Script tools could never carry a code callable at all, so they were stuck with the
		raw arguments no matter what."""
		runtime = self._record(
			type="Script",
			import_path=None,
			code="def main(amount: float) -> str:\n\treturn str(amount)\n",
			confirm_template="Post {amount}.",
		).to_tool()
		self.assertEqual(runtime.confirm_template, "Post {amount}.")

	def test_a_record_written_before_the_field_existed_still_asks(self):
		"""A site that has not migrated has no such column. Attribute access on a Document raises,
		which would take out every tool, not only the ones with a sentence written on them."""
		from flow.lib.resolver import _build_tool

		doc = self._record()
		del doc.confirm_template
		built = _build_tool(doc, {"type": "object", "properties": {}}, lambda **kw: "ok")
		self.assertIsNone(built.confirm_template)

	def test_a_sentence_is_stored_as_it_was_measured(self):
		"""Padding is not a way past the cap: 999 characters and 5000 spaces is not 999 stored."""
		doc = self._record(confirm_template="  Post {amount}.   ")
		self.assertEqual(doc.confirm_template, "Post {amount}.")
		self.assertIsNone(self._record(confirm_template="   ").confirm_template)

	def test_a_sentence_too_long_to_read_is_refused_when_it_is_written(self):
		from flow.flow.doctype.flow_tool.flow_tool import CONFIRM_TEMPLATE_LIMIT

		self._record(confirm_template="A" * CONFIRM_TEMPLATE_LIMIT)  # positive control
		with self.assertRaises(frappe.ValidationError):
			self._record(confirm_template="A" * (CONFIRM_TEMPLATE_LIMIT + 1))


class TestTheApprovalGateIsUnmovedByTheWording(IntegrationTestCase):
	"""The wording changed; the decision did not. Only the exact "Approve" executes."""

	def tearDown(self):
		frappe.db.rollback()

	def _agent_with_templated_tool(self):
		from flow.lib.agent import Agent
		from flow.lib.tool import Tool

		executed: list = []

		def post(amount: float) -> str:
			executed.append(amount)
			return f"posted {amount}"

		templated = Tool(
			name="post_invoice",
			description="Post an invoice.",
			parameters={
				"type": "object",
				"properties": {"amount": {"type": "number"}},
				"additionalProperties": False,
				"required": ["amount"],
			},
			func=post,
			requires_confirmation=True,
			title="Post Invoice",
			confirm_template="Post an invoice for {amount}.",
		)
		return Agent, templated, executed

	def _model(self, responses):
		from flow.lib.model import ChatResponse, ToolCall

		class Scripted:
			model_id = "openai/gpt-4o-mini"

			def __init__(self, rs):
				self._rs = list(rs)

			def chat(self, messages, tools=None, *, stream=False):
				return self._rs.pop(0)

		pause = ChatResponse(
			content=None,
			tool_calls=[ToolCall(id="c1", name="post_invoice", arguments={"amount": 4200.0})],
			finish_reason="tool_calls",
			usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		)
		done = ChatResponse(
			content="done",
			finish_reason="stop",
			usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		)
		return Scripted([pause] + ([done] if responses == 2 else []))

	def test_the_question_is_asked_with_its_arguments_and_the_tool_has_not_run(self):
		Agent, templated, executed = self._agent_with_templated_tool()
		agent = Agent(model=self._model(1), tools=[templated])
		result = agent.run("post it")

		self.assertTrue(result.paused)
		self.assertEqual(result.questions[0].options, ["Approve", "Deny"])
		self.assertTrue(result.questions[0].prompt.startswith("Approve Post Invoice?"))
		self.assertIn('Post an invoice for "4200.0".', result.questions[0].prompt)
		self.assertIn('"amount": 4200.0', result.questions[0].prompt)
		self.assertEqual(executed, [])

	def test_only_the_exact_approve_executes_a_templated_tool(self):
		Agent, templated, executed = self._agent_with_templated_tool()
		agent = Agent(model=self._model(2), tools=[templated])
		paused = agent.run("post it")
		agent.resume(paused.messages, {"c1": "Approve"})
		self.assertEqual(executed, [4200.0])

	def test_deny_does_not_execute_a_templated_tool(self):
		Agent, templated, executed = self._agent_with_templated_tool()
		agent = Agent(model=self._model(1), tools=[templated])
		paused = agent.run("post it")
		agent.resume(paused.messages, {"c1": "Deny"})
		self.assertEqual(executed, [])

	def test_free_text_does_not_execute_a_templated_tool(self):
		Agent, templated, executed = self._agent_with_templated_tool()
		agent = Agent(model=self._model(2), tools=[templated])
		paused = agent.run("post it")
		agent.resume(paused.messages, {"c1": "no, make it 1"})
		self.assertEqual(executed, [])
