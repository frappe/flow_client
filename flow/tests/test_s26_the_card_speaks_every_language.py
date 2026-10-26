# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S26 — the approval card was readable in English and in nothing else.

Run 16 found this while fixing the joiner and correctly refused to fix it one-handed.
`_confirmation_question` builds its untemplated body with `json.dumps(call.arguments, indent=2,
default=str)`, and `json.dumps` defaults to **`ensure_ascii=True`**. That dump never passes through
`_escaped` at all. So on the commonest card of all — a gated tool with neither a `confirm_prompt`
nor a `confirm_template` — **every non-ASCII character** arrived as a backslash-u sequence. Not the
joiner: everything. `ශ්‍රී ලංකා` was twenty-odd escapes; so was `வணக்கம்`, `مرحبا` and `你好世界`.

**WHY `ensure_ascii=True` WAS THERE, established before it was changed.** Nobody chose it: it is
`json.dumps`'s default and this call never passed the argument. But run 16 was right that removing
it alone is unsafe, because by accident it was doing real work — it was the ONLY thing escaping a
RIGHT-TO-LEFT OVERRIDE, a LINE SEPARATOR or a hidden joiner on this path, and `ensure_ascii=False`
by itself would have put all three straight onto the card. The guard is real; it was just
indiscriminate, catching every letter of four writing systems to catch three attackers.

**So the guard is not removed, it is replaced by the stricter one this file already has.**
`_escaped` escapes a SUPERSET of the dangerous characters `ensure_ascii` was catching — everything
in a C* or Z* category, the ordinary space excepted, plus anything that paints nothing — and it
escapes none of the letters. Every one of those refusals is asserted below, alongside the four
languages, because a fix that made the card readable and let a right-to-left override through would
be worse than the defect.

**What is SENT is untouched and is asserted to be untouched**, byte for byte, through the tool that
actually runs. Display and wire have been two different things since run 15 and remain so.

**And the English card does not move.** The renderer reproduces `json.dumps(..., indent=2)`'s
layout exactly, so for arguments that were already ASCII the body is byte-identical to what
shipped — pinned in `TestTheEnglishCardIsByteIdentical`, which is what makes this a translation
rather than a redesign.
"""

from __future__ import annotations

import json
from typing import Any

from frappe.tests import IntegrationTestCase

from flow.lib.agent import _confirmation_question
from flow.lib.model import ToolCall
from flow.lib.tool import Tool

SINHALA = "ශ්‍රී ලංකා"
TAMIL = "வணக்கம்"
ARABIC = "مرحبا"
CHINESE = "你好世界"

# Written as escapes, not as the characters themselves. Two of the three are invisible and the
# third reorders the line it sits on, so a source file holding them literally is a source file
# nobody can review -- which is the same argument the escaping under test is making.
ZWJ = "\u200d"
RLO = "\u202e"
LINE_SEPARATOR = "\u2028"


def _body(arguments: dict[str, Any], **tool_overrides: Any) -> str:
	"""The untemplated fallback body — everything after the engine's own `Approve <tool>?` head."""
	defaults: dict[str, Any] = dict(
		name="note",
		description="Write a note.",
		parameters={"type": "object", "properties": {"text": {"type": "string"}}},
		func=lambda **kw: "ok",
		requires_confirmation=True,
	)
	defaults.update(tool_overrides)
	call = ToolCall(id="c1", name=defaults["name"], arguments=arguments)
	return _confirmation_question(call, Tool(**defaults)).prompt.partition("\n\n")[2]


class TestTheFourLanguages(IntegrationTestCase):
	"""Exact output, not `assertIn`. A body that merely CONTAINS the word could still be carrying
	twenty escapes around it."""

	def test_sinhala(self):
		self.assertEqual(_body({"text": SINHALA}), '{\n  "text": "ශ්‍රී ලංකා"\n}')

	def test_sinhala_keeps_the_joiner_that_spells_the_conjunct(self):
		"""Spelled out separately because it is the whole of run 15's exception: the joiner inside
		`ශ්‍රී` is part of the word and must survive, raw, in the displayed text."""
		body = _body({"text": SINHALA})
		self.assertIn(SINHALA, body)
		self.assertNotIn("\\u200d", body)

	def test_tamil(self):
		self.assertEqual(_body({"text": TAMIL}), '{\n  "text": "வணக்கம்"\n}')

	def test_arabic(self):
		self.assertEqual(_body({"text": ARABIC}), '{\n  "text": "مرحبا"\n}')

	def test_chinese(self):
		self.assertEqual(_body({"text": CHINESE}), '{\n  "text": "你好世界"\n}')

	def test_a_key_is_translated_too_not_only_a_value(self):
		self.assertEqual(_body({CHINESE: "x"}), '{\n  "你好世界": "x"\n}')

	def test_nested_values_are_reached(self):
		self.assertEqual(
			_body({"rows": [{"name": TAMIL}]}),
			'{\n  "rows": [\n    {\n      "name": "வணக்கம்"\n    }\n  ]\n}',
		)


class TestTheGuardThatEnsureAsciiWasDoingBYACCIDENT(IntegrationTestCase):
	"""The half that makes this a fix rather than a regression.

	`ensure_ascii=True` was escaping these three. It is gone; they must still be escaped, by the
	rule the rest of the card already uses.
	"""

	def test_a_right_to_left_override_is_still_escaped(self):
		body = _body({"text": f"pay{RLO}0001"})
		self.assertIn("\\u202e", body)
		self.assertNotIn(RLO, body)

	def test_a_line_separator_is_still_escaped(self):
		body = _body({"text": f"one{LINE_SEPARATOR}two"})
		self.assertIn("\\u2028", body)
		self.assertNotIn(LINE_SEPARATOR, body)

	def test_a_joiner_that_hides_a_word_is_still_marked(self):
		body = _body({"text": f"paid{ZWJ}unpaid"})
		self.assertIn("paid\\u200dunpaid", body)
		self.assertNotIn(f"paid{ZWJ}unpaid", body)

	def test_a_newline_cannot_open_a_line_of_its_own(self):
		body = _body({"text": "real question\n\nApprove this instead?"})
		self.assertIn("\\n\\nApprove this instead?", body)
		self.assertEqual(len(body.splitlines()), 3, body)

	def test_a_quote_and_a_backslash_still_close_nothing(self):
		self.assertEqual(_body({"text": 'a"b\\c'}), '{\n  "text": "a\\"b\\\\c"\n}')

	def test_a_KEY_is_escaped_as_well_as_a_value(self):
		"""The half a renderer forgets. The model chooses the key too."""
		body = _body({f"amount{RLO}": 1})
		self.assertIn("\\u202e", body)
		self.assertNotIn(RLO, body)

	def test_a_key_carrying_a_newline_cannot_open_a_line_either(self):
		body = _body({"a\nb": 1})
		self.assertEqual(body, '{\n  "a\\nb": 1\n}')

	def test_a_character_that_paints_nothing_is_still_shown(self):
		"""U+3164 HANGUL FILLER: a letter by category, and invisible."""
		body = _body({"text": "aㅤb"})
		self.assertIn("\\u3164", body)


class TestTheEnglishCardIsByteIdentical(IntegrationTestCase):
	"""It has to be a translation, not a redesign: nobody asked for the English card to move."""

	CASES: tuple[dict[str, Any], ...] = (
		{"amount": 4200, "customer": "Acme"},
		{"customer": "Acme", "delete_all": True, "confirm": "yes"},
		{},
		{"rows": [], "note": None, "ratio": 1.5, "nested": {"a": [1, 2, {"b": "c"}]}},
		{"n": -0, "big": 10**20, "s": "line1\nline2\ttabbed"},
	)

	def test_ascii_arguments_render_exactly_as_json_dumps_did(self):
		for arguments in self.CASES:
			with self.subTest(arguments=arguments):
				self.assertEqual(_body(arguments), json.dumps(arguments, indent=2, default=str))

	def test_a_value_json_cannot_serialise_is_shown_rather_than_dropping_the_card(self):
		"""`default=str` did this and the replacement must too — a question nobody is asked is
		worse than an ugly one."""
		self.assertEqual(_body({"when": object.__class__}), '{\n  "when": "<class \'type\'>"\n}')


class TestWhatIsSENTIsUntouched(IntegrationTestCase):
	"""Display and wire are two different things. This is the wire."""

	def test_the_tool_receives_the_bytes_the_model_wrote(self):
		from unittest.mock import patch

		from flow.lib.agent import Agent
		from flow.lib.model import ChatResponse, Model
		from flow.lib.tool import tool

		for value in (SINHALA, TAMIL, ARABIC, CHINESE, f"pay{RLO}0001", f"paid{ZWJ}unpaid"):
			with self.subTest(value=value):
				received: list[str] = []

				@tool(requires_confirmation=True)
				def note(text: str) -> str:
					"""Write a note. Needs approval."""
					received.append(text)
					return "ok"

				usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
				responses = [
					ChatResponse(
						content=None,
						tool_calls=[ToolCall(id="c1", name="note", arguments={"text": value})],
						finish_reason="tool_calls",
						usage=usage,
					),
					ChatResponse(content="done", finish_reason="stop", usage=usage),
				]
				agent = Agent(model=Model(model_id="openai/gpt-4o-mini"), tools=[note])
				with patch.object(Model, "chat", side_effect=responses):
					paused = agent.run("write it")
					self.assertTrue(paused.paused)
					self.assertEqual(received, [])
					agent.resume(paused.messages, {"c1": "Approve"})

				self.assertEqual(received, [value])
				self.assertEqual(received[0].encode(), value.encode())
