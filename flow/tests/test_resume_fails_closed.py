# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S15 — an approval must never be silently swallowed.

A person is shown an approval question and answers it. By the time the run resumes, the tool the
question was about may not be in the runtime any more — removed, renamed or disabled while the run
was paused — or it may no longer be gated at all. Before this change, both of those fell into the
branch written for an ordinary answered question and the person's own answer string was recorded
as that tool call's result. Nothing ran, nothing was denied, and the model was handed the word
"Approve" as though a tool had returned it.

Every tool here records its own calls, so "nothing executed" is asserted against a list rather than
inferred from the result shape, and every assertion about what the model was told reads the
transcript rather than the result object.
"""

import ast
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from flow.lib import agent as agent_module
from flow.lib.agent import Agent, Done, Question, ToolEnded
from flow.lib.model import ChatResponse, Model, ToolCall
from flow.lib.tool import tool

UNAVAILABLE = {
	"status": "not_executed",
	"reason": "unavailable",
	"message": (
		"This action was not carried out and nothing was done. It is no longer available. "
		"Do not report it as done. Tell the user it did not happen."
	),
}
APPROVAL_NO_LONGER_APPLIES = {
	"status": "not_executed",
	"reason": "approval_no_longer_applies",
	"message": (
		"This action was not carried out and nothing was done. What it requires changed while the "
		"question was open, so the answer that was given no longer applies to it. "
		"Do not report it as done. Ask again before doing it."
	),
}
DENIED = {"status": "denied", "message": "User denied this tool call."}
WITHHELD_USER_ANSWER = "Approve"


class FakeModel:
	"""Returns scripted responses and remembers every call, so a test can assert the model was
	not consulted again."""

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


def _tool_results(messages: list[dict[str, Any]]) -> dict[str, str]:
	"""tool_call_id → content, for every tool result in the transcript."""
	return {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}


class _Recorder:
	"""Confirmation-gated tools that record what actually ran."""

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

		self.send_money = send_money
		self.delete_records = delete_records
		self.tools = [send_money, delete_records]


def _ungated_twin(recorder: _Recorder) -> Any:
	"""The same tool by the same name, but no longer gated — an administrator turning the
	confirmation off while a run is paused produces exactly this."""

	@tool
	def send_money(to: str, amount: int) -> str:
		"""Send money to someone."""
		recorder.ran.append(("send_money", {"to": to, "amount": amount}))
		return f"sent {amount} to {to}"

	return send_money


def _pause_on_one(recorder: _Recorder):
	"""Run to a pause holding one approval question, c1 on send_money."""
	model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1"))])
	agent = Agent(model=model, tools=recorder.tools)
	return agent, model, agent.run("pay alice")


def _pause_on_two(recorder: _Recorder):
	"""Run to a pause holding two approval questions: k1 send_money, k2 delete_records."""
	model = FakeModel(
		[
			_calls(
				("send_money", {"to": "alice", "amount": 500}, "k1"),
				("delete_records", {"folder": "invoices"}, "k2"),
			)
		]
	)
	agent = Agent(model=model, tools=recorder.tools)
	return agent, model, agent.run("pay alice and clear the invoices")


class TestAMissingToolFailsClosed(UnitTestCase):
	"""Row 1 of the resume branch: the runtime cannot find the tool the question was about."""

	def test_the_pause_really_does_carry_an_approval_question_and_nothing_has_run(self):
		"""Precondition. If this fails, every other test in this class measures nothing."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		self.assertTrue(paused.paused)
		self.assertEqual([q.key for q in paused.questions], ["c1"])
		self.assertEqual(paused.questions[0].options, ["Approve", "Deny"])
		self.assertEqual(recorder.ran, [])

	def test_approve_on_a_tool_missing_from_the_runtime_executes_nothing(self):
		"""Note what this does and does not prove. "Nothing ran" was already true before this
		change — a runtime with no such tool could not run it either way. The defect was never
		an execution; it was the answer being written in as the tool's result. So this asserts
		BOTH halves: it is the forward guard against a future row that executes, and the result
		assertion is the half that was actually broken."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		# The resuming runtime was rebuilt without send_money — the production shape, where a
		# resume loads the session's agent afresh from its records.
		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), UNAVAILABLE)

	def test_the_missing_tools_result_is_the_fixed_record_and_never_the_answer(self):
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		result = _tool_results(resumed.messages)["c1"]
		self.assertEqual(json.loads(result), UNAVAILABLE)
		self.assertNotEqual(result, "Approve")

	def test_a_denial_on_a_missing_tool_is_the_same_fixed_record(self):
		"""A Deny halts the run either way; what matters is that the call itself is recorded as
		not executed rather than as a tool that returned the word "Deny"."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": "Deny"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), UNAVAILABLE)

	def test_free_text_on_a_missing_tool_is_the_same_fixed_record(self):
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": "send 400 instead"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), UNAVAILABLE)

	def test_no_part_of_the_persons_answer_reaches_the_model(self):
		"""The answer is caller-supplied text. None of it may appear in what is written as the
		tool's own output."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)
		secret = "zzqmarkerzz-the-persons-own-words"

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": secret}, asked=paused.questions)

		self.assertNotIn(secret, _tool_results(resumed.messages)["c1"])
		self.assertNotIn(secret, json.dumps(resumed.messages))

	def test_the_fixed_record_names_no_platform_vendor_or_model(self):
		"""CLAUDE.md rule 3. Both records are read by the model.

		It reads the ENGINE's strings, not this module's copies of them: a test that scanned its
		own literals would stay green while the production message named a platform, which is the
		one thing it exists to stop.
		"""
		messages = agent_module.NOT_EXECUTED_MESSAGES
		self.assertEqual(
			sorted(messages),
			["approval_no_longer_applies", "group_refused", "unattended", "unavailable"],
		)
		for reason, message in messages.items():
			text = message.lower()
			for word in ("frappe", "flow", "erpnext", "mariadb", "openai", "anthropic", "gpt", "claude"):
				self.assertNotIn(word, text, f"{word!r} must not be in {reason}")

	def test_this_modules_copies_match_the_engines(self):
		"""The control for every equality assertion in this file: if the two drifted apart, the
		tests would be pinning a string the engine does not produce."""
		self.assertEqual(UNAVAILABLE["message"], agent_module.NOT_EXECUTED_MESSAGES["unavailable"])
		self.assertEqual(
			APPROVAL_NO_LONGER_APPLIES["message"],
			agent_module.NOT_EXECUTED_MESSAGES["approval_no_longer_applies"],
		)

	def test_it_holds_without_any_record_of_what_was_asked(self):
		"""A caller that passes no asked-questions record — an in-process caller, or a run that
		paused before this change — still fails closed on a missing tool. The missing-tool row
		does not need to know what was asked."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"})

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), UNAVAILABLE)

	def test_the_streaming_resume_fails_closed_identically(self):
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		events = list(
			resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions, stream=True)
		)

		self.assertEqual(recorder.ran, [])
		ended = [e for e in events if isinstance(e, ToolEnded)]
		self.assertEqual(json.loads(ended[0].result), UNAVAILABLE)
		done = [e for e in events if isinstance(e, Done)][-1]
		self.assertEqual(json.loads(_tool_results(done.result.messages)["c1"]), UNAVAILABLE)


class TestAGateTurnedOffWhilePausedFailsClosed(UnitTestCase):
	"""Row 3: the tool is still there, but it no longer requires confirmation. The person
	answered a question whose basis has changed, so the answer cannot be acted on."""

	def test_the_old_approval_does_not_execute_the_now_ungated_tool(self):
		"""As above: not executing was already true here. The result assertion is the half that
		this change is responsible for, so both are asserted together."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[_ungated_twin(recorder)])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), APPROVAL_NO_LONGER_APPLIES)

	def test_its_result_is_the_approval_no_longer_applies_record(self):
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[_ungated_twin(recorder)])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		result = _tool_results(resumed.messages)["c1"]
		self.assertEqual(json.loads(result), APPROVAL_NO_LONGER_APPLIES)
		self.assertNotEqual(result, "Approve")

	def test_the_asked_record_may_arrive_as_stored_rows_rather_than_objects(self):
		"""What the public path has is the run's stored JSON, not the Question objects."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)
		stored = [{"key": q.key, "prompt": q.prompt, "options": q.options} for q in paused.questions]

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[_ungated_twin(recorder)])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=stored)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), APPROVAL_NO_LONGER_APPLIES)


class TestAGateTurnedOnWhilePausedDoesNotExecute(UnitTestCase):
	"""The mirror of the class above, and the direction that EXECUTES if it is not caught.

	A tool asks its own question — not an approval question; nobody was shown "Approve this?" by
	the engine. While the run is paused the tool is given `requires_confirmation`. At resume it
	is present and gated, so on the way in it looks exactly like a call the person approved, and
	an answer that happens to read "Approve" runs it. The person answered a tool's question and
	a write went through on it.

	Found by two reviewers independently during this spec's verify pass; it is the same defect
	class as the rest of this module, pointing the other way.
	"""

	def _pause_on_a_tool_authored_question(self, ran: list[str]):
		@tool
		def review_draft(draft: str) -> Question:
			"""Ask what to do with a draft."""
			return Question(prompt="What should happen to this draft?", options=["Publish", "Hold"])

		@tool(requires_confirmation=True)
		def review_draft_gated(draft: str) -> str:
			"""The same tool, after someone ticked the confirmation box."""
			ran.append(draft)
			return "published"

		review_draft_gated.name = "review_draft"
		model = FakeModel([_calls(("review_draft", {"draft": "d1"}, "c1")), _final("done")])
		agent = Agent(model=model, tools=[review_draft])
		return agent.run("what about the draft?"), review_draft_gated

	def test_the_now_gated_tool_does_not_execute_on_an_answer_to_a_tools_own_question(self):
		ran: list[str] = []
		paused, gated = self._pause_on_a_tool_authored_question(ran)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[gated])
		resumed = resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), APPROVAL_NO_LONGER_APPLIES)

	def test_a_tool_question_shaped_exactly_like_an_approval_is_not_told_apart(self):
		"""The limitation, pinned rather than left unsaid. A question is recognised as an
		approval by its options, so a tool that returns one offering exactly "Approve"/"Deny" is
		indistinguishable from the engine's own, and a gate turned on underneath it still
		executes. Telling these apart needs an explicit marker on the stored question, which
		means changing what builds it — a rule-4 function, so it needs a spec that names it.
		Nothing in this repository writes such a tool today. If one is ever written, this test
		goes red and says what it costs."""
		ran: list[str] = []

		@tool
		def review_draft(draft: str) -> Question:
			"""Ask what to do with a draft."""
			return Question(prompt="Approve this draft?", options=["Approve", "Deny"])

		@tool(requires_confirmation=True)
		def review_draft_gated(draft: str) -> str:
			"""The same tool, after someone ticked the confirmation box."""
			ran.append(draft)
			return "published"

		review_draft_gated.name = "review_draft"
		model = FakeModel([_calls(("review_draft", {"draft": "d1"}, "c1")), _final("done")])
		paused = Agent(model=model, tools=[review_draft]).run("what about the draft?")

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[review_draft_gated])
		resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(ran, ["d1"], "known limitation: see this test's docstring")

	def test_with_no_record_of_the_pause_it_is_todays_behaviour(self):
		"""AC 11 in the direction that matters most: with nothing to read, the tool's own gate
		stands in for what was asked, the two cannot disagree, and this row cannot fire."""
		ran: list[str] = []
		paused, gated = self._pause_on_a_tool_authored_question(ran)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[gated])
		resuming.resume(paused.messages, {"c1": "Approve"})

		self.assertEqual(ran, ["d1"])


class TestOrdinaryQuestionsAreUnchanged(UnitTestCase):
	"""Row 4, the branch the `else` was written for: the tool asked the question itself, it is
	still present, and it is not gated. The answer is its result, exactly as today."""

	def _pause_on_a_tool_authored_question(self, ran: list[str]):
		@tool
		def pick_table(hint: str) -> Question:
			"""Ask which table to read."""
			ran.append(hint)
			return Question(prompt="Which table?", options=["Customers", "Invoices"])

		model = FakeModel([_calls(("pick_table", {"hint": "sales"}, "c1")), _final("read it")])
		agent = Agent(model=model, tools=[pick_table])
		return agent, agent.run("which table?")

	def test_the_answer_is_still_recorded_as_the_tools_result(self):
		ran: list[str] = []
		agent, paused = self._pause_on_a_tool_authored_question(ran)

		resumed = agent.resume(paused.messages, {"c1": "Customers"}, asked=paused.questions)

		self.assertEqual(_tool_results(resumed.messages)["c1"], "Customers")
		self.assertEqual(resumed.output, "read it")
		# The tool DID run before it asked. That is exactly why echoing its answer is right here
		# and wrong in rows 1 and 3, where nothing ran at all.
		self.assertEqual(ran, ["sales"])

	def test_it_is_unchanged_with_no_asked_record_either(self):
		ran: list[str] = []
		agent, paused = self._pause_on_a_tool_authored_question(ran)

		resumed = agent.resume(paused.messages, {"c1": "Customers"})

		self.assertEqual(_tool_results(resumed.messages)["c1"], "Customers")


class TestTheGatedPathIsByteIdentical(UnitTestCase):
	"""Row 2 is today's path and must not move: S15 adds rows around it, not inside it."""

	def test_a_lone_approve_still_executes(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_one(recorder)
		agent.model = FakeModel([_final("paid")])

		resumed = agent.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])
		self.assertEqual(_tool_results(resumed.messages)["c1"], "sent 500 to alice")
		self.assertEqual(resumed.output, "paid")

	def test_a_lone_deny_records_todays_denial_and_halts(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_one(recorder)

		resumed = agent.resume(paused.messages, {"c1": "Deny"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["c1"]), DENIED)
		self.assertIsNone(resumed.output)
		self.assertEqual(resumed.iterations, 0)

	def test_a_lone_free_text_still_redirects(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_one(recorder)
		agent.model = FakeModel([_final("adjusted")])

		resumed = agent.resume(paused.messages, {"c1": "make it 400"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		record = json.loads(_tool_results(resumed.messages)["c1"])
		self.assertEqual(record["status"], "redirect")
		self.assertEqual(record["user_feedback"], "make it 400")

	def test_s14_still_withholds_every_approve_beside_a_denial(self):
		recorder = _Recorder()
		agent, _model, paused = _pause_on_two(recorder)

		resumed = agent.resume(paused.messages, {"k1": "Approve", "k2": "Deny"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		withheld = json.loads(_tool_results(resumed.messages)["k1"])
		self.assertEqual(withheld["status"], "not_executed")
		self.assertEqual(withheld["user_answer"], WITHHELD_USER_ANSWER)
		self.assertEqual(json.loads(_tool_results(resumed.messages)["k2"]), DENIED)

	def test_a_group_mixing_a_missing_tool_with_a_gated_one_executes_nothing(self):
		"""The two rules meet: one call's tool is gone, the other is present and gated. Neither
		may run, and each is recorded for what it is."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_two(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"k1": "Approve", "k2": "Deny"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["k1"]), UNAVAILABLE)
		self.assertEqual(json.loads(_tool_results(resumed.messages)["k2"]), DENIED)

	def test_a_missing_tool_does_not_make_the_rest_of_the_group_execute(self):
		"""The mirror of the test above: a missing tool beside an approved, present, gated one
		must not disturb the approved one, which still runs."""
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_two(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[recorder.delete_records])
		resumed = resuming.resume(paused.messages, {"k1": "Approve", "k2": "Approve"}, asked=paused.questions)

		self.assertEqual(recorder.ran, [("delete_records", {"folder": "invoices"})])
		self.assertEqual(json.loads(_tool_results(resumed.messages)["k1"]), UNAVAILABLE)
		self.assertEqual(_tool_results(resumed.messages)["k2"], "deleted invoices")


class TestTheStreamingPathReadsTheRecordToo(UnitTestCase):
	"""The only streaming test in this module was a missing-tool case, and row 1 never reads the
	record — so dropping `asked` from the streaming call site would have left the suite green
	while every streaming client lost row 3. This is the test that notices."""

	def test_the_streamed_resume_withholds_a_stale_approval(self):
		recorder = _Recorder()
		_agent, _model, paused = _pause_on_one(recorder)

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[_ungated_twin(recorder)])
		events = list(
			resuming.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions, stream=True)
		)

		self.assertEqual(recorder.ran, [])
		ended = [e for e in events if isinstance(e, ToolEnded)]
		self.assertEqual([(e.id, e.name) for e in ended], [("c1", "send_money")])
		self.assertEqual(json.loads(ended[0].result), APPROVAL_NO_LONGER_APPLIES)

	def test_a_gated_tool_still_executes_with_no_record_at_all(self):
		"""AC 11's missing third: row 2 never reads the record, and this is what says so."""
		recorder = _Recorder()
		agent, _model, paused = _pause_on_one(recorder)
		agent.model = FakeModel([_final("paid")])

		agent.resume(paused.messages, {"c1": "Approve"})

		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])


class TestTheLoadBearingFunctionsStillHaveNotMoved(UnitTestCase):
	"""CLAUDE.md rule 4, re-asserted from this spec's own module.

	The baseline digests live in one place — S14's pin — so the two modules cannot drift apart.
	S15 adds branches *around* `_resolve_confirmation` and reads the options
	`_confirmation_question` already produces; it changes none of the four.
	"""

	def _baseline(self) -> dict[str, str]:
		from flow.tests.test_deny_stops_batch import TestTheLoadBearingFunctionsAreUntouched

		return dict(TestTheLoadBearingFunctionsAreUntouched.BASELINE_DIGESTS)

	def test_the_four_functions_are_byte_identical_to_their_reviewed_form(self):
		baseline = self._baseline()
		text = Path(agent_module.__file__).read_text()
		found = {
			node.name: hashlib.sha256(ast.get_source_segment(text, node).encode()).hexdigest()
			for node in ast.walk(ast.parse(text))
			if isinstance(node, ast.FunctionDef) and node.name in baseline
		}

		self.assertEqual(sorted(found), sorted(baseline))
		for name, digest in baseline.items():
			self.assertEqual(found[name], digest, f"{name} changed; rule 4 requires a spec that names it")

	def test_the_baseline_is_not_empty(self):
		"""The positive control for the test above: an empty baseline would make it vacuous."""
		self.assertEqual(len(self._baseline()), 4)


class TestItHoldsThroughTheWholeStack(IntegrationTestCase):
	"""The public path a client actually uses. The session pauses with the tool in place, and the
	resume rebuilds the runtime from the record — where the tool no longer is. That is the whole
	defect, reached without touching the engine's internals."""

	def setUp(self):
		self.model_doc = frappe.get_doc(
			{
				"doctype": "Flow Model",
				"title": "Fails Closed Model",
				"model_id": "openai/gpt-4o-mini",
				"enabled": 1,
			}
		).insert()
		self.agent_doc = frappe.get_doc(
			{
				"doctype": "Flow Agent",
				"title": "Fails Closed Agent",
				"model": self.model_doc.name,
				"instructions": "be terse",
				"enabled": 1,
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_session_that_loses_the_tool_between_pause_and_resume_executes_nothing(self):
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
			return _calls(("send_money", {"to": "alice", "amount": 500}, "c1"))

		with patch.object(Model, "chat", side_effect=pause):
			run = session.chat("pay alice")
		self.assertEqual(run.status, "Paused")
		self.assertEqual(recorder.ran, [])

		# No tools are put back this time: the resume rebuilds the agent from its records, and
		# send_money is a code tool that is not among them. This is the production shape of a
		# tool removed, renamed or disabled while the run was paused.
		with patch.object(Model, "chat", side_effect=lambda *a, **k: _final("all done")):
			resume_run(run.name, {"c1": "Approve"})

		self.assertEqual(recorder.ran, [])
		rows = frappe.get_doc("Flow Session", run.session).messages
		results = {r.tool_call_id: r.content for r in rows if r.role == "tool"}
		self.assertEqual(json.loads(results["c1"]), UNAVAILABLE)
		self.assertNotEqual(results["c1"], "Approve")

	def test_a_gate_turned_off_while_paused_holds_through_the_public_resume(self):
		"""The tool is still there at resume — it is simply no longer gated. Telling that apart
		from a question a tool asked itself needs the record of what was asked, which only the
		session layer has. If it stops passing that down, this test is what notices."""
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
			return _calls(("send_money", {"to": "alice", "amount": 500}, "c1"))

		with patch.object(Model, "chat", side_effect=pause):
			run = session.chat("pay alice")
		self.assertEqual(run.status, "Paused")

		# The rebuilt runtime gets the same tool by the same name, with the gate turned off —
		# an administrator unticking it while the question was open.
		ungated = _ungated_twin(recorder)

		def rebuilt(name, **kw):
			reloaded = load_session(name, **kw)
			reloaded._runtime.tools.append(ungated)
			reloaded._runtime._tools_by_name[ungated.name] = ungated
			return reloaded

		with (
			patch("flow.lib.session.load_session", side_effect=rebuilt),
			patch.object(Model, "chat", side_effect=lambda *a, **k: _final("all done")),
		):
			resume_run(run.name, {"c1": "Approve"})

		self.assertEqual(recorder.ran, [])
		rows = frappe.get_doc("Flow Session", run.session).messages
		results = {r.tool_call_id: r.content for r in rows if r.role == "tool"}
		self.assertEqual(json.loads(results["c1"]), APPROVAL_NO_LONGER_APPLIES)
