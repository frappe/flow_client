"""The known-defect machinery: four outcomes, and which of them hold the gate.

A scenario marked `known_defect` describes something this project has PROVEN is wrong and has not
fixed. It asserts the RIGHT behaviour and is expected to fail. Two things must be true of it and
neither is free:

  - it must never look like a pass, or the defect is buried;
  - it must never hold the suite red, or the suite stops being read.

And the outcome that earns the machinery: a known defect that starts PASSING means the code was
fixed and the record was not. The suite is then asserting something untrue about the system, and
that must fail, because only a person can correct it.

These tests need no platform context: they build `Result` objects directly.
"""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run as runner


def _report(results):
	out = io.StringIO()
	code = runner.report(results, out=out)
	return code, out.getvalue()


def _r(name, passed, known_defect=None):
	return runner.Result(name, f"{name} description", passed, [] if passed else ["it failed"], known_defect)


class TestTheFourVerdicts(unittest.TestCase):
	def test_an_ordinary_scenario_is_pass_or_fail(self):
		self.assertEqual(_r("a", True).verdict, "PASS")
		self.assertEqual(_r("a", False).verdict, "FAIL")

	def test_a_failing_known_defect_is_reported_as_one(self):
		self.assertEqual(_r("a", False, "it is broken").verdict, "KNOWN-DEFECT")

	def test_a_passing_known_defect_is_reported_as_fixed(self):
		self.assertEqual(_r("a", True, "it is broken").verdict, "FIXED")


class TestWhatHoldsTheGate(unittest.TestCase):
	def test_a_known_defect_does_not_fail_the_suite(self):
		code, text = _report([_r("ok", True), _r("broken", False, "written down")])

		self.assertEqual(code, 0)
		self.assertIn("KNOWN_DEFECT=1", text)
		self.assertIn("FAILED=0", text)

	def test_an_ordinary_failure_still_fails_the_suite(self):
		code, _text = _report([_r("ok", True), _r("broken", False)])

		self.assertEqual(code, 1)

	def test_a_known_defect_that_started_passing_fails_the_suite(self):
		"""The point of all of this. The code was fixed and the record was not."""
		code, text = _report([_r("was_broken", True, "written down")])

		self.assertEqual(code, 1)
		self.assertIn("FIXED=1", text)
		self.assertIn("Drop `known_defect` from the scenario", text)

	def test_an_all_green_suite_still_passes(self):
		"""The positive control. Without it, every test above would pass on a report() that
		returned 1 unconditionally."""
		code, text = _report([_r("a", True), _r("b", True)])

		self.assertEqual(code, 0)
		self.assertIn("EVALS=2 PASSED=2 FAILED=0 KNOWN_DEFECT=0 FIXED=0", text)


class TestTheReasonIsNotOptional(unittest.TestCase):
	"""A known defect that does not say what it is, and where it is written down, is
	indistinguishable from a scenario somebody silenced."""

	def test_a_bare_true_is_refused(self):
		with self.assertRaises(ValueError):
			runner._known_defect({"name": "s", "known_defect": True})

	def test_an_empty_reason_is_refused(self):
		with self.assertRaises(ValueError):
			runner._known_defect({"name": "s", "known_defect": "   "})

	def test_no_flag_at_all_is_fine(self):
		self.assertIsNone(runner._known_defect({"name": "s"}))
		self.assertIsNone(runner._known_defect({"name": "s", "known_defect": False}))

	def test_a_real_reason_is_kept_and_collapsed_to_one_line(self):
		note = runner._known_defect({"name": "s", "known_defect": "it is\n  broken\nsee the inbox"})

		self.assertEqual(note, "it is broken see the inbox")


class TestEveryKnownDefectInThisRepositoryExplainsItself(unittest.TestCase):
	"""Reads the real scenario files. A flag added later without a reason fails here."""

	def test_each_marked_scenario_carries_a_reason(self):
		marked = [s for s in runner.load_scenarios() if s.get("known_defect") is not None]

		self.assertGreater(len(marked), 0, "if this is zero the test below proves nothing")
		for scenario in marked:
			note = runner._known_defect(scenario)
			self.assertGreater(len(note), 60, f"{scenario['name']}: say what the defect is")

	# There is deliberately NO test here that runs the marked scenarios and asserts they still
	# reproduce. Running a scenario needs a platform context, which these tests do not have, and a
	# test that skipped itself when the context was missing would be the same mistake this project
	# has already made once: a gate whose failure mode is never observed is a comment.
	#
	# It is not needed. `evals/run.sh` enforces it on every run: a marked scenario that starts
	# passing is reported FIXED and turns EVALS_GATE red, which is the live version of the same
	# assertion and cannot skip itself.


if __name__ == "__main__":
	unittest.main()
