"""Tests for the scenario runner itself.

Plain unittest, outside the bench's test gate, because nothing under `flow/` changes for these
evaluations. `run.py` imports the engine lazily inside its functions, so this module needs only
PyYAML:

    python3 -m unittest discover -s evals/tests -t .
"""

import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run as runner


class TestItRefusesARealModel(unittest.TestCase):
	"""The runner must refuse rather than quietly use a real model: that would bill someone and
	would report a different thing from what the README says it reports."""

	def test_a_provider_credential_in_the_environment_refuses_the_run(self):
		for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
			with self.subTest(var=var), self.assertRaises(runner.RealModelConfigured) as caught:
				runner.assert_no_real_model({var: "sk-whatever"})
			self.assertIn(var, str(caught.exception))

	def test_the_explicit_escape_hatch_also_refuses(self):
		with self.assertRaises(runner.RealModelConfigured):
			runner.assert_no_real_model({"FLOW_EVALS_ALLOW_REAL": "1"})

	def test_an_empty_credential_is_not_treated_as_configured(self):
		"""An exported-but-blank variable is the ordinary state of a shell that has none."""
		runner.assert_no_real_model({"OPENAI_API_KEY": ""})

	def test_a_clean_environment_is_allowed(self):
		"""The positive control. Without this, every test above would pass on a function that
		raised unconditionally."""
		runner.assert_no_real_model({"PATH": "/usr/bin", "HOME": "/home/someone"})

	def test_every_listed_variable_is_actually_checked(self):
		"""A name in the list that the check ignores would be a comment, not a guard."""
		for var in runner.CREDENTIAL_VARS:
			with self.subTest(var=var), self.assertRaises(runner.RealModelConfigured):
				runner.assert_no_real_model({var: "x"})


class TestItCannotReachAProvider(unittest.TestCase):
	def test_the_runner_never_names_the_platforms_own_model_class(self):
		"""The only model the runner knows is the scripted one. If this file ever constructs the
		engine's `Model`, a scenario could make a real request."""
		source = (Path(runner.__file__)).read_text()
		self.assertNotIn("Model(", source.replace("ScriptedModel(", ""))
		self.assertNotIn("import requests", source)
		self.assertNotIn("urllib", source)
		self.assertNotIn("site_config", source)

	def test_the_scripted_model_is_what_a_scenario_gets(self):
		self.assertTrue(hasattr(runner.ScriptedModel, "chat"))
		model = runner.ScriptedModel([{"content": "hi"}])
		self.assertEqual(model.calls, [])


class TestScenarioLoading(unittest.TestCase):
	def test_every_shipped_scenario_parses_and_is_named_after_its_file(self):
		scenarios = runner.load_scenarios()

		self.assertGreaterEqual(len(scenarios), 5)
		for s in scenarios:
			with self.subTest(name=s["name"]):
				self.assertIn("user_message", s)
				self.assertIn("model_script", s)
				self.assertIn("expect", s)

	def test_a_scenario_whose_name_disagrees_with_its_filename_is_rejected(self):
		import tempfile

		with tempfile.TemporaryDirectory() as d:
			Path(d, "alpha.yaml").write_text("name: beta\n")
			with self.assertRaises(ValueError):
				runner.load_scenarios(Path(d))

	def test_the_approval_path_is_actually_covered(self):
		"""The five scenarios must between them exercise Approve, Deny and free text. A suite
		that only covered the happy path would say nothing about the approval contract."""
		answer_values = set()
		for s in runner.load_scenarios():
			for case in (s.get("expect", {}).get("after") or {}).values():
				answer_values.update(str(v) for v in case["answers"].values())

		self.assertIn("Approve", answer_values)
		self.assertIn("Deny", answer_values)
		self.assertTrue(
			[v for v in answer_values if v not in ("Approve", "Deny")],
			"no scenario answers with free text",
		)


class TestReporting(unittest.TestCase):
	def test_a_failing_scenario_makes_the_summary_say_so(self):
		import io

		out = io.StringIO()
		code = runner.report(
			[
				runner.Result("ok_one", "fine", True),
				runner.Result("bad_one", "not fine", False, ["it executed something it should not have"]),
			],
			out=out,
		)
		text = out.getvalue()

		self.assertEqual(code, 1)
		self.assertIn("EVALS=2 PASSED=1 FAILED=1", text)
		self.assertIn("it executed something it should not have", text)

	def test_all_passing_reports_zero_failures(self):
		import io

		out = io.StringIO()
		code = runner.report([runner.Result("ok_one", "fine", True)], out=out)

		self.assertEqual(code, 0)
		self.assertIn("FAILED=0", out.getvalue())


class TestASccenarioCanExpectARefusal(unittest.TestCase):
	"""AT11 — the four branches of `refusal_failures`.

	Called directly, never through `run_scenario`, which opens by importing the engine. This
	module runs with no platform context (see the docstring at the top of this file), and
	`TestItCannotReachAProvider` exists precisely to keep it that way — so the branch that decides
	whether a raise was the right answer has to be reachable without an engine import, and this is
	the test that proves it is.
	"""

	FORBIDDEN: ClassVar[list[str]] = ["frappe", "erpnext", "mariadb", "openai", "anthropic", "gpt-", "claude"]

	def test_a_scenario_that_expects_a_refusal_passes_on_it(self):
		failures = runner.refusal_failures(
			{"raises": "could not be told apart"},
			ValueError(
				"Two actions in one reply could not be told apart, so one approval would have answered both."
			),
		)
		self.assertEqual(failures, [])

	def test_a_scenario_that_expects_a_refusal_fails_on_the_wrong_one(self):
		"""A `raises:` that matches an unrelated error would silence a scenario, so a wrong one
		must fail and must say both texts."""
		failures = runner.refusal_failures(
			{"raises": "could not be told apart"}, RuntimeError("the database went away")
		)
		self.assertEqual(len(failures), 1)
		self.assertIn("could not be told apart", failures[0])
		self.assertIn("the database went away", failures[0])

	def test_a_run_that_completed_when_a_refusal_was_expected_fails(self):
		"""The branch a probe caught missing. `raises` checked only where an exception is already
		in hand is vacuous in the one case the key exists for: run the scenario against an engine
		that does NOT refuse, and the run simply completes, nothing looks at `raises`, and the row
		goes green against the very engine it was written to measure."""
		failures = runner.refusal_failures({"raises": "could not be told apart"}, None)
		self.assertEqual(len(failures), 1)
		self.assertIn("could not be told apart", failures[0])
		self.assertIn("completed", failures[0])

	def test_a_completed_run_with_no_refusal_expected_is_not_a_failure(self):
		"""The control: every ordinary scenario in the suite takes this path on every run."""
		self.assertIsNone(runner.refusal_failures({}, None))
		self.assertIsNone(runner.refusal_failures({"pauses": True}, None))

	def test_a_raise_with_no_expectation_still_fails(self):
		"""The control. Returning None hands the caller back to today's behaviour, where an
		unexpected raise is a red row with the reason on it. If this ever returned [] the new key
		would turn every crash in the suite into a pass."""
		self.assertIsNone(runner.refusal_failures({}, RuntimeError("boom")))
		self.assertIsNone(runner.refusal_failures({"pauses": True}, RuntimeError("boom")))
		self.assertIsNone(runner.refusal_failures({"raises": None}, RuntimeError("boom")))

	def test_a_forbidden_word_in_the_refusal_fails_even_when_raises_matched(self):
		"""`absent_text` is checked nowhere else on this path: the three existing call sites all
		run over a result, and a run that raised has none. Without this the key would read as
		coverage and be none."""
		failures = runner.refusal_failures(
			{"raises": "could not be told apart", "absent_text": self.FORBIDDEN},
			ValueError("Two Frappe actions in one reply could not be told apart."),
		)
		self.assertEqual(len(failures), 1)
		self.assertIn("frappe", failures[0].lower())

	def test_a_clean_refusal_with_absent_text_still_passes(self):
		"""The control for the test above: `absent_text` must not fail a refusal that is clean."""
		failures = runner.refusal_failures(
			{"raises": "could not be told apart", "absent_text": self.FORBIDDEN},
			ValueError("Two actions in one reply could not be told apart. Nothing was carried out."),
		)
		self.assertEqual(failures, [])


class TestARefusalCannotBeCombinedWithAResult(unittest.TestCase):
	"""The loader's contradiction check. A scenario asking for both a refusal and a result can be
	satisfied by neither, which is what a scenario somebody silenced by accident looks like."""

	def _write(self, tmp, body):
		path = Path(tmp) / "contradictory.yaml"
		path.write_text(body)
		return path

	def test_raises_beside_pauses_is_refused_by_the_loader(self):
		import tempfile

		body = (
			"name: contradictory\n"
			"user_message: go\n"
			"model_script: []\n"
			"expect:\n"
			"  raises: nope\n"
			"  pauses: true\n"
		)
		with tempfile.TemporaryDirectory() as tmp:
			self._write(tmp, body)
			with self.assertRaises(ValueError) as caught:
				runner.load_scenarios(Path(tmp))
		self.assertIn("raises", str(caught.exception))
		self.assertIn("pauses", str(caught.exception))

	def test_an_empty_raises_is_refused(self):
		"""`raises: ""` passes an `is not None` guard and then matches EVERY exception — a
		scenario silenced against any crash at all, which is the sharpest form of the risk the
		spec records for this new key."""
		import tempfile

		body = 'name: empty\nuser_message: go\nmodel_script: []\nexpect:\n  raises: ""\n'
		with tempfile.TemporaryDirectory() as tmp:
			(Path(tmp) / "empty.yaml").write_text(body)
			with self.assertRaises(ValueError) as caught:
				runner.load_scenarios(Path(tmp))
		self.assertIn("non-empty string", str(caught.exception))

	def test_a_non_string_raises_is_refused(self):
		"""`raises: false` is worse than useless: it reaches the substring test and raises
		TypeError from inside `run_scenario`'s own `except`, taking the whole run down with no
		summary line — which the wrapper can only report as a gate failure with no reason."""
		import tempfile

		body = "name: falsy\nuser_message: go\nmodel_script: []\nexpect:\n  raises: false\n"
		with tempfile.TemporaryDirectory() as tmp:
			(Path(tmp) / "falsy.yaml").write_text(body)
			with self.assertRaises(ValueError) as caught:
				runner.load_scenarios(Path(tmp))
		self.assertIn("non-empty string", str(caught.exception))

	def test_raises_alone_loads(self):
		"""The control. Without it the check above would pass on a loader that refused every
		scenario carrying `raises`."""
		import tempfile

		body = "name: fine\nuser_message: go\nmodel_script: []\nexpect:\n  raises: nope\n"
		with tempfile.TemporaryDirectory() as tmp:
			(Path(tmp) / "fine.yaml").write_text(body)
			scenarios = runner.load_scenarios(Path(tmp))
		self.assertEqual([s["name"] for s in scenarios], ["fine"])


if __name__ == "__main__":
	unittest.main()
