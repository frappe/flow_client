# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""REVIEW-FLOW-10 M5 — the shipped assistant prompt told the model to waive approvals.

It said, of a run that fires on its own, "set auto_approve=1 unless the user says otherwise — a
trigger runs unattended, so any tool call needing confirmation would stall forever without it."

Both halves were wrong by the time the review found it. The stall is what the engine now stops on
its own: a run with nobody in it is computed from what the run IS, not from that flag, and a tool
that needs approving is refused rather than parked. And the flag it recommended persisting is the
one thing that makes a run with somebody in it count as having nobody: it is read by every later
caller of the same record, not only by the scheduled run it was written for.

So every recurring agent the assistant ever set up carried a standing instruction to skip approvals,
justified by a problem that no longer exists.
"""

from frappe.tests import UnitTestCase

from flow.assistant.assistant import ASSISTANT_INSTRUCTIONS as INSTRUCTIONS

# The clause that replaced it. Quoted here, not imported, so that rewriting the prompt cannot
# quietly rewrite what this test checks for.
REPLACEMENT = "A run that fires on its own has nobody to approve anything"


class TestTheAssistantNeverTellsTheModelToWaiveApprovals(UnitTestCase):
	def test_the_shipped_prompt_does_not_mention_auto_approve(self):
		self.assertNotIn(
			"auto_approve",
			INSTRUCTIONS,
			"the prompt still tells the model to turn approvals off on a run it creates",
		)

	def test_and_it_says_what_is_true_instead(self):
		"""Deleting the clause is not enough on its own: without a replacement the model is left
		to guess what happens to a gated tool in a run nobody is watching, and the guess that
		matches the old prompt is that it waits."""
		self.assertIn(REPLACEMENT, INSTRUCTIONS)
		self.assertIn("refused", INSTRUCTIONS)

	def test_the_replacement_names_no_platform_vendor_or_model(self):
		"""CLAUDE.md rule 3, over the sentence this change is responsible for.

		Scoped to the replacement deliberately. The rest of this prompt names the platform
		throughout and has since long before this change; that is a separate, larger piece of work
		and widening the assertion here would have made this test fail for a reason it is not
		about.
		"""
		self._assert_clean(REPLACEMENT)

	def test_control_the_check_can_go_red(self):
		with self.assertRaises(AssertionError):
			self._assert_clean("a trigger in Frappe runs unattended")

	def _assert_clean(self, text: str) -> None:
		for word in ("frappe", "flow", "erpnext", "mariadb", "openai", "anthropic", "gpt", "claude"):
			self.assertNotIn(word, text.lower(), f"{word!r} appears in text the model reads")
