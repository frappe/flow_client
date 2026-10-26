# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""A SOURCE GUARD on the Desk confirmation card. It is not a render proof, and must never be called one.

READ THIS BEFORE TRUSTING IT. There is no JavaScript test runner in this repository: `package.json`
declares only `dev` and `build`, both `vite build`, and its devDependencies are vite, the vue plugin,
postcss, autoprefixer, postcss-prefix-selector and tailwind — no vitest, no jest, no
`@vue/test-utils`, no jsdom. CI runs one job whose only test step is the bench test runner. The built
bundle is not even committed (`.gitignore` carries `flow/public/flow_panel/`). So **`GATE=GREEN` says
nothing whatever about `frontend/`**, and this module does not change that: it reads the component off
disk and asserts on its text. It proves no pixel, no layout and no behaviour.

WHY IT EXISTS ANYWAY. It is the only assertion this repository's gate can turn red for the `.vue`
change, it can be watched failing before the fix, and it stops a later refactor silently restoring
either of the two suppressors that hid the approval question for three months. A lint-shaped,
brittle guard that can go red beats seven `features.json` rows whose `passes` somebody flips from
memory of a browser session — which is the failure mode CLAUDE.md names in as many words: *a gate
whose failure mode has never been observed is a comment.*

WHAT ACTUALLY PROVES THE PIXELS: the browser checks in the spec's T3 list, done by a person, and
recorded as browser checks and never as tests. A JS runner would replace most of them; that is its
own decision and its own spec.

KEEP THIS FILE OUT OF ANY UPSTREAM BRANCH. It asserts on paths and on source text, not on behaviour.
"""

from __future__ import annotations

import pathlib
import re

import frappe
from frappe.tests import IntegrationTestCase

# `frappe.get_app_path("flow")` is `<repo>/flow`, so the panel source is its sibling.
APP = pathlib.Path(frappe.get_app_path("flow"))
CARD = APP.parent / "frontend/src/components/ConfirmCard.vue"
STORE = APP.parent / "frontend/src/store.js"
AUDIT = APP / "flow/doctype/flow_run/flow_run_detail.html"


def _text(path: pathlib.Path) -> str:
	return path.read_text(encoding="utf-8")


def _template(card: str) -> str:
	"""The `<template>` block alone. A cap or a wrapper added in the markup is invisible to an
	assertion that only reads the stylesheet — QA proved exactly that."""
	return card[card.index("<template>") : card.index("</template>")]


def _style(card: str) -> str:
	return card[card.index("<style scoped>") : card.index("</style>")]


class TestTheFilesAreWhereThisModuleThinksTheyAre(IntegrationTestCase):
	"""The control for every assertion below. `assertNotIn` on a file that does not exist would be
	a test that passes by reading nothing — the exact shape of a false green."""

	def test_each_file_read_by_this_module_exists_and_is_not_empty(self):
		for path in (CARD, STORE, AUDIT):
			with self.subTest(path=path.name):
				self.assertTrue(path.is_file(), f"{path} is missing — this module is asserting on nothing")
				self.assertGreater(len(_text(path)), 500)

	def test_the_card_is_the_file_this_module_means(self):
		"""A positive control in the identical form: text that IS there."""
		self.assertIn("flow-confirm-body", _text(CARD))
		self.assertIn("question.options", _text(CARD))


class TestNeitherSuppressorIsPresent(IntegrationTestCase):
	"""The two independent reasons the engine's question never reached a Desk approver. Either one
	alone is enough to blank it, so both are asserted separately."""

	def test_the_body_is_not_blanked_whenever_there_is_a_tool(self):
		"""`body` used to be `props.tool ? "" : …`, and on this path `props.tool` is never null —
		the only mount of this component always passes it. So the body was always the empty string."""
		self.assertNotIn('props.tool ? ""', _text(CARD))

	def test_the_arguments_table_does_not_exclude_the_body(self):
		"""The second suppressor: the body sat in the `v-else-if` of the arguments table, and the
		table renders for any call with arguments. Both branches must be `v-if`."""
		self.assertNotIn('v-else-if="body"', _text(CARD))

	def test_the_body_is_rendered_above_the_arguments(self):
		"""Order matters: the sentence saying what will happen goes first, the corroborating table
		second. A table above the sentence is read as the whole answer."""
		card = _text(CARD)
		self.assertLess(
			card.index('<pre v-if="body"'),
			card.index('v-if="showArgs"'),
			"the arguments table is rendered above the body",
		)


class TestTheBodyIsShownWholeAsText(IntegrationTestCase):
	def test_there_is_no_height_cap_on_the_body(self):
		"""The FIRST version of this test read the `.flow-confirm-body` rule and nothing else, and QA
		broke it in one move: wrap the `<pre>` in `<div style="max-height: 220px; overflow: auto">`
		and the cap is back with the rule still clean. So the assertion is now on the whole
		component — the stylesheet AND the markup — because a cap is a cap wherever it is written."""
		card = _text(CARD)
		start = card.index(".flow-confirm-body {")
		rule = card[start : card.index("}", start)]
		self.assertNotIn("max-height", rule)
		self.assertNotIn("overflow", rule)
		self.assertNotIn("max-height", _style(card), "a height cap moved to another rule")
		self.assertNotIn("overflow", _style(card), "an internal scroll moved to another rule")
		self.assertNotIn("max-height", _template(card), "a height cap moved into the markup")
		self.assertNotIn("overflow", _template(card), "an internal scroll moved into the markup")
		self.assertNotIn(
			"style=", _template(card), "an inline style can carry a cap no stylesheet assertion sees"
		)

	def test_no_show_more_affordance_is_introduced_on_the_body(self):
		"""The same defect wearing a button. `ClampText` and `CodeBlock` are how a value in the
		ARGUMENTS table collapses, and neither may be reached from the body."""
		card = _text(CARD)
		body_block = card[card.index('<pre v-if="body"') : card.index("</pre>")]
		for forbidden in ("ClampText", "CodeBlock", "Show more", "line-clamp"):
			self.assertNotIn(forbidden, body_block)

	def test_the_body_is_interpolated_as_text_never_as_markup(self):
		"""Mustache interpolation sets `textContent`, so `<img src=x onerror=…>` in a note is
		displayed rather than parsed. `MarkdownText` is the panel's only `v-html` and would also
		re-interpret the very characters the engine escaped on purpose — a `\\n` printed to show that
		a value contained a newline has to stay the two characters `\\`, `n`."""
		card = _text(CARD)
		self.assertIn('<pre v-if="body" class="flow-confirm-body">{{ body }}</pre>', card)
		self.assertNotIn("v-html", card)
		self.assertNotIn("MarkdownText", card)


class TestAQuestionWithNoToolPartStillHasSomethingToRead(IntegrationTestCase):
	def test_a_one_paragraph_question_falls_back_to_the_whole_prompt(self):
		"""The empty-card case, and the one the sibling web apps shipped: a prompt with no blank
		line in it, or a gated call with no arguments at all, drew a card containing a label and two
		buttons and nothing else. The fallback is what closes it."""
		card = _text(CARD)
		self.assertIn("titleIsEngineHead", card)
		body = card[card.index("const body = computed(") : card.index("// execute's description")]
		# QA broke the first version of this by replacing the whole computed with
		# `titleIsEngineHead.value ? "" : props.question.prompt.trim()` — which blanks the body on
		# EXACTLY the live approval path, the defect S21 exists to fix — while keeping both substrings
		# this test asked for. So the engine body itself has to be named, and the empty-string branch
		# has to be absent.
		self.assertIn("engineBody.value", body, "the body no longer renders the engine's own body")
		self.assertNotIn('? ""', body, "the body has a branch that renders nothing")
		# The stronger property the security review asked for (its L3): when the headline is NOT the
		# engine's own first line, the body is the WHOLE prompt, so paragraph 0 is never dropped.
		self.assertIn("titleIsEngineHead.value", body)
		# The whole prompt, trimmed. Written as the NAME of the guarded value rather than as the
		# dereference it used to be: run 14's final reviewer found that reading the headline off the
		# engine's first line made this computed reachable on EVERY card, so a stored question row with
		# no `prompt` — `store.js` spreads one verbatim when a paused run is resumed, and validates
		# nothing — threw a TypeError inside a computed during render. Not a degraded card but NO card,
		# an approval that can no longer be answered. `promptText` is `String(prompt ?? "")` and is the
		# only thing that touches the stored value.
		self.assertIn("promptText.value.trim()", body)
		# And the property that rename has to keep, stated so it cannot be renamed away: the ONE place
		# the stored value is read is inside a guard, and nothing in the card dereferences it directly.
		# This is strictly more than the string this test used to look for, which the guard would have
		# had to delete to satisfy.
		card_no_comments = re.sub(r"^\s*(//|\*|/\*).*$", "", card, flags=re.M)
		self.assertIn('String(props.question.prompt ?? "")', card_no_comments)
		self.assertNotIn("props.question.prompt.", card_no_comments)
		# Positive control on that detector, in the identical form: it really does fire on the shape it
		# forbids, so its absence above is a finding and not a dead assertion.
		self.assertIn("props.question.prompt.", "x = props.question.prompt.trim()")


class TestApproveAndDenyNeverTakeFocus(IntegrationTestCase):
	"""Nothing may answer for the person before the person has read the question. This is true today
	and the assertion is here so it stays true: the free-text box is the ONLY thing in this component
	that is focused programmatically, and it is only focused after somebody clicks "Other…"."""

	def test_the_only_focus_call_in_the_card_is_the_free_text_box(self):
		self.assertEqual(re.findall(r"(\w+)\.value\?\.focus\(\)", _text(CARD)), ["otherEl"])

	def test_no_option_button_is_autofocused(self):
		card = _text(CARD)
		self.assertNotIn("autofocus", card)
		option_block = card[card.index('v-for="opt in question.options"') : card.index('@click="pick(opt)"')]
		self.assertNotIn("focus", option_block)

	def test_no_key_handler_answers_an_option(self):
		"""Enter must not approve. The only keydown handlers in the card are on the free-text box."""
		self.assertEqual(
			re.findall(r"@keydown[.\w]*", _text(CARD)),
			["@keydown.enter.exact.prevent", "@keydown.esc"],
		)


class TestAPauseScrollsToTheQuestionNotToTheButtons(IntegrationTestCase):
	"""Without this, removing the height cap makes things worse rather than better: the pause used to
	force a scroll to the bottom of the message list, which with a 220px body left the whole card on
	screen and with no cap leaves the BUTTON ROW on screen and the question above the viewport."""

	def test_the_card_puts_its_own_top_on_screen_when_it_mounts(self):
		card = _text(CARD)
		self.assertIn("onMounted", card)
		self.assertIn('scrollIntoView({ block: "start"', card)
		self.assertIn('ref="rootEl"', card)

	def test_it_does_not_do_that_to_a_question_already_answered(self):
		"""Re-rendering history must not yank the view to an old card."""
		card = _text(CARD)
		mounted = card[card.index("onMounted(() => {") : card.index("function pick(")]
		self.assertIn("props.question._answer !== undefined", mounted)
		self.assertIn("return", mounted)

	def test_the_store_no_longer_forces_a_bottom_scroll_when_a_run_pauses(self):
		"""Comments are stripped first: the branch carries a comment naming the call it no longer
		makes, and an assertion that a NAME is absent from prose is not an assertion about code."""
		store = _text(STORE)
		paused = store[store.index('if (event.status === "Paused")') : store.index("refreshHistory();")]
		code = "\n".join(line.split("//")[0] for line in paused.split("\n"))
		self.assertNotIn("requestScroll(true)", code)
		self.assertIn("requestScroll(true)", paused)  # control: the comment IS there, and is why

	def test_the_store_still_forces_a_scroll_everywhere_it_did_before(self):
		"""The control against fixing this by deleting the scroll machinery. Sending a message and
		resuming a run both still follow new content to the bottom, which is right — there is no
		question to read there."""
		self.assertIn("requestScroll(true)", _text(STORE))


class TestTheAuditViewShowsWhatTheApproverSaw(IntegrationTestCase):
	"""The read-only detail view on the run record renders the same prompt with no Approve or Deny.
	It used to collapse every newline into one run-on line, so the record of what was approved read
	differently from the approval."""

	def test_the_pending_question_block_keeps_its_line_breaks(self):
		audit = _text(AUDIT)
		self.assertIn(".flow-run .question { white-space: pre-wrap; word-break: break-word; }", audit)
		self.assertIn('<div class="question">{{ esc(q.prompt) }}</div>', audit)

	def test_it_still_escapes_the_prompt(self):
		"""`pre-wrap` changes how whitespace is laid out and must not change how the text is
		escaped: this surface is server-rendered HTML, not a Vue interpolation."""
		self.assertIn("esc(q.prompt)", _text(AUDIT))
