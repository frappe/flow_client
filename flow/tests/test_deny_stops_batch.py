# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S14 — a Deny in a batch executes nothing.

One pause can carry more than one question. Before this change, answering two of them
`{"k1": "Approve", "k2": "Deny"}` ran k1's tool and only then halted the turn: a person who
refused one action in a group had not stopped the group.

These tests exercise the real resume path. Every tool here records its own calls, so "nothing
executed" is asserted against a list, never inferred from the result shape.
"""

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from flow.lib import agent as agent_module
from flow.lib.agent import Agent, Done, ToolEnded
from flow.lib.model import ChatResponse, Model, ToolCall
from flow.lib.tool import tool


class FakeModel:
	"""Returns scripted responses and remembers every call, so a test can assert the model
	was not consulted again."""

	def __init__(self, responses: list[ChatResponse]):
		self._responses = list(responses)
		self.calls: list[dict[str, Any]] = []

	def chat(self, messages, tools=None, *, stream=False):
		self.calls.append({"messages": list(messages), "tools": tools, "stream": stream})
		if not self._responses:
			raise AssertionError("FakeModel ran out of scripted responses")
		response = self._responses.pop(0)
		if stream:
			return _scripted_stream(response)
		return response


def _scripted_stream(response: ChatResponse):
	if response.content:
		yield response.content
	return response


def _final(text: str) -> ChatResponse:
	return ChatResponse(
		content=text,
		finish_reason="stop",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


def _calls(*specs: tuple[str, dict[str, Any], str]) -> ChatResponse:
	"""One assistant turn asking for several tools at once: (name, arguments, call_id)."""
	return ChatResponse(
		content=None,
		tool_calls=[ToolCall(id=call_id, name=name, arguments=args) for name, args, call_id in specs],
		finish_reason="tool_calls",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


WITHHELD = {
	"status": "not_executed",
	"message": "Nothing in this group ran. The user approved this action but denied another action in the same group.",
	"user_answer": "Approve",
}
DENIED = {"status": "denied", "message": "User denied this tool call."}


def _tool_results(messages: list[dict[str, Any]]) -> dict[str, str]:
	"""tool_call_id → content, for every tool result in the transcript."""
	return {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}


class _Recorder:
	"""A set of confirmation-gated tools that record what actually ran."""

	def __init__(self):
		self.ran: list[tuple[str, dict[str, Any]]] = []

		recorder = self

		@tool(requires_confirmation=True)
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			recorder.ran.append(("send_money", {"to": to, "amount": amount}))
			return f"sent {amount} to {to}"

		@tool(requires_confirmation=True)
		def delete_records(folder: str) -> str:
			"""Delete a folder of records."""
			recorder.ran.append(("delete_records", {"folder": folder}))
			return f"deleted {folder}"

		@tool(requires_confirmation=True)
		def send_email(to: str) -> str:
			"""Send an email."""
			recorder.ran.append(("send_email", {"to": to}))
			return f"emailed {to}"

		self.send_money = send_money
		self.delete_records = delete_records
		self.send_email = send_email
		self.tools = [send_money, delete_records, send_email]


def _pause_on_two(recorder: _Recorder, extra: list[ChatResponse] | None = None):
	"""Run to a pause holding two questions: k1 send_money, k2 delete_records."""
	model = FakeModel(
		[
			_calls(
				("send_money", {"to": "alice", "amount": 500}, "k1"),
				("delete_records", {"folder": "invoices"}, "k2"),
			),
			*(extra or []),
		]
	)
	agent = Agent(model=model, tools=recorder.tools)
	paused = agent.run("pay alice and clear the invoices")
	return agent, model, paused


class TestDenyStopsTheBatch(UnitTestCase):
	def test_the_pause_really_does_carry_two_questions_and_nothing_has_run(self):
		"""Precondition. If this fails, every other test in this class is measuring nothing."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_two(recorder)

		self.assertTrue(paused.paused)
		self.assertEqual([q.key for q in paused.questions], ["k1", "k2"])
		self.assertEqual(recorder.ran, [])

	def test_approve_beside_deny_executes_nothing(self):
		recorder = _Recorder()
		# Only the pausing response is scripted: another model call would raise.
		agent, model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		self.assertEqual(recorder.ran, [])
		self.assertEqual(len(model.calls), 1)
		self.assertFalse(resumed.paused)

	def test_deny_beside_approve_is_the_same_whichever_way_round_the_answers_are(self):
		"""Same transcript, the Deny on the first call instead of the second."""
		recorder = _Recorder()
		agent, model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Deny", "k2": "Approve"})

		self.assertEqual(recorder.ran, [])
		self.assertEqual(len(model.calls), 1)
		self.assertFalse(resumed.paused)

	def test_the_order_of_the_answers_map_does_not_change_it(self):
		"""The same two answers, inserted in the opposite order. Execution follows the
		transcript, so a dict that happens to iterate Deny-first must not be what saves it."""
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder)
		answers = {}
		answers["k2"] = "Deny"
		answers["k1"] = "Approve"

		agent.resume(paused.messages, answers)

		self.assertEqual(recorder.ran, [])

	def test_one_deny_withholds_every_approve_in_a_batch_of_three(self):
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("send_money", {"to": "alice", "amount": 500}, "k1"),
					("send_email", {"to": "bob"}, "k2"),
					("delete_records", {"folder": "invoices"}, "k3"),
				)
			]
		)
		agent = Agent(model=model, tools=recorder.tools)
		paused = agent.run("do three things")

		agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny", "k3": "Approve"})

		self.assertEqual(recorder.ran, [])

	def test_the_withheld_call_records_the_persons_own_answer(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		results = _tool_results(resumed.messages)
		self.assertEqual(json.loads(results["k1"]), WITHHELD)
		self.assertEqual(json.loads(results["k1"])["user_answer"], "Approve")

	def test_the_denied_calls_own_result_is_unchanged(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		self.assertEqual(json.loads(_tool_results(resumed.messages)["k2"]), DENIED)

	def test_the_run_halts_exactly_as_a_deny_halts_it_today(self):
		recorder = _Recorder()
		agent, model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		self.assertIsNone(resumed.output)
		self.assertEqual(resumed.iterations, 0)
		self.assertFalse(resumed.paused)
		self.assertEqual(len(model.calls), 1)

	def test_every_pending_call_still_gets_a_result_so_none_is_left_dangling(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		self.assertEqual(sorted(_tool_results(resumed.messages)), ["k1", "k2"])

	def test_the_streaming_resume_withholds_identically(self):
		recorder = _Recorder()
		agent, model, paused = _pause_on_two(recorder)

		events = list(agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"}, stream=True))

		self.assertEqual(recorder.ran, [])
		self.assertEqual(len(model.calls), 1)
		ended = [e for e in events if isinstance(e, ToolEnded)]
		self.assertEqual([e.id for e in ended], ["k1", "k2"])
		self.assertEqual(json.loads(ended[0].result), WITHHELD)
		self.assertEqual(json.loads(ended[1].result), DENIED)
		self.assertIsInstance(events[-1], Done)
		self.assertFalse(events[-1].result.paused)
		self.assertIsNone(events[-1].result.output)


class TestWhatS14MustNotChange(UnitTestCase):
	"""Approve-only, free-text-only and single-question behaviour, pinned."""

	def test_two_approvals_still_execute_both_and_the_run_continues(self):
		recorder = _Recorder()
		agent, model, paused = _pause_on_two(recorder, extra=[_final("both done")])

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Approve"})

		self.assertEqual(
			recorder.ran,
			[("send_money", {"to": "alice", "amount": 500}), ("delete_records", {"folder": "invoices"})],
		)
		self.assertEqual(resumed.output, "both done")
		self.assertEqual(len(model.calls), 2)

	def test_approve_beside_free_text_still_executes_the_approved_one_and_redirects_the_other(self):
		"""Today's behaviour, pinned deliberately. The spec's Open question 1 asks the owner
		whether free text should stop the batch as a Deny now does; until that is decided this
		test is what makes a change to it visible."""
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder, extra=[_final("adjusted")])

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "make it smaller"})

		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])
		redirect = json.loads(_tool_results(resumed.messages)["k2"])
		self.assertEqual(redirect["status"], "redirect")
		self.assertEqual(redirect["user_feedback"], "make it smaller")
		self.assertEqual(resumed.output, "adjusted")

	def test_a_lone_approve_still_executes(self):
		recorder = _Recorder()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1")), _final("done")])
		agent = Agent(model=model, tools=recorder.tools)
		paused = agent.run("pay alice")

		resumed = agent.resume(paused.messages, {"c1": "Approve"})

		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])
		self.assertEqual(_tool_results(resumed.messages)["c1"], "sent 500 to alice")
		self.assertEqual(resumed.output, "done")

	def test_a_lone_deny_halts_and_its_record_is_byte_identical(self):
		recorder = _Recorder()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1"))])
		agent = Agent(model=model, tools=recorder.tools)
		paused = agent.run("pay alice")

		resumed = agent.resume(paused.messages, {"c1": "Deny"})

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), DENIED)
		self.assertIsNone(resumed.output)
		self.assertEqual(len(model.calls), 1)

	def test_a_lone_free_text_answer_still_redirects_and_the_run_continues(self):
		recorder = _Recorder()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1")), _final("ok")])
		agent = Agent(model=model, tools=recorder.tools)
		paused = agent.run("pay alice")

		resumed = agent.resume(paused.messages, {"c1": "pay bob instead"})

		self.assertEqual(recorder.ran, [])
		redirect = json.loads(_tool_results(resumed.messages)["c1"])
		self.assertEqual(redirect["status"], "redirect")
		self.assertEqual(redirect["user_feedback"], "pay bob instead")
		self.assertEqual(resumed.output, "ok")

	def test_a_pending_call_on_an_ungated_tool_resolves_as_today_even_in_a_denied_batch(self):
		"""`_prepare_resume`'s else-branch: a pending call whose tool does not require
		confirmation records the answer and executes nothing, with or without a Deny beside it.
		Reachable by resuming with an agent whose copy of the tool is ungated."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_two(recorder)

		ran: list[str] = []

		@tool
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			ran.append(to)
			return "sent"

		resuming = Agent(
			model=FakeModel([]),
			tools=[send_money, recorder.delete_records],
		)
		resumed = resuming.resume(paused.messages, {"k1": "Approve", "k2": "Deny"})

		self.assertEqual(ran, [])
		self.assertEqual(recorder.ran, [])
		self.assertEqual(_tool_results(resumed.messages)["k1"], "Approve")


class TestTheLoadBearingFunctionsAreUntouched(UnitTestCase):
	"""CLAUDE.md rule 4. These four decide what executes and on which answer; S14 reads
	`_has_denial` and changes none of them.

	The expected digests were taken once, from the unmodified engine, and are literals here on
	purpose. An earlier version resolved the baseline by shelling out to git, which meant the pin
	quietly skipped itself anywhere the comparison branch was not a local ref — including this
	project's own CI, which checks out a single ref. A gate whose failure mode has never been
	observed is a comment, so this one carries its own baseline and cannot opt out.

	If one of these fails, nothing is wrong with the test: a function that must not change has
	changed, and it needs a spec that names it before it goes any further.
	"""

	BASELINE_DIGESTS: ClassVar[dict[str, str]] = {
		# Re-baselined once, for S19 (brain/10-specs/s19-batch-is-one-decision.md, D2/D6), under
		# the owner's exception for that spec: `_invoke` now reads the same disposition the loops
		# classify a batch with, so the engine holds ONE copy of its most important condition
		# instead of three. The previous value was
		# 745260a7da1fe7e9221cf6257de98eeb7c7e23edf5eb4e1ce17d4d0505f5fa4f. The other three are
		# byte-unchanged in the same commit, and `test_s19_batch_is_one_decision.py` quotes them
		# independently so a second re-baseline cannot pass unnoticed here.
		"_invoke": "2c89005367c8e8bc8ce944ddc2b4fe7f164c84a50802964024f63981e3633246",
		"_resolve_confirmation": "adbb8b26e0b0fb166a5a9fff1c658c531d081b3bd2f2967e55b8e838b5ab8f47",
		# Re-baselined a second time, for S26 (run 17, 29 Sep 2026), under the owner's exception
		# for that spec: the brief names this function's fallback body. ONE LINE changed —
		# `json.dumps(call.arguments, indent=2, default=str)` became `_readable_arguments(...)`,
		# because `json.dumps` defaults to `ensure_ascii=True` and every non-English letter on the
		# commonest approval card of all was arriving as a backslash-u sequence. What executes and
		# on which answer is decided elsewhere and this change cannot reach it; the wording is all
		# that moved, and `flow/tests/test_s26_the_card_speaks_every_language.py` pins the new
		# wording from both sides — the four scripts, and the right-to-left override, line
		# separator and hidden joiner that `ensure_ascii` had been catching by accident.
		# The previous value was
		# 32916612298d4ebdb423d9904e268992a2e638b56a67f2ca14fa67deba9cf34c. The other three are
		# byte-unchanged in the same commit, and `test_s19_batch_is_one_decision.py` quotes them
		# independently so a re-baseline of any of THEM cannot pass unnoticed here.
		"_confirmation_question": "9ee6e922cf59846f322e2c284af895bdf716ba352b78e7b7599a7a58ba8e305e",
		"_has_denial": "80f799b6827afea159589dcee7889282ad8c376aacc15be424c273cd0e55b209",
	}

	def _digests(self, text: str) -> dict[str, str]:
		tree = ast.parse(text)
		return {
			node.name: hashlib.sha256(ast.get_source_segment(text, node).encode()).hexdigest()
			for node in ast.walk(tree)
			if isinstance(node, ast.FunctionDef) and node.name in self.BASELINE_DIGESTS
		}

	def _engine_source(self) -> str:
		return Path(agent_module.__file__).read_text()

	def test_the_four_functions_are_byte_identical_to_their_reviewed_form(self):
		found = self._digests(self._engine_source())

		# If a name went missing, a dict comparison of what is left would still pass.
		self.assertEqual(sorted(found), sorted(self.BASELINE_DIGESTS))
		for name, digest in self.BASELINE_DIGESTS.items():
			self.assertEqual(found[name], digest, f"{name} changed; rule 4 requires a spec that names it")

	def test_the_comparison_can_fail(self):
		"""The positive control. The same comparison over a deliberately altered copy must
		report a difference — otherwise the test above proves nothing."""
		altered = self._engine_source().replace('if answer == "Approve":', 'if answer == "approve":', 1)

		digests = self._digests(altered)

		self.assertNotEqual(digests["_resolve_confirmation"], self.BASELINE_DIGESTS["_resolve_confirmation"])
		self.assertEqual(digests["_has_denial"], self.BASELINE_DIGESTS["_has_denial"])

	def test_the_digests_describe_the_engine_that_is_actually_imported(self):
		"""The second control: the file being hashed is the module the tests ran against, not
		some other copy on the path."""
		self.assertTrue(Path(agent_module.__file__).is_file())
		self.assertIn("def _resolve_confirmation", self._engine_source())


class TestItHoldsThroughTheWholeStack(IntegrationTestCase):
	"""The tests above drive `Agent.resume` directly. This one goes through the public path a
	client actually uses — the whitelisted resume endpoint, a record-backed session, and the
	stored transcript — so a future change to how answers or messages are reshaped on the way in
	cannot quietly undo the withholding."""

	def setUp(self):
		self.model_doc = frappe.get_doc(
			{
				"doctype": "Flow Model",
				"title": "Deny Batch Model",
				"model_id": "openai/gpt-4o-mini",
				"enabled": 1,
			}
		).insert()
		self.agent_doc = frappe.get_doc(
			{
				"doctype": "Flow Agent",
				"title": "Deny Batch Agent",
				"model": self.model_doc.name,
				"instructions": "be terse",
				"enabled": 1,
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_deny_in_the_batch_executes_nothing_through_the_public_resume(self):
		from flow.api.api import resume_run
		from flow.lib.session import load_session

		recorder = _Recorder()
		session = load_session(
			frappe.get_doc({"doctype": "Flow Session", "agent": self.agent_doc.name})
			.insert(ignore_permissions=True)
			.name
		)
		session._runtime.tools.extend(recorder.tools)
		for t in recorder.tools:
			session._runtime._tools_by_name[t.name] = t

		def pause(messages, tools=None, **_):
			return _calls(
				("send_money", {"to": "alice", "amount": 500}, "k1"),
				("delete_records", {"folder": "invoices"}, "k2"),
			)

		with patch.object(Model, "chat", side_effect=pause):
			run = session.chat("pay alice and clear the invoices")
		self.assertEqual(run.status, "Paused")
		self.assertEqual(recorder.ran, [])

		# The client answers both questions in one resume, through the whitelisted endpoint —
		# which reloads the session from the record rather than reusing the object above.
		load_session(run.session)._runtime.tools.extend(recorder.tools)
		with patch(
			"flow.lib.session.load_session",
			side_effect=lambda name, **kw: _with_tools(load_session(name, **kw), recorder),
		):
			resume_run(run.name, {"k1": "Approve", "k2": "Deny"})

		self.assertEqual(recorder.ran, [])
		rows = frappe.get_doc("Flow Session", run.session).messages
		results = {r.tool_call_id: r.content for r in rows if r.role == "tool"}
		self.assertEqual(json.loads(results["k1"]), WITHHELD)
		self.assertEqual(json.loads(results["k2"]), DENIED)


def _with_tools(session, recorder: _Recorder):
	"""Attach the test's tools to a freshly rebuilt runtime. A record-backed agent resolves its
	tools from Flow Tool rows; these are code tools, so they are put back by hand."""
	for t in recorder.tools:
		if t.name not in session._runtime._tools_by_name:
			session._runtime.tools.append(t)
			session._runtime._tools_by_name[t.name] = t
	return session
