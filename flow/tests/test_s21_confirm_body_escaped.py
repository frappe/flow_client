# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""What a person SEES in the approval question of every tool that ships with a body of its own.

S21 v2's D0, and a precondition for the rest of S21. Until this holds, the card must not render the
body: the engine composes `"Approve <tool>?" + "\\n\\n" + body`, and five of the six shipped bodies
interpolated model-chosen arguments raw. Rendered in a `pre-wrap` block with no height cap, a name
carrying a newline draws a second, friendlier question inside the real card, above two buttons
labelled Approve and Deny. That is the E5 v1 lesson CLAUDE.md records in as many words: model-chosen
values are data; never let them change the shape of what a person is asked to approve.

Every assertion below is on the WHOLE question as an approver reads it — `Question.prompt` — not on
a helper's return value, because the helper is not what anybody sees.

ONE RULE, ONE ESCAPER. Every value goes through `_display_value`, which is E5 v2's own
`escape_for_display` plus the cap, and nothing else. A second escaper would be a second rule and the
first thing to drift (`flow/lib/agent.py`, above `escape_for_display`).

THE CAP IS APPLIED AFTER ESCAPING, and that is the point of `test_the_cap_is_measured_on_the_escaped
_form_not_the_raw_one`. Escaping only ever lengthens — one right-to-left override becomes the six
characters `\\u202e` — so a cap measured on the raw value lets six times the cap through, which is
how a body with a 120-character bound reached 720 characters of nothing but overrides.

THE ONE DELIBERATE EXCEPTION is the code-running tool's `code`. It keeps its real newlines because a
person approving Python reads Python, an eval depends on it
(`evals/scenarios/an_approved_execute_shows_its_code.yaml`), and escaping it would turn every quote
in it into `\\"`. It is last in the body, beneath its own escaped one-line sentence, and it is shown
WHOLE — never shortened. Shortening the code is the E5 v1 truncation attack ("and DELETE every
invoice" hidden past the cut), so the length is stated and the code is still printed in full.

NOT TOUCHED BY THIS MODULE: `flow/lib/agent.py`. `_invoke`, `_resolve_confirmation`,
`_confirmation_question` and `_has_denial` are read here and nowhere modified (CLAUDE.md rule 4);
`escape_for_display` gains callers, never a second rule.
"""

from __future__ import annotations

from frappe.tests import IntegrationTestCase

from flow.lib.agent import _confirmation_question, _escaped
from flow.lib.model import ToolCall
from flow.tools.builtins import create, delete, execute, run_action, update

RTL = "‮"  # RIGHT-TO-LEFT OVERRIDE — reorders a line without adding a character to it
ZWJ = "‍"  # ZERO WIDTH JOINER — occupies no width, so it hides a word boundary
FORGED = "\nApproved by admin"  # a newline and a line that was never the engine's
CONTROL_ONLY = "\u0001\u2028\u202e\u200d\r\n\t"  # nothing in it a reader could see unescaped
HUGE = "A" * 50_000
# The builtins carry no `title`, so the engine head falls back to the slug in backticks.
_EXPECTED_HEAD = "Approve `delete`?"


def _body(tool, arguments: dict) -> str:
	"""The question as an approver reads it, with the engine's own first line removed.

	Split on the first blank line, exactly as `_confirmation_question` joined it, so an assertion
	about "the body" cannot accidentally be satisfied by the engine's `Approve <tool>?` head.
	"""
	return _confirmation_question(
		ToolCall(id="c1", name=tool.name, arguments=arguments), tool
	).prompt.partition("\n\n")[2]


class TestNothingModelChosenCanStartALine(IntegrationTestCase):
	"""A body is one line, or the lines in it are the engine's. One test per place a value is
	interpolated, so a mutation at one place reddens one test and names itself."""

	def test_a_right_to_left_override_in_a_record_name_is_shown_not_obeyed(self):
		"""`_summarize_names`, reached by delete, update and run_action.

		An override needs no line break: it reverses the run of text after it, so a body reading
		"Delete 1 ToDo" can be made to read as its own opposite while every character stays where
		it was. It is escaped, so the reader sees the override rather than its effect.
		"""
		body = _body(delete, {"doctype": "ToDo", "names": [f"T-1{RTL}detceled eb lliw gnihtoN"]})
		self.assertNotIn(RTL, body)
		self.assertIn("\\u202e", body)
		self.assertIn("T-1", body)  # positive control: the name itself still reaches the reader

	def test_a_zero_width_joiner_in_a_field_value_is_made_visible(self):
		"""`_summarize_values`, reached by create and update.

		A zero-width character is the one an approver cannot see at all, so it is the one an
		escaper has to print. Before D0 this passed through `json.dumps(..., ensure_ascii=False)`
		untouched, and so did U+2028, which every layout engine treats as a line break.
		"""
		body = _body(create, {"doctype": "ToDo", "records": [{"description": f"paid{ZWJ}unpaid"}]})
		self.assertNotIn(ZWJ, body)
		self.assertIn("\\u200d", body)
		self.assertIn("paid", body)  # positive control

	def test_a_forged_approval_line_in_a_record_type_cannot_start_a_line(self):
		"""`update`'s own `doctype`. The attack in one string: a newline, then a sentence that
		reads like the engine's. It is the body the card renders, so a real newline there is a real
		line, at full height, above the buttons."""
		body = _body(update, {"doctype": f"ToDo{FORGED}", "names": ["T-1"], "values": {"status": "Closed"}})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)

	def test_a_description_of_nothing_but_control_characters_leaves_one_line(self):
		"""The code-running tool's `description`. It is one sentence and must stay one line: the
		code block beneath it is the only thing in any body that is allowed real newlines, and a
		sentence that can open a line of its own can open one that looks like a new question."""
		body = _body(execute, {"description": CONTROL_ONLY, "code": "result = 1"})
		sentence = body.partition("\n\n")[0]
		self.assertNotIn("\n", sentence)
		for ch in CONTROL_ONLY:
			self.assertNotIn(ch, sentence, f"{ch!r} reached the sentence unescaped")

	def test_a_record_type_in_the_create_body_is_escaped_too(self):
		"""`create`'s own `doctype`, a separate interpolation from `update`'s."""
		body = _body(create, {"doctype": f"ToDo{FORGED}", "records": [{"status": "Open"}]})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)

	def test_a_record_type_in_the_delete_body_is_escaped_too(self):
		"""`delete`'s own `doctype`."""
		body = _body(delete, {"doctype": f"ToDo{FORGED}", "names": ["T-1"]})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)

	def test_a_record_type_in_the_run_action_body_is_escaped_too(self):
		"""`run_action`'s own `doctype`, distinct again from its `action`."""
		body = _body(run_action, {"doctype": f"ToDo{FORGED}", "names": ["T-1"], "action": "submit"})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)


class TestAFieldNameIsAsModelChosenAsAFieldValue(IntegrationTestCase):
	"""QA found this as a coverage hole, not as a defect: the shipped code escaped dict keys, and
	removing that escape kept the whole module green because every other test used an ordinary key
	like `status`. A key is chosen by the model exactly as a value is — `values` and `records[0]` both
	come straight from the call — so each key surface gets its own hostile test."""

	def test_a_field_name_in_an_update_cannot_start_a_line(self):
		body = _body(update, {"doctype": "ToDo", "names": ["T-1"], "values": {f"status{FORGED}": "Closed"}})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)

	def test_a_field_name_in_a_create_cannot_start_a_line(self):
		body = _body(create, {"doctype": "ToDo", "records": [{f"status{FORGED}": "Open"}]})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)

	def test_a_field_name_inside_a_child_row_cannot_start_a_line(self):
		"""The nested branch has its own key interpolation, so it needs its own test."""
		body = _body(create, {"doctype": "ToDo", "records": [{"items": [{f"qty{FORGED}": 2}]}]})
		self.assertNotIn("\nApproved by admin", body)
		self.assertIn("\\nApproved by admin", body)


class TestEveryElisionCountIsOutsideAQuote(IntegrationTestCase):
	"""QA's Q4: the commit titled "an elision count cannot be forged" fixed ONE of the three places
	that emit a count. `_display_json`'s list and dict markers were still INSIDE quotes, so a value
	reading `… +7 more` in a three-element list was byte-identical to a ten-element list with seven
	hidden. One rule: an unescaped quote is the engine's boundary, so every count sits outside one."""

	def test_a_list_element_cannot_impersonate_the_hidden_count(self):
		forged = _body(create, {"doctype": "ToDo", "records": [{"t": ["a", "b", "… +7 more"]}]})
		real = _body(create, {"doctype": "ToDo", "records": [{"t": [str(i) for i in range(9)]}]})
		self.assertIn(
			'"… +7 more"', forged, "the forged text is not shown quoted, so it reads as the engine's"
		)
		self.assertIn("… +3 more", real)
		self.assertNotIn('"… +3 more"', real, "a real count is quoted, so a value can impersonate it")

	def test_a_field_name_cannot_impersonate_the_hidden_count(self):
		forged = _body(create, {"doctype": "ToDo", "records": [{"t": {"…": "+7 more"}}]})
		real = _body(create, {"doctype": "ToDo", "records": [{"t": {f"k{i}": i for i in range(9)}}]})
		self.assertIn('"…"', forged)
		self.assertNotIn('"…":', real, "a real dict count is quoted like a key, so a key can impersonate it")


class TestAWrongTypedArgumentIsStillAskedAbout(IntegrationTestCase):
	"""QA's Q5, a REGRESSION this run introduced. Stating the code's length meant calling `len()` on
	it, and a model that sends `code` as a number made the question itself raise — killing the turn
	where the unfixed engine had simply asked about it. Nothing executed either way (the raise happens
	in the branch that returns before the tool body runs), but a question that cannot be composed is a
	question nobody is asked, and that is a worse failure than an ugly one."""

	def test_a_numeric_code_still_produces_a_question(self):
		body = _body(execute, {"description": "count", "code": 123})
		self.assertIn("123", body)

	def test_a_call_with_no_code_does_not_promise_a_block_that_is_not_there(self):
		"""QA's Q8: the engine's line used to announce a nought-character block and then show
		nothing under it."""
		body = _body(execute, {"description": "count", "code": ""})
		self.assertNotIn("in full", body)


class TestATypeIsNotTurnedIntoText(IntegrationTestCase):
	"""QA's Q6. Quoting every value made a cleared field (`None`) indistinguishable from a model
	writing the four letters "None", and a quantity of `3` indistinguishable from the character "3".
	Those are different writes. The quoting argument — a reader can see where a value starts and ends
	— is about TEXT, which is the only kind of value that can carry an escape; a number, a boolean and
	a null cannot, so they are shown as themselves."""

	def test_a_number_a_boolean_and_a_null_are_shown_as_themselves(self):
		body = _body(create, {"doctype": "ToDo", "records": [{"qty": 3, "paid": True, "remarks": None}]})
		self.assertIn(": 3", body)
		self.assertIn(": true", body)
		self.assertIn(": null", body)

	def test_a_number_too_long_to_show_goes_back_through_the_cap(self):
		"""QA's R3, a defect the previous fix INTRODUCED. Showing a number as itself meant handing it
		to `json.dumps` with no cap and no finiteness check, on a path that skips the very helper the
		cap lives in — 3,000 digits of engine-register text in the question, and a 4,301-digit integer
		raised outright, re-creating the "a question nobody is asked" failure one commit later."""
		body = _body(create, {"doctype": "ToDo", "records": [{"qty": 10**3000}]})
		self.assertLess(len(body), 600, "a long number bypassed the cap")
		self.assertIn("3001", body, "the true length of the number is not stated")

	def test_a_number_python_refuses_to_print_still_produces_a_question(self):
		body = _body(create, {"doctype": "ToDo", "records": [{"qty": 10**5000}]})
		self.assertTrue(body, "composing the question raised instead of asking it")

	def test_a_value_that_is_not_a_number_at_all_is_not_shown_in_the_engines_register(self):
		"""QA's R4. `NaN` and `Infinity` are not JSON, and `json.loads` accepts both from a model —
		so they reached the body as bare unquoted tokens, in the register the engine reserves for its
		own words."""
		body = _body(create, {"doctype": "ToDo", "records": [{"a": float("nan"), "b": float("inf")}]})
		self.assertNotIn(": NaN", body)
		self.assertNotIn(": Infinity", body)

	def test_and_the_text_versions_of_them_are_still_quoted_and_distinguishable(self):
		body = _body(
			create, {"doctype": "ToDo", "records": [{"qty": "3", "paid": "True", "remarks": "None"}]}
		)
		self.assertIn(': "3"', body)
		self.assertIn(': "True"', body)
		self.assertIn(': "None"', body)


class TestEveryValueIsCappedAfterItIsEscaped(IntegrationTestCase):
	def test_a_fifty_thousand_character_action_name_does_not_reach_the_reader_whole(self):
		"""`run_action`'s `action`. 50,000 characters is not a question, it is a denial of the
		card: the sentence a person has to read scrolls off a screen and the buttons are what is
		left. The cap says how long the value really was, so nothing is shortened silently."""
		body = _body(run_action, {"doctype": "ToDo", "names": ["T-1"], "action": HUGE})
		self.assertLess(len(body), 2_000, "the body is not bounded by anything")
		self.assertIn("50000", body, "the true length of the value is not stated")

	def test_the_cap_is_measured_on_the_escaped_form_not_the_raw_one(self):
		"""The property the word AFTER is doing in "capped after escaping".

		250 right-to-left overrides are 250 raw characters and 1,500 escaped ones. A cap of 200
		measured before escaping passes all 250 through and the body carries 1,500 characters of
		escape sequence; measured after, the body carries 200 and says the value was 250 long.
		"""
		body = _body(delete, {"doctype": "ToDo", "names": [RTL * 250]})
		self.assertLess(len(body), 600, "the cap was measured before escaping, so escaping burst it")
		self.assertIn("250", body, "the true length of the value is not stated")

	def test_a_value_of_only_control_characters_shows_only_escapes(self):
		"""Nothing invisible reaches the reader, and the reader is not shown an empty body either
		— a body that renders as nothing reads exactly like a tool with nothing to say."""
		body = _body(delete, {"doctype": "ToDo", "names": [CONTROL_ONLY]})
		for ch in CONTROL_ONLY:
			self.assertNotIn(ch, body, f"{ch!r} reached the body unescaped")
		self.assertIn("\\u0001", body)
		self.assertIn("\\u2028", body)
		self.assertIn("\\r", body)


class TestTheElisionMarkerCannotBeForged(IntegrationTestCase):
	"""The security review's M2, and it was a real defect in the first version of this helper.

	The marker saying a value was shortened used to be appended INSIDE the quotes, so a value whose
	own text was `short… (9999 characters in all)` reached the reader byte-identical to a genuinely
	elided 9,999-character value. A reader could not tell a 33-character value from a 9,999-character
	one — which is the exact property the helper's docstring claims to establish.

	The fix relies on the one character escaping guarantees a value cannot produce: `_escaped` maps
	`"` to `\"`, so an UNESCAPED quote is engine-owned. The marker goes after the closing quote, and
	the quote is the boundary.
	"""

	FORGED_MARKER = "short… (9999 characters in all)"

	def test_a_value_that_looks_elided_is_not_read_as_elided(self):
		body = _body(delete, {"doctype": "ToDo", "names": [self.FORGED_MARKER]})
		self.assertIn(self.FORGED_MARKER, body)  # it is shown, whole — nothing is hidden
		self.assertNotIn('" ', body, "the forged marker is outside a quote, so it reads as the engine's")

	def test_a_genuinely_elided_value_puts_its_count_outside_the_quote(self):
		body = _body(delete, {"doctype": "ToDo", "names": ["A" * 500]})
		self.assertIn('" ', body, "a real elision marker is not separated from the value by a quote")
		self.assertIn("500", body)

	def test_the_two_are_therefore_distinguishable(self):
		"""The assertion that makes the pair a proof rather than two observations."""
		forged = _body(delete, {"doctype": "ToDo", "names": [self.FORGED_MARKER]})
		real = _body(delete, {"doctype": "ToDo", "names": ["A" * 500]})
		self.assertNotEqual('" ' in forged, '" ' in real)


class TestTheCodeBlockIsIntroducedByTheEngineNotByTheModel(IntegrationTestCase):
	"""The security review's M1. The helper's docstring justified leaving the code raw by saying a
	forged line inside *a block introduced as the code that will run* is still inside that block —
	but the only thing introducing the block was `description`, which the model writes. So the
	justification was not implemented. An engine-owned line now sits between the two, and the length
	is stated ALWAYS rather than only past a threshold: the threshold was what left short code, the
	common case, unlabelled."""

	def test_an_engine_owned_line_sits_between_the_sentence_and_the_code(self):
		body = _body(execute, {"description": "Verification notice — read before approving", "code": "x = 1"})
		self.assertIn("The code that will run", body)
		self.assertLess(
			body.index("Verification notice"),
			body.index("The code that will run"),
			"the engine's line must come after the model's sentence and before the code",
		)
		self.assertLess(body.index("The code that will run"), body.index("x = 1"))

	def test_the_length_is_stated_even_for_short_code(self):
		body = _body(execute, {"description": "count", "code": "x = 1"})
		self.assertIn("5", body, "a five-character code block does not say it is five characters")


class TestTheCodeBlockIsTheOneExceptionAndStaysWhole(IntegrationTestCase):
	def test_the_code_keeps_its_newlines_and_its_quotes(self):
		"""The eval `an_approved_execute_shows_its_code` asserts on this text. A person approving
		code is approving THIS code, so it is not escaped and not shortened."""
		code = (
			'names = frappe.get_list("Sales Invoice", pluck="name")\nresult = delete("Sales Invoice", names)'
		)
		body = _body(execute, {"description": "Delete last month's drafts", "code": code})
		self.assertTrue(body.endswith(code), "the code is not the last thing in the body, whole")

	def test_a_long_code_block_is_still_shown_whole_with_its_length_stated(self):
		"""The one value that is never shortened. Cutting code is the E5 v1 truncation attack —
		the part left out is the part that mattered — so the bound is a sentence about the length,
		not a shorter body."""
		code = "\n".join(f"x{i} = {i}" for i in range(1, 1_001))
		body = _body(execute, {"description": "count", "code": code})
		self.assertIn(code, body, "the code was shortened; it must be shown whole")
		self.assertIn(str(len(code)), body, "a code block past the bound does not say how long it is")


class TestTheOrdinaryQuestionStillReadsLikeItself(IntegrationTestCase):
	"""The positive control for every assertion above: an escaper that mangled ordinary text would
	pass every attack test in this module and be useless."""

	def test_a_plain_delete_body_is_unchanged_by_escaping(self):
		body = _body(delete, {"doctype": "ToDo", "names": ["TODO-0001", "TODO-0002"]})
		self.assertIn("ToDo", body)
		self.assertIn("TODO-0001", body)
		self.assertIn("TODO-0002", body)
		self.assertNotIn("\\", body, "an ordinary body carries no escapes at all")

	def test_a_plain_create_body_still_shows_its_values(self):
		body = _body(
			create, {"doctype": "ToDo", "records": [{"description": "Pay the invoice", "priority": 3}]}
		)
		self.assertIn("Pay the invoice", body)
		self.assertIn("3", body)

	def test_the_options_and_the_engine_head_are_untouched_by_any_of_this(self):
		"""CLAUDE.md rule 4's boundary, asserted rather than assumed: D0 changes wording only."""
		q = _confirmation_question(
			ToolCall(id="c1", name="delete", arguments={"doctype": f"ToDo{RTL}", "names": [FORGED]}), delete
		)
		self.assertEqual(q.options, ["Approve", "Deny"])
		self.assertTrue(q.allow_other)
		self.assertEqual(q.prompt.splitlines()[0], _EXPECTED_HEAD)


class TestACharacterThatPaintsNothingIsEscapedWhateverItsCategory(IntegrationTestCase):
	"""The class the C*/Z* rule could never reach, found by a reviewer measuring instead of reading.

	The rule was "everything in a C* or Z* category". Unicode has a property that says exactly what
	this escaper is defending against — `Default_Ignorable_Code_Point`, "a conformant renderer paints
	nothing here" — and **267 of those code points are in neither C* nor Z***, so every one arrived
	in the approval question RAW. Four of them are category `Lo`: LETTERS. No rule about controls,
	formats, separators or even combining marks was ever going to catch a letter.

	What that buys an attacker is the whole of A2 over again, on the sentence a person approves:
	`SO-0001` and `SO-0001ㅤ` are two different writes that render identically, and the second
	one carries no signal at all — not even the quote, because a value the rule finds nothing wrong
	with is shown as itself.

	Python has no such property in `unicodedata`, so the table is written out. It is derived from the
	same Unicode property the panel's regex uses and is checked against the panel's rule in
	`frontend/tests/displayProperty.spec.js`, because the two escapers are a port of one rule and the
	whole point is that they do not drift.
	"""

	# Not combining marks, not formats, not separators. Letters that paint nothing.
	INVISIBLE_LETTERS = ("ᅟ", "ᅠ", "ㅤ", "ﾠ")

	def test_an_invisible_letter_is_escaped(self):
		for ch in self.INVISIBLE_LETTERS:
			with self.subTest(ch=hex(ord(ch))):
				self.assertEqual(_escaped(ch), "\\u%04x" % ord(ch))

	def test_two_values_a_reader_cannot_tell_apart_do_not_escape_alike(self):
		"""The property, not the example: the escaping is what makes the difference visible."""
		for ch in self.INVISIBLE_LETTERS:
			with self.subTest(ch=hex(ord(ch))):
				self.assertNotEqual(_escaped("SO-0001"), _escaped("SO-0001" + ch))

	def test_the_rest_of_the_property_goes_the_same_way(self):
		"""The members that are combining marks rather than letters — including the variation
		selectors, which is a deliberate cost: an emoji written with U+FE0F now shows quoted."""
		for cp in (0x034F, 0x17B4, 0x180B, 0xFE0F, 0xE0100):
			with self.subTest(cp=hex(cp)):
				shown = _escaped(chr(cp))
				self.assertNotEqual(shown, chr(cp))
				# `\\u` below the BMP and `\\U` above it, which is the escaper's own rule and is
				# why U+E0100 is in this list: an astral member proves the branch a 16-bit scan
				# would have split in half.
				self.assertTrue(shown.startswith(("\\u", "\\U")), shown)

	def test_ordinary_text_is_still_returned_untouched(self):
		"""The control. A rule that escaped everything would pass every assertion above."""
		self.assertEqual(
			_escaped("Sales Order SO-0001 — 3 items, Rs 4,500"), "Sales Order SO-0001 — 3 items, Rs 4,500"
		)
		self.assertEqual(_escaped("日本語のテキスト"), "日本語のテキスト")
		self.assertEqual(_escaped("עברית"), "עברית")
