#!/usr/bin/env python3
"""Run the agent-loop scenarios in this process against a scripted model.

There is no network here, no credential, and no real model. The runner builds a code `Agent`
around `ScriptedModel` below and never constructs the platform's own model class, so there is no
code path from here to a provider. `assert_no_real_model()` refuses to start if the environment
suggests otherwise.

These scenarios test the plumbing — which tool is called, whether approval is asked for, what the
exact "Approve" does and what "Deny" and free text do. They say nothing about whether a real model
would choose well. See README.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"

# Any of these being set means someone has a real model configured in this shell. The runner is
# in-process and could import engine code that reads them, so it refuses rather than risks it.
CREDENTIAL_VARS = (
	"OPENAI_API_KEY",
	"ANTHROPIC_API_KEY",
	"OPENROUTER_API_KEY",
	"AZURE_OPENAI_API_KEY",
	"GOOGLE_API_KEY",
	"GEMINI_API_KEY",
	"MISTRAL_API_KEY",
	"COHERE_API_KEY",
	"GROQ_API_KEY",
	"TOGETHER_API_KEY",
	"FLOW_EVALS_ALLOW_REAL",
)


class RealModelConfigured(RuntimeError):
	"""Raised when the environment looks like a real model is available."""


def assert_no_real_model(environ: dict[str, str] | None = None) -> None:
	"""Refuse to run if a real model could be reached from this process.

	Deliberately a hard error and not a warning: an evaluation that quietly used a real model
	would bill someone and would report a different thing from what it claims to report.
	"""
	env = os.environ if environ is None else environ
	found = sorted(name for name in CREDENTIAL_VARS if env.get(name))
	if found:
		raise RealModelConfigured(
			"These scenarios run against a scripted model only, and this environment has "
			f"{', '.join(found)} set. Unset it, or run in a shell that has no model credentials."
		)


# --------------------------------------------------------------------------------------------
# The scripted model
# --------------------------------------------------------------------------------------------


class ScriptedModel:
	"""Returns the scenario's scripted turns in order. It is the only model the runner knows."""

	def __init__(self, script: list[dict[str, Any]]):
		self._script = list(script)
		self.calls: list[dict[str, Any]] = []

	def chat(self, messages, tools=None, *, stream=False):
		from flow.lib.model import ChatResponse, ToolCall

		self.calls.append({"messages": list(messages), "tools": tools})
		if not self._script:
			raise AssertionError("the scenario's model script ran out of turns")
		turn = self._script.pop(0)
		usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
		if turn.get("tool_calls"):
			return ChatResponse(
				content=turn.get("content"),
				tool_calls=[
					ToolCall(id=c["id"], name=c["name"], arguments=c.get("arguments", {}))
					for c in turn["tool_calls"]
				],
				finish_reason="tool_calls",
				usage=usage,
			)
		return ChatResponse(content=turn.get("content", ""), finish_reason="stop", usage=usage)


# --------------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------------


@dataclass
class Result:
	name: str
	description: str
	passed: bool
	failures: list[str] = field(default_factory=list)
	known_defect: str | None = None

	@property
	def verdict(self) -> str:
		"""Four outcomes, not two.

		A scenario carrying `known_defect` describes something this project has PROVEN is wrong
		and has not fixed. It asserts the RIGHT behaviour and is expected to fail. It must not be
		allowed to look like a pass — that would bury the defect — and it must not be allowed to
		make the suite red either, because a defect already written down is not news and a suite
		that is permanently red stops being read.

		The fourth outcome is the one that earns the machinery: a known defect that starts
		PASSING. Someone fixed the code and did not update the record, so the record is now
		lying about the state of the system. That fails the suite, and it is the only one of the
		four whose fix is to edit a scenario rather than the engine.
		"""
		if self.known_defect:
			return "KNOWN-DEFECT" if not self.passed else "FIXED"
		return "PASS" if self.passed else "FAIL"


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[dict[str, Any]]:
	scenarios = []
	for path in sorted(directory.glob("*.yaml")):
		data = yaml.safe_load(path.read_text())
		if data.get("name") != path.stem:
			raise ValueError(f"{path.name}: 'name' is {data.get('name')!r}, expected {path.stem!r}")
		expect = data.get("expect") or {}
		if expect.get("raises") is not None:
			# Non-empty `str`, checked here rather than trusted. `raises: ""` passes an
			# `is not None` guard and then matches EVERY exception — a scenario silenced against
			# any crash at all. `raises: false` is worse: it reaches the substring test and
			# raises TypeError from inside `run_scenario`'s own `except`, taking the whole run
			# down with no summary line, which the wrapper reports as a gate failure with no
			# reason on it.
			if not isinstance(expect["raises"], str) or not expect["raises"].strip():
				raise ValueError(
					f"{path.name}: 'expect.raises' must be a non-empty string naming part of the "
					f"refusal, not {expect['raises']!r}"
				)
			contradictory = sorted(k for k in _RESULT_KEYS if expect.get(k) is not None)
			if contradictory:
				raise ValueError(
					f"{path.name}: 'expect.raises' cannot be combined with {contradictory} — "
					"a run that was refused has no result to check those against"
				)
		scenarios.append(data)
	return scenarios


def _build_tools(spec: list[dict[str, Any]], executed: list[tuple[str, dict[str, Any]]]):
	"""Every tool is a stub that records its call. Nothing in a scenario touches anything real."""
	from flow.lib.tool import Tool

	def make(name: str, result: str):
		# A closure per tool, so the stub's signature is **kwargs only and nothing about the
		# recording machinery can be mistaken for one of the tool's own parameters.
		def run(**kwargs: Any) -> str:
			executed.append((name, kwargs))
			return result

		return run

	tools = []
	for t in spec:
		name, result = t["name"], t.get("result", "ok")
		shipped = _shipped_tool(t.get("builtin"))
		tools.append(
			Tool(
				name=name,
				description=t.get("description") or (shipped.description if shipped else ""),
				parameters=t.get("parameters")
				or (shipped.parameters if shipped else {"type": "object", "properties": {}}),
				# The body is ALWAYS the recording stub, even for a shipped tool: a scenario must
				# never write anything. What a `builtin:` entry borrows is the tool's declared
				# surface — whether it is gated, and the question it raises — which is exactly the
				# part a registry change can break without any test noticing.
				func=make(name, result),
				requires_confirmation=bool(
					t["requires_confirmation"]
					if "requires_confirmation" in t
					else (shipped.requires_confirmation if shipped else False)
				),
				confirm_prompt=shipped.confirm_prompt if shipped else None,
				title=shipped.title if shipped else None,
			)
		)
	return tools


def _shipped_tool(name: str | None):
	"""The engine's own tool of that name, or None.

	A scenario naming one is asserting about the REGISTRY — the flag and the question a tool ships
	with — rather than about a tool the scenario invented. Those are the two halves that can
	disagree, and a suite of invented tools can never see it.
	"""
	if not name:
		return None
	from flow.tools.builtins import BUILTIN_TOOLS

	for tool in BUILTIN_TOOLS:
		if tool.name == name:
			return tool
	raise ValueError(f"no builtin tool named {name!r}")


def _check_tool_calls(expected: list[dict[str, Any]], actual, failures: list[str]) -> None:
	if len(expected) != len(actual):
		failures.append(
			f"expected {len(expected)} tool call(s), saw {len(actual)}: {[c.name for c in actual]}"
		)
		return
	for i, (want, got) in enumerate(zip(expected, actual, strict=True)):
		if want["name"] != got.name:
			failures.append(f"tool call {i}: expected {want['name']!r}, saw {got.name!r}")
		for key, value in (want.get("arguments") or {}).items():
			if got.arguments.get(key) != value:
				failures.append(
					f"tool call {i} argument {key!r}: expected {value!r}, saw {got.arguments.get(key)!r}"
				)


def _as_list(value) -> list[str]:
	"""A bare string in the YAML means one string, not a sequence of characters. Iterating it
	directly would assert that a result contains "n", "o", "t"... which nearly anything does — a
	check that cannot fail, written by a typo."""
	if value is None:
		return []
	return [value] if isinstance(value, str) else list(value)


def _check_tool_results(expected: dict[str, Any], messages, label: str, failures: list[str]) -> None:
	"""Assert on what each pending call was TOLD, by tool_call_id.

	`executed` says what ran; this says what the model was handed. They are different questions,
	and some defects are invisible to the first: nothing runs, and the person's own answer is
	written in as the tool's output.
	"""
	results = {m["tool_call_id"]: m["content"] for m in messages if m.get("role") == "tool"}
	for call_id, checks in expected.items():
		if call_id not in results:
			failures.append(f"[{label}] no tool result was recorded for {call_id!r}")
			continue
		content = results[call_id]
		for text in _as_list(checks.get("contains")):
			if text not in content:
				failures.append(f"[{label}] {call_id} result does not contain {text!r}: {content!r}")
		for text in _as_list(checks.get("absent")):
			if text in content:
				failures.append(f"[{label}] {call_id} result must not contain {text!r}: {content!r}")
		if "equals" in checks and content != checks["equals"]:
			failures.append(f"[{label}] {call_id} result is {content!r}, expected {checks['equals']!r}")


def _check_absent_text(forbidden: list[str], haystack: str, where: str, failures: list[str]) -> None:
	for text in forbidden:
		if text.lower() in haystack.lower():
			failures.append(f"{where} contains text that must not appear: {text!r}")


# Scenario keys that describe a run that produced a RESULT. A run that raised has none of them to
# be checked against, so asking for both is a scenario that cannot be satisfied either way — which
# is the shape of a scenario somebody silenced by accident.
_RESULT_KEYS = ("pauses", "tool_calls", "questions", "after")


def refusal_failures(expect: dict[str, Any], error: BaseException | None) -> list[str] | None:
	"""Failures for a scenario that expects a refusal, or None when it does not expect one.

	`error` is the exception the run raised, or **None when the run completed**. Both outcomes
	come here, and that is the whole point: a scenario expecting a refusal has to fail against an
	engine that does not refuse, and the run completing is exactly what that looks like. Checking
	`raises` only where an exception is already in hand makes the key vacuous in the one case it
	exists to catch — the scenario would go green against the very engine it was written to
	measure. (Found by the probe that reverts the engine fix and requires this scenario to fail.)

	Pure: the expectation and the exception, nothing else. `evals/tests/` runs as plain unittest
	with no platform context (see both test modules' docstrings), so the branch that decides
	whether a raise was the right answer has to be reachable without importing the engine.

	`absent_text` is applied to the refusal here and nowhere else. The three existing call sites
	run over questions, a paused reply and a resume reply, and a run that raised reaches none of
	them — so without this, a scenario expecting a refusal would carry an `absent_text` list that
	checked nothing while reading exactly as though it did.
	"""
	wanted = expect.get("raises")
	if wanted is None:
		return None
	if error is None:
		return [f"expected the run to be refused with {wanted!r}, but it completed without refusing"]
	failures: list[str] = []
	actual = str(error)
	if wanted not in actual:
		failures.append(f"expected the run to be refused with {wanted!r}, but it raised {actual!r}")
	_check_absent_text(expect.get("absent_text", []), actual, "the refusal", failures)
	return failures


def run_scenario(scenario: dict[str, Any]) -> Result:
	from flow.lib.agent import Agent

	failures: list[str] = []
	expect = scenario.get("expect", {})
	forbidden = expect.get("absent_text", [])

	executed: list[tuple[str, dict[str, Any]]] = []
	model = ScriptedModel(scenario["model_script"])
	agent = Agent(
		model=model,
		name=scenario["name"],
		instructions=scenario.get("agent", {}).get("instructions"),
		tools=_build_tools(scenario.get("tools", []), executed),
		# A scenario may declare an unattended run — the one flag that turns every gate in the
		# engine off at once. A suite that could not express it could not record what it costs.
		auto_approve=bool(scenario.get("agent", {}).get("auto_approve", False)),
	)

	try:
		result = agent.run(scenario["user_message"])
	except Exception as e:
		# A scenario that does not behave as written must FAIL, not take the suite down with it.
		# The commonest shape is the important one: a scenario expecting a pause, run against an
		# engine that does not pause, walks on to a turn the script does not have. That is exactly
		# what measuring a scenario against an older engine looks like, and the answer to it is a
		# red row with the reason on it — not a traceback and no summary line at all.
		#
		# Unless a refusal is the RIGHT answer. Some behaviour this suite has to be able to assert
		# is "the engine refuses this and nothing happens", and without a way to say so such a
		# scenario could never pass — it would sit red forever as a known defect while the record
		# said the opposite, which is the one outcome the known-defect machinery exists to prevent.
		refused = refusal_failures(expect, e)
		if refused is not None:
			# The whole point of refusing is that nothing happened, so a scenario that expects a
			# refusal must also observe that. Without this an engine that ran both writes and
			# THEN raised would report PASS — and this is the scenario named for a double write.
			# `tool_calls:` cannot carry the claim, because the loader forbids it beside `raises`.
			if executed:
				refused = [*refused, f"expected nothing to run, saw {[n for n, _a in executed]}"]
			return Result(
				scenario["name"],
				scenario.get("description", ""),
				not refused,
				refused,
				known_defect=_known_defect(scenario),
			)
		return Result(
			scenario["name"],
			scenario.get("description", ""),
			False,
			[f"the run raised {type(e).__name__}: {e}"],
			known_defect=_known_defect(scenario),
		)

	# The run completed. If the scenario said it must be refused, that is the failure — and it is
	# the one that matters, because it is what an engine WITHOUT the fix produces.
	refused = refusal_failures(expect, None)
	if refused:
		return Result(
			scenario["name"],
			scenario.get("description", ""),
			False,
			refused,
			known_defect=_known_defect(scenario),
		)

	if expect.get("pauses") is not None and result.paused != bool(expect["pauses"]):
		failures.append(f"expected paused={expect['pauses']}, saw paused={result.paused}")
	_check_tool_calls(expect.get("tool_calls", []), result.tool_calls, failures)

	questions = expect.get("questions")
	if questions is not None:
		if len(result.questions) != questions.get("count", len(result.questions)):
			failures.append(f"expected {questions['count']} question(s), saw {len(result.questions)}")
		for q in result.questions:
			if "options" in questions and q.options != questions["options"]:
				failures.append(f"question options were {q.options}, expected {questions['options']}")
			for text in _as_list(questions.get("contains")):
				if text not in q.prompt:
					failures.append(f"the approval question does not contain {text!r}: {q.prompt!r}")
			for text in _as_list(questions.get("absent")):
				if text in q.prompt:
					failures.append(f"the approval question must not contain {text!r}: {q.prompt!r}")
			_check_absent_text(forbidden, q.prompt, "an approval question", failures)

	if result.paused:
		_check_absent_text(
			forbidden, result.output or "", "the reply shown while a change is pending", failures
		)

	# What the model was TOLD by a run that completed. Before this, `tool_results` and the
	# forward-path `absent_text` were only ever consulted inside an answer case (`after:`) or on a
	# refusal, so a scenario about a run that completes carried keys that checked nothing while
	# reading exactly as though they did. A scenario whose whole claim is "it was refused and the
	# model was told so" needs them here, because such a run never pauses and has no answers.
	_check_tool_results(expect.get("tool_results", {}), result.messages, "the completed run", failures)
	if not result.paused:
		_check_absent_text(forbidden, result.output or "", "the reply from the completed run", failures)
		for message in result.messages:
			if message.get("role") == "tool":
				_check_absent_text(forbidden, message.get("content") or "", "a tool result", failures)

	# Each answer set is applied to the SAME pause, from the same transcript.
	for label, case in (expect.get("after") or {}).items():
		_run_answer_case(scenario, label, case, result, forbidden, failures)

	return Result(
		scenario["name"],
		scenario.get("description", ""),
		not failures,
		failures,
		known_defect=_known_defect(scenario),
	)


def _known_defect(scenario: dict[str, Any]) -> str | None:
	"""The recorded reason a scenario is expected to fail, or None.

	A bare `true` is refused. A known defect that does not say what it is, and where it is written
	down, is indistinguishable from a scenario somebody silenced.
	"""
	note = scenario.get("known_defect")
	if note is None or note is False:
		return None
	if not isinstance(note, str) or not note.strip():
		raise ValueError(
			f"{scenario['name']}: known_defect must be a non-empty description of the defect, not {note!r}"
		)
	return " ".join(note.split())


def _run_answer_case(scenario, label, case, paused, forbidden, failures) -> None:
	"""Replay the pause with one answer set, on a fresh agent, and assert what actually ran.

	The agent is always fresh — never the one that paused — which is what a client reloading a
	conversation produces. A case may also give its own `tools`, replacing the scenario's for the
	resume only: the runtime that resumes a run is rebuilt from a record and is not necessarily
	the one that paused it, so a tool can be gone, renamed or no longer gated by the time an
	answer arrives, and a scenario cannot describe that without saying it.
	"""
	from flow.lib.agent import Agent

	executed: list[tuple[str, dict[str, Any]]] = []
	model = ScriptedModel(case.get("model_script", []))
	agent = Agent(
		model=model,
		name=scenario["name"],
		instructions=scenario.get("agent", {}).get("instructions"),
		tools=_build_tools(case.get("tools", scenario.get("tools", [])), executed),
	)
	try:
		# Deliberately no record of what was asked: a scenario must run against any engine in
		# this repository's history, so the runner uses only the call every version has.
		resumed = agent.resume([dict(m) for m in paused.messages], case["answers"])
	except Exception as e:  # a scenario that cannot even resume is a failure, not a crash
		failures.append(f"[{label}] resume raised {type(e).__name__}: {e}")
		return

	_check_tool_results(case.get("tool_results") or {}, resumed.messages, label, failures)

	ran = [name for name, _args in executed]
	if sorted(ran) != sorted(case.get("executed", [])):
		failures.append(f"[{label}] expected {sorted(case.get('executed', []))} to run, saw {sorted(ran)}")
	if "output" in case and resumed.output != case["output"]:
		failures.append(f"[{label}] expected output {case['output']!r}, saw {resumed.output!r}")
	if "paused" in case and resumed.paused != bool(case["paused"]):
		failures.append(f"[{label}] expected paused={case['paused']}, saw {resumed.paused}")
	_check_absent_text(forbidden, resumed.output or "", f"[{label}] the reply", failures)


# --------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------


def report(results: list[Result], out=sys.stdout) -> int:
	width = max((len(r.name) for r in results), default=4)
	pad = " " * (width + 2)
	print(f"{'SCENARIO'.ljust(width)}  RESULT        DESCRIPTION", file=out)
	print(f"{'-' * width}  ------------  -----------", file=out)
	for r in results:
		print(f"{r.name.ljust(width)}  {r.verdict.ljust(12)}  {r.description}", file=out)
		if r.verdict == "KNOWN-DEFECT":
			print(f"{pad}              ! {r.known_defect}", file=out)
		elif r.verdict == "FIXED":
			print(
				f"{pad}              ! this no longer reproduces. Drop `known_defect` from the "
				f"scenario — the record now says something untrue. It was: {r.known_defect}",
				file=out,
			)
		for failure in r.failures:
			print(f"{pad}              - {failure}", file=out)

	counts = Counter(r.verdict for r in results)
	print(
		f"\nEVALS={len(results)} PASSED={counts['PASS']} FAILED={counts['FAIL']} "
		f"KNOWN_DEFECT={counts['KNOWN-DEFECT']} FIXED={counts['FIXED']}",
		file=out,
	)
	# A known defect does not fail the suite: it is already written down. A known defect that has
	# started passing DOES, because the record is now wrong and only a person can correct it.
	return 0 if not counts["FAIL"] and not counts["FIXED"] else 1


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--scenario", help="run one scenario by name")
	parser.add_argument("--list", action="store_true", help="list scenario names and exit")
	args = parser.parse_args(argv)

	assert_no_real_model()

	scenarios = load_scenarios()
	if args.list:
		for s in scenarios:
			print(s["name"])
		return 0
	if args.scenario:
		scenarios = [s for s in scenarios if s["name"] == args.scenario]
		if not scenarios:
			print(f"no scenario named {args.scenario!r}", file=sys.stderr)
			return 2

	return report([run_scenario(s) for s in scenarios])


if __name__ == "__main__":
	raise SystemExit(main())
