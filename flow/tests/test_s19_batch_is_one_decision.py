# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S19 Part A — a batch is one decision.

The model can ask for several tools in one reply. Before this change the engine ran them one by
one and only decided to pause after the last of them, so every ungated call in a pausing turn had
already executed by the time the person saw the question. They were asked about the write having
already had the read done in their name — and a Deny undid nothing and said nothing.

Now nothing in a turn runs if anything in that turn will ask a person: the calls nobody was asked
about are held back and execute on resume, in their original order, after the answers are in.

Every tool here records its own calls, so "nothing ran" is asserted against a list rather than
inferred from the shape of a result.
"""

import json
from typing import Any

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from flow.lib.agent import (
	_UNRESOLVABLE_PAUSE,
	CONFIRM_ANSWER_OPTIONS,
	Agent,
	Done,
	Question,
	ToolEnded,
	ToolStarted,
)
from flow.lib.model import ChatResponse, ToolCall, ToolCallBegin
from flow.lib.tool import tool


class FakeModel:
	"""Scripted responses, and a record of every call, so a test can assert the model was not
	consulted again."""

	def __init__(self, responses: list[ChatResponse]):
		self._responses = list(responses)
		self.calls: list[dict[str, Any]] = []
		# Overridable so a test can script the ORDER of a stream, not only its contents.
		self._stream = None

	def chat(self, messages, tools=None, *, stream=False):
		self.calls.append({"messages": list(messages), "tools": tools, "stream": stream})
		if not self._responses:
			raise AssertionError("FakeModel ran out of scripted responses")
		response = self._responses.pop(0)
		if stream:
			return (self._stream or _scripted_stream)(response)
		return response


def _scripted_stream(response: ChatResponse):
	"""A scripted stream that carries the mid-stream tool announcements the real one carries.

	`flow/lib/model.py:_consume_stream` yields one `ToolCallBegin` per tool call, for EVERY call
	in the reply, the moment its id and name are known. Without them this helper produced no
	`ToolStarted` events at all, so AT8's "no card was opened" assertion was over an empty list
	and could not fail — the exact shape CLAUDE.md names: a gate whose failure mode has never
	been observed is a comment.
	"""
	if response.content:
		yield response.content
	for call in response.tool_calls or []:
		yield ToolCallBegin(id=call.id, name=call.name)
	return response


def _final(text: str) -> ChatResponse:
	return ChatResponse(content=text, finish_reason="stop", usage={})


def _calls(*specs: tuple[str, dict[str, Any], str]) -> ChatResponse:
	"""ONE assistant turn asking for several tools at once: (name, arguments, call_id).

	Deliberately not two scripted single-call responses — those are two turns, and two turns is
	the shape this defect does not live in.
	"""
	return ChatResponse(
		content=None,
		tool_calls=[ToolCall(id=call_id, name=name, arguments=args) for name, args, call_id in specs],
		finish_reason="tool_calls",
		usage={},
	)


def _assistant_turn(specs: list[tuple[str, dict[str, Any], str]]) -> dict[str, Any]:
	"""One stored assistant turn, in the shape a transcript holds it.

	Hand-built rather than produced by a run, because the shapes below are what a STORED transcript
	can hold after a run was stopped or failed, and no scripted run reaches some of them.
	"""
	return {
		"role": "assistant",
		"content": None,
		"tool_calls": [
			{
				"id": call_id,
				"type": "function",
				"function": {"name": name, "arguments": json.dumps(args)},
			}
			for name, args, call_id in specs
		],
	}


def _tool_results(messages: list[dict[str, Any]]) -> dict[str, str]:
	return {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}


class _Books:
	"""An ungated read and a gated write, each recording what actually ran."""

	def __init__(self):
		self.read: list[dict[str, Any]] = []
		self.wrote: list[dict[str, Any]] = []
		books = self

		@tool
		def read_balance(account: str) -> str:
			"""Read an account balance."""
			books.read.append({"account": account})
			return "120"

		@tool(requires_confirmation=True)
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			books.wrote.append({"to": to, "amount": amount})
			return f"sent {amount} to {to}"

		self.read_balance = read_balance
		self.send_money = send_money
		self.tools = [read_balance, send_money]


def _pause_on_a_mixed_batch(books: _Books, extra: list[ChatResponse] | None = None, *, read_first=True):
	"""Run one batch holding an ungated read (r1) and a gated write (c2), to the pause."""
	specs = [
		("read_balance", {"account": "alice"}, "r1"),
		("send_money", {"to": "alice", "amount": 500}, "c2"),
	]
	if not read_first:
		specs.reverse()
	model = FakeModel([_calls(*specs), *(extra or [])])
	agent = Agent(model=model, tools=books.tools)
	return agent, model, agent.run("read alice's balance and pay her")


class TestABatchIsOneDecision(UnitTestCase):
	def test_an_ungated_call_beside_a_gated_one_does_not_run(self):
		"""AT1. The defect itself: the read used to have run by the time the question was shown."""
		books = _Books()
		_agent, _model, paused = _pause_on_a_mixed_batch(books)

		self.assertTrue(paused.paused)
		self.assertEqual(len(paused.questions), 1)
		self.assertEqual(paused.questions[0].key, "c2")
		self.assertEqual(paused.tool_calls, [])
		self.assertEqual(books.read, [], "the read ran before anyone was asked about the write")
		self.assertEqual(books.wrote, [])
		self.assertEqual(_tool_results(paused.messages), {})

	def test_the_gated_call_first_makes_no_difference(self):
		"""AT2. The whole batch is classified before any of it runs, so the order the model
		happened to choose decides nothing."""
		books = _Books()
		_agent, _model, paused = _pause_on_a_mixed_batch(books, read_first=False)

		self.assertTrue(paused.paused)
		self.assertEqual(len(paused.questions), 1)
		self.assertEqual(paused.tool_calls, [])
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])

	def test_the_deferred_call_runs_on_resume_before_the_approved_one(self):
		"""AT3. Held back, not dropped — and in the order the model asked for them."""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])
		# Held back, not merely late: without this the test passes against the engine that ran the
		# read before anyone was asked, because by resume time the recorder looks the same.
		self.assertEqual(books.read, [], "the read ran in the pausing turn")

		# `asked` is what the production resume always passes (flow_session.py:384,393). It is
		# what tells a call HELD BACK from a call whose own question went unanswered — see AT7d —
		# so a test about a held-back call has to resume the way the engine's own caller does.
		resumed = agent.resume(paused.messages, {"c2": "Approve"}, asked=paused.questions)

		self.assertEqual(books.read, [{"account": "alice"}])
		self.assertEqual(books.wrote, [{"to": "alice", "amount": 500}])
		self.assertEqual([c.name for c in resumed.tool_calls], ["read_balance", "send_money"])
		self.assertEqual(_tool_results(resumed.messages)["r1"], "120")
		self.assertEqual(resumed.output, "done")

	def test_a_denial_holds_back_the_deferred_call_too(self):
		"""AT4. Refusing one action shown in a group refuses the group, and a deferred read is
		part of that group precisely because it was held back for the group's sake."""
		books = _Books()
		agent, model, paused = _pause_on_a_mixed_batch(books)

		resumed = agent.resume(paused.messages, {"c2": "Deny"}, asked=paused.questions)

		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])
		self.assertIsNone(resumed.output)
		self.assertFalse(resumed.paused)
		deferred = json.loads(_tool_results(resumed.messages)["r1"])
		self.assertEqual(deferred["status"], "not_executed")
		self.assertEqual(len(model.calls), 1, "a denied turn must not consult the model again")

	def test_a_tool_that_asks_its_own_question_still_lets_the_others_run(self):
		"""AT5. The fork's own copy of upstream's `test_other_tools_run_while_a_question_pauses`.

		A question a TOOL returns is not an approval: the tool body has already run by the time
		anyone sees it, so holding its neighbours back would protect nothing and would change a
		behaviour upstream pins. The classification pass never sees it.
		"""
		ran: list[str] = []

		@tool
		def safe() -> str:
			"""Safe."""
			ran.append("safe")
			return "safe-result"

		@tool
		def ask_user(prompt: str) -> Question:
			"""Ask the user."""
			return Question(prompt=prompt, options=["A", "B"])

		agent = Agent(
			model=FakeModel([_calls(("safe", {}, "c1"), ("ask_user", {"prompt": "ok?"}, "c2"))]),
			tools=[safe, ask_user],
		)

		result = agent.run("do both")

		self.assertTrue(result.paused)
		self.assertEqual(ran, ["safe"])
		self.assertEqual([c.name for c in result.tool_calls], ["safe"])
		self.assertEqual([q.key for q in result.questions], ["c2"])

	def test_a_turn_with_no_approval_is_unchanged(self):
		"""AT6. The control. Two ungated calls: both run, in order, one model call each side."""
		books = _Books()

		@tool
		def read_limit(account: str) -> str:
			"""Read an account limit."""
			books.read.append({"limit": account})
			return "500"

		model = FakeModel(
			[
				_calls(
					("read_balance", {"account": "alice"}, "r1"),
					("read_limit", {"account": "alice"}, "r2"),
				),
				_final("both read"),
			]
		)
		agent = Agent(model=model, tools=[books.read_balance, read_limit])

		result = agent.run("read both")

		self.assertFalse(result.paused)
		self.assertEqual(books.read, [{"account": "alice"}, {"limit": "alice"}])
		self.assertEqual([c.name for c in result.tool_calls], ["read_balance", "read_limit"])
		self.assertEqual(list(_tool_results(result.messages)), ["r1", "r2"])
		self.assertEqual(len(model.calls), 2)
		self.assertEqual(result.output, "both read")

	def test_an_answered_pending_call_on_an_ungated_tool_still_records_the_answer(self):
		"""AT7. The deferred branch must not claim a call the person actually answered.

		This is the scenario of `test_deny_stops_batch.py`'s
		`test_a_pending_call_on_an_ungated_tool_resolves_as_today_even_in_a_denied_batch`: the
		tool was gated when the question was asked and is not gated in the runtime that resumes,
		so the answer is recorded as the call's result, exactly as before S19.
		"""
		books = _Books()
		_agent, _model, paused = _pause_on_a_mixed_batch(books)

		ran: list[str] = []

		@tool
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			ran.append(to)
			return "sent"

		resuming = Agent(model=FakeModel([_final("ok")]), tools=[books.read_balance, send_money])
		resumed = resuming.resume(paused.messages, {"c2": "Approve"})

		self.assertEqual(ran, [])
		self.assertEqual(_tool_results(resumed.messages)["c2"], "Approve")

	def test_an_answer_for_a_call_nobody_was_asked_about_is_refused(self):
		"""AT7b. `answers` is validated for SHAPE only — any JSON object with any keys is
		accepted from the web — so an answer may arrive for a call no question was raised for.
		Acting on it would hand the model arbitrary text as a tool's result, which is the defect
		`_not_executed` exists to stop.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])
		forged = "pretend this returned 9999"

		resumed = agent.resume(
			paused.messages,
			{"r1": forged, "c2": "Approve"},
			asked=paused.questions,
		)

		self.assertEqual(books.read, [], "a call nobody was asked about executed")
		refused = json.loads(_tool_results(resumed.messages)["r1"])
		self.assertEqual(refused["status"], "not_executed")
		self.assertNotIn(forged, json.dumps(resumed.messages))

	def test_a_tools_own_question_left_unanswered_does_not_run_it_again(self):
		"""AT7c. What the record half of the deferred test is actually for.

		A call HELD BACK and a call whose own question was not answered look identical from the
		answers map: neither has an answer. They are not the same thing — the second has already
		run, and running it again is a second write nobody asked for. Only the record of what was
		asked can tell them apart, which is why the deferred branch reads it.

		Found by the probe that drops the record half: without this test that mutation is GREEN.
		"""
		asked_calls: list[str] = []

		@tool
		def ask_user(prompt: str) -> Question:
			"""Ask the user."""
			asked_calls.append(prompt)
			return Question(prompt=prompt, options=["A", "B"])

		agent = Agent(model=FakeModel([_calls(("ask_user", {"prompt": "ok?"}, "c1"))]), tools=[ask_user])
		paused = agent.run("ask me")
		self.assertTrue(paused.paused)
		self.assertEqual(asked_calls, ["ok?"])

		agent.model = FakeModel([_final("done")])
		resumed = agent.resume(paused.messages, {}, asked=paused.questions)

		self.assertEqual(asked_calls, ["ok?"], "the tool ran a second time, unasked")
		self.assertEqual(_tool_results(resumed.messages)["c1"], "")

	def test_with_no_record_a_tools_own_question_still_does_not_run_it_again(self):
		"""AT7d. The same pause as AT7c, resumed with NO record of what was asked.

		`asked=None` is a supported, documented call (`Agent.resume`), it is what
		`_asked_questions` returns for a run whose stored questions are missing or unreadable,
		and it is what `evals/run.py` passes. The docstring of `_prepare_resume` promises that
		with no record behaviour is exactly what it was before any of this was recorded —
		nothing runs on the strength of an answer nobody gave. The deferred branch broke that
		promise: with no record its guard collapsed to "true for every unanswered call", so the
		tool's body ran a SECOND time.
		"""
		asked_calls: list[str] = []

		@tool
		def ask_user(prompt: str) -> Question:
			"""Ask the user."""
			asked_calls.append(prompt)
			return Question(prompt=prompt, options=["A", "B"])

		agent = Agent(model=FakeModel([_calls(("ask_user", {"prompt": "ok?"}, "c1"))]), tools=[ask_user])
		paused = agent.run("ask me")
		self.assertTrue(paused.paused)
		self.assertEqual(asked_calls, ["ok?"])

		agent.model = FakeModel([_final("done")])
		resumed = agent.resume(paused.messages, {}, asked=None)

		self.assertEqual(asked_calls, ["ok?"], "the tool ran a second time, unasked")
		self.assertEqual(_tool_results(resumed.messages)["c1"], "")

	def test_with_no_record_an_unanswered_call_does_not_run(self):
		"""AT7e. The other half of AT7d: a call nobody answered, in a pause with no record.

		Without a record there is nothing that can say whether this call was held back for the
		group or was a question in its own right, so it must not execute on the strength of an
		answer that does not exist. Before the fix it did — and for a call that was gated when
		the run paused and has since been un-gated, it executed with no answer of any kind.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])
		self.assertTrue(paused.paused)
		self.assertEqual(books.read, [])

		resumed = agent.resume(paused.messages, {}, asked=None)

		self.assertEqual(books.read, [], "a held-back call ran with no answer and no record")
		self.assertEqual(books.wrote, [])
		self.assertEqual(_tool_results(resumed.messages)["r1"], "")

	def test_the_streamed_loop_defers_the_same_calls(self):
		"""AT8. The streaming loop is a second copy of the same decision, and telling a client an
		action is starting when it will not run in this step is its own kind of lie.

		Written against a stream that announces every call mid-stream, the way the real one does.
		The first version of this test scripted a stream that announced nothing, so its "no card
		was opened" assertion held over an empty list while the shipped engine opened a card for
		the held-back call — with no arguments in it — on the very screen where someone was being
		asked to approve its neighbour.
		"""
		books = _Books()
		model = FakeModel(
			[
				_calls(
					("read_balance", {"account": "alice"}, "r1"),
					("send_money", {"to": "alice", "amount": 500}, "c2"),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=books.tools)

		events = list(agent.run("read and pay", stream=True))

		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])
		started = [(e.id, e.arguments) for e in events if isinstance(e, ToolStarted)]
		self.assertEqual(
			[call_id for call_id, _args in started],
			# Twice for the asked call, and that is the contract the client reads: once mid-stream
			# with no arguments yet, once with the full arguments (frontend/src/store.js:393-399).
			# Not once for the held-back one.
			["c2", "c2"],
			"a call was announced as starting when it was being held back",
		)
		self.assertEqual(started[-1][1], {"to": "alice", "amount": 500})
		self.assertEqual(
			[(e.id, e.result) for e in events if isinstance(e, ToolEnded)],
			[("c2", "")],
			"a call the client cannot see was ended for it",
		)
		done = next(e for e in events if isinstance(e, Done))
		self.assertTrue(done.result.paused)
		self.assertEqual(done.result.tool_calls, [])

		# ...and it is announced when it actually runs, carrying what it ran with.
		resumed = list(
			agent.resume(done.result.messages, {"c2": "Approve"}, stream=True, asked=done.result.questions)
		)

		self.assertEqual(books.read, [{"account": "alice"}])
		announced = [e for e in resumed if isinstance(e, ToolStarted) and e.id == "r1"]
		self.assertEqual(len(announced), 1, "the held-back call ran without ever being announced")
		self.assertEqual(
			announced[0].arguments,
			{"account": "alice"},
			"the held-back call was announced with no arguments to show",
		)
		self.assertEqual(announced[0].name, "read_balance")
		self.assertIn(("r1", "120"), [(e.id, e.result) for e in resumed if isinstance(e, ToolEnded)])

	def test_a_denied_group_announces_nothing_for_the_held_back_call(self):
		"""AT8d. The Deny half of AT8, and the one path where `announce` was still wrong.

		A card is opened for an action that is starting. A denial is the one answer that starts
		nothing, so it opens none. `announce` consulted the question record and the turn's position
		and nothing else, so on a resume whose answers hold an exact "Deny" the held-back call was
		announced anyway — with the arguments the model wrote — immediately before its
		`group_refused` result. Nothing ran, so this is an honesty defect rather than an execution
		one: the person declined, and the screen then drew the declined action as though it had
		begun. During the pause nothing at all had been drawn for that call, which is the behaviour
		the engine ships as correct; the Deny path contradicted it. It is also the E5 lesson one
		door over — model-authored values shaping what a person is shown around an approval.

		The `tool_ended` still goes out, and a client with no card for that id drops it, which is
		the correct outcome: nothing shown for a call that never ran, exactly as during the pause.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])

		events = list(agent.resume(paused.messages, {"c2": "Deny"}, asked=paused.questions, stream=True))

		# The control that makes the assertion below mean something: it really did not run.
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])
		self.assertEqual(
			[(e.id, e.arguments) for e in events if isinstance(e, ToolStarted)],
			[],
			"a call the person's denial stopped was announced as starting",
		)
		self.assertEqual(
			[
				(e.id, json.loads(e.result).get("reason") or json.loads(e.result)["status"])
				for e in events
				if isinstance(e, ToolEnded)
			],
			[("r1", "group_refused"), ("c2", "denied")],
		)
		done = next(e for e in events if isinstance(e, Done))
		self.assertEqual(done.result.output, None)

	def test_but_an_approve_still_announces_the_held_back_call_once_with_its_arguments(self):
		"""The control for AT8d. Holding the announcement back on a denial must not hold it back
		on the answer that does start the action — that would trade one silent card for another.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])

		events = list(agent.resume(paused.messages, {"c2": "Approve"}, asked=paused.questions, stream=True))

		self.assertEqual(books.read, [{"account": "alice"}])
		announced = [e for e in events if isinstance(e, ToolStarted) and e.id == "r1"]
		self.assertEqual(len(announced), 1, "the held-back call ran without ever being announced")
		self.assertEqual(announced[0].name, "read_balance")
		self.assertEqual(announced[0].arguments, {"account": "alice"})

	def test_a_reply_with_nothing_to_approve_streams_exactly_as_it_did(self):
		"""AT8b. The control for AT8: attended behaviour is unchanged.

		When no call in the reply needs a person, every call runs in this step, so every
		announcement goes out — same events, same payloads, same order as before. Without this
		test "announce nothing until the reply is complete" would satisfy AT8 by making every
		client wait for everything.
		"""
		books = _Books()
		model = FakeModel(
			[
				_calls(
					("read_balance", {"account": "alice"}, "r1"),
					("read_balance", {"account": "bob"}, "r2"),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=books.tools)

		events = list(agent.run("read both", stream=True))

		shape: list[Any] = []
		for event in events:
			if isinstance(event, ToolStarted):
				shape.append(("started", event.id, event.name, event.arguments))
			elif isinstance(event, ToolEnded):
				shape.append(("ended", event.id, event.result))
			elif isinstance(event, Done):
				shape.append(("done", event.result.paused))
			else:
				shape.append(("text", event.text))

		self.assertEqual(
			shape,
			[
				# announced the moment the model starts emitting each call, arguments still empty
				("started", "r1", "read_balance", {}),
				("started", "r2", "read_balance", {}),
				# re-announced with the full arguments, immediately before each one runs
				("started", "r1", "read_balance", {"account": "alice"}),
				("ended", "r1", "120"),
				("started", "r2", "read_balance", {"account": "bob"}),
				("ended", "r2", "120"),
				("text", "done"),
				("done", False),
			],
		)
		self.assertEqual(books.read, [{"account": "alice"}, {"account": "bob"}])

	def test_a_reply_that_interleaves_text_and_calls_puts_its_text_first(self):
		"""AT8c. QA-L1: AT8b's scripted reply has `content=None`, so it cannot see the one thing
		buffering actually moves — where a reply's text sits relative to its announcements.

		This scripts a stream that INTERLEAVES them, which is the only shape that can tell the
		two engines apart: announce mid-stream and the client sees text, card, text; hold the
		announcements and it sees all the text, then the card. The second is what ships, and it is
		the accepted cost of not being able to tell, while a reply is still arriving, which of its
		calls are going to run. Pinned rather than left as prose, because it is a change to the
		contract `frontend/src/store.js` reads.
		"""
		books = _Books()
		response = ChatResponse(
			content="let me look",
			tool_calls=[ToolCall(id="r1", name="read_balance", arguments={"account": "alice"})],
			finish_reason="tool_calls",
			usage={},
		)

		def _interleaved(scripted: ChatResponse):
			if scripted is not response:  # the closing turn streams normally
				return (yield from _scripted_stream(scripted))
			yield "let me "
			yield ToolCallBegin(id="r1", name="read_balance")
			yield "look"
			return scripted

		model = FakeModel([response, _final("done")])
		model._stream = _interleaved
		agent = Agent(model=model, tools=books.tools)

		events = list(agent.run("balance please", stream=True))

		shape: list[Any] = []
		for event in events:
			if isinstance(event, ToolStarted):
				shape.append(("started", event.id, event.arguments))
			elif isinstance(event, ToolEnded):
				shape.append(("ended", event.id, event.result))
			elif isinstance(event, Done):
				shape.append(("done", event.result.paused))
			else:
				shape.append(("text", event.text))

		self.assertEqual(
			shape,
			[
				# all of the reply's text, uninterrupted...
				("text", "let me "),
				("text", "look"),
				# ...then the announcement it used to be split by
				("started", "r1", {}),
				("started", "r1", {"account": "alice"}),
				("ended", "r1", "120"),
				("text", "done"),
				("done", False),
			],
		)

	def test_the_pause_and_answer_shapes_are_unchanged(self):
		"""AT18. The web apps read these three things and nothing else about a pause. How much
		has already run when the pause arrives is the only thing S19 changes.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])

		for question in paused.questions:
			self.assertEqual(question.options, list(CONFIRM_ANSWER_OPTIONS))
			self.assertTrue(question.allow_other)
		self.assertEqual([q.key for q in paused.questions], ["c2"])

		resumed = agent.resume(paused.messages, {"c2": "Approve"})

		self.assertEqual(books.wrote, [{"to": "alice", "amount": 500}])
		self.assertEqual(resumed.output, "done")


class _Unattended:
	"""A gated write and an ungated read, each recording what actually ran."""

	def __init__(self):
		self.wrote: list[dict[str, Any]] = []
		self.read: list[str] = []
		bag = self

		@tool(requires_confirmation=True)
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			bag.wrote.append({"to": to, "amount": amount})
			return f"sent {amount} to {to}"

		@tool
		def read_balance(account: str) -> str:
			"""Read an account balance."""
			bag.read.append(account)
			return "120"

		self.send_money = send_money
		self.read_balance = read_balance


class TestAnUnattendedRunRefusesEveryGate(UnitTestCase):
	"""S19 Part B. A run with nobody in it cannot be asked anything, so a tool that requires
	asking is refused: it does not run, and it does not park the run waiting for an answer that
	can never come.

	`auto_approve` answered the wrong question. It asked *may questions be skipped in this run*,
	when the only answerable one is *may this tool run unasked in this run* — and the answer to
	that is no.
	"""

	def test_an_unattended_run_refuses_a_gated_tool(self):
		"""AT9."""
		bag = _Unattended()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1")), _final("done")])
		agent = Agent(model=model, tools=[bag.send_money], unattended=True)

		result = agent.run("pay alice")

		self.assertEqual(bag.wrote, [], "a gated write ran in a run with nobody in it")
		self.assertFalse(result.paused)
		self.assertEqual(result.tool_calls, [], "a refused call was reported as one that ran")
		refused = json.loads(_tool_results(result.messages)["c1"])
		self.assertEqual(refused["status"], "not_executed")
		self.assertEqual(refused["reason"], "unattended")
		self.assertEqual(result.output, "done")

	def test_auto_approve_alone_still_counts_as_unattended(self):
		"""AT9b. The backward-compatible path: every caller that passes only `auto_approve` — a
		trigger with the flag on, and upstream's own test — means the same thing by it."""
		bag = _Unattended()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1")), _final("done")])
		agent = Agent(model=model, tools=[bag.send_money], auto_approve=True)

		result = agent.run("pay alice")

		self.assertEqual(bag.wrote, [])
		self.assertFalse(result.paused)
		refused = json.loads(_tool_results(result.messages)["c1"])
		self.assertEqual(refused["reason"], "unattended")

	def test_an_unattended_run_still_executes_an_ungated_tool(self):
		"""AT12. The control. Without it, AT9 is satisfied by an engine that refuses everything —
		which is an outage, not a gate."""
		bag = _Unattended()
		model = FakeModel([_calls(("read_balance", {"account": "alice"}, "r1")), _final("120")])
		agent = Agent(model=model, tools=[bag.read_balance], unattended=True)

		result = agent.run("read alice's balance")

		self.assertEqual(bag.read, ["alice"])
		self.assertEqual([c.name for c in result.tool_calls], ["read_balance"])
		self.assertEqual(result.output, "120")

	def test_an_attended_run_is_unaffected(self):
		"""AT13. Refuse is checked before ask, and must never win when there IS someone to ask."""
		bag = _Unattended()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1"))])
		agent = Agent(model=model, tools=[bag.send_money])

		result = agent.run("pay alice")

		self.assertTrue(result.paused)
		self.assertEqual(len(result.questions), 1)
		self.assertEqual(result.questions[0].options, list(CONFIRM_ANSWER_OPTIONS))
		self.assertEqual(bag.wrote, [])

	def test_a_refused_call_beside_an_ungated_one_stops_neither_the_read_nor_the_run(self):
		"""A refusal is not a pause: the rest of the reply runs and the turn continues, which is
		what keeps an unattended run from stalling on a tool it cannot be asked about."""
		bag = _Unattended()
		model = FakeModel(
			[
				_calls(
					("read_balance", {"account": "alice"}, "r1"),
					("send_money", {"to": "alice", "amount": 500}, "c1"),
				),
				_final("read it, did not pay"),
			]
		)
		agent = Agent(model=model, tools=[bag.read_balance, bag.send_money], unattended=True)

		result = agent.run("read and pay")

		self.assertEqual(bag.read, ["alice"])
		self.assertEqual(bag.wrote, [])
		self.assertFalse(result.paused)
		self.assertEqual([c.name for c in result.tool_calls], ["read_balance"])

	def test_the_refusal_names_no_platform_or_vendor(self):
		"""AT14. CLAUDE.md rule 3, over the literal the model reads."""
		from flow.lib.agent import NOT_EXECUTED_MESSAGES

		self._assert_clean(NOT_EXECUTED_MESSAGES["unattended"])

	def test_control_the_vendor_check_can_go_red(self):
		with self.assertRaises(AssertionError):
			self._assert_clean("this sentence mentions Frappe by name")

	def _assert_clean(self, text: str) -> None:
		for word in ("frappe", "flow", "erpnext", "mariadb", "openai", "anthropic", "gpt", "claude"):
			self.assertNotIn(word, text.lower(), f"{word!r} appears in text the model reads")


class TestOnlyTheInvokeDigestMoved(UnitTestCase):
	"""AT15. CLAUDE.md rule 4: four functions decide what executes and on which answer. S19
	rewrites exactly one of them, `_invoke`, under an exception the owner gave for this spec.
	The other three are quoted here as literals, so this test fails if one of them moves even
	though the pin in `test_deny_stops_batch.py` was re-baselined in the same commit.
	"""

	UNCHANGED = {
		"_resolve_confirmation": "adbb8b26e0b0fb166a5a9fff1c658c531d081b3bd2f2967e55b8e838b5ab8f47",
		# MOVED SINCE, by S26 (run 17, 29 Sep 2026) and not by S19 — the class name above is the
		# statement S19 made, and it was true of S19. The re-baseline is recorded at length beside
		# the canonical pin in `test_deny_stops_batch.py`; the previous value was
		# 32916612298d4ebdb423d9904e268992a2e638b56a67f2ca14fa67deba9cf34c. This literal is kept
		# independent of that pin on purpose: it is what makes a re-baseline of the OTHER TWO
		# below impossible to slip through in one edit.
		"_confirmation_question": "9ee6e922cf59846f322e2c284af895bdf716ba352b78e7b7599a7a58ba8e305e",
		"_has_denial": "80f799b6827afea159589dcee7889282ad8c376aacc15be424c273cd0e55b209",
	}

	def test_the_three_that_did_not_move_are_byte_identical(self):
		from flow.tests.test_deny_stops_batch import TestTheLoadBearingFunctionsAreUntouched as Pin

		pin = Pin("test_the_four_functions_are_byte_identical_to_their_reviewed_form")
		digests = pin._digests(pin._engine_source())

		for name, digest in self.UNCHANGED.items():
			self.assertEqual(digests[name], digest, f"{name} changed; rule 4 requires a spec naming it")

	def test_the_re_baselined_pin_and_the_engine_agree(self):
		"""The control: the pin next door must be describing the engine this test just hashed,
		or a re-baseline could quietly have been taken from something else."""
		from flow.tests.test_deny_stops_batch import TestTheLoadBearingFunctionsAreUntouched as Pin

		pin = Pin("test_the_four_functions_are_byte_identical_to_their_reviewed_form")
		digests = pin._digests(pin._engine_source())

		self.assertEqual(digests["_invoke"], Pin.BASELINE_DIGESTS["_invoke"])
		for name, digest in self.UNCHANGED.items():
			self.assertEqual(Pin.BASELINE_DIGESTS[name], digest)


class TestAnAbandonedTurnNeverExecutesLater(UnitTestCase):
	"""SEC-H1, from the run 11 security adversary. The deferred branch was guarded by
	`have_record` but not by WHICH pause the record belongs to.

	A resume is handed the whole session transcript (`FlowSession._build_prompt_messages`), and
	`_pending_calls` returns every assistant tool call in it that has no tool result, whatever run
	produced it. When a batch pauses, the assistant turn carrying BOTH calls is persisted and
	neither gets a tool result. If that pause is then abandoned — the person presses Stop, which
	clears the run's questions but not its messages, or a resume raises and the run is marked
	failed — the held-back call stays pending in the transcript for ever.

	The next time anything in that session is approved, for anything at all, the abandoned call
	satisfied every condition of the deferred branch and RAN, with its original arguments, on the
	strength of an approval given for something else. Before S19 it fell through to the branch
	below and produced an empty result, so this was a path S19 introduced.

	The rule is the same one R10 settled one door over: act on the turn that is live, never on a
	session's wreckage.
	"""

	def _abandoned_then_a_new_pause(self, books: _Books):
		"""A transcript holding an abandoned mixed-batch pause, then a fresh, unrelated pause."""
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])
		self.assertEqual(books.read, [], "the held-back read ran in the pausing turn")

		messages = list(paused.messages)  # the run was stopped: questions cleared, messages kept
		messages.append({"role": "user", "content": "forget that, pay carol"})
		messages.append(
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "z9",
						"type": "function",
						"function": {
							"name": "send_money",
							"arguments": '{"to": "carol", "amount": 5}',
						},
					}
				],
			}
		)
		asked = [
			Question(
				prompt="Approve `send_money`?",
				options=list(CONFIRM_ANSWER_OPTIONS),
				allow_other=True,
				key="z9",
			)
		]
		return agent, messages, asked

	def test_a_held_back_call_from_an_abandoned_pause_does_not_run_on_a_later_approval(self):
		books = _Books()
		agent, messages, asked = self._abandoned_then_a_new_pause(books)
		agent.model = FakeModel([_final("paid carol")])

		resumed = agent.resume(messages, {"z9": "Approve"}, asked=asked)

		self.assertEqual(
			books.read,
			[],
			"a call from a turn the person abandoned ran on an approval given for something else",
		)
		self.assertEqual(books.wrote, [{"to": "carol", "amount": 5}], "the real approval must run")
		self.assertEqual(
			_tool_results(resumed.messages)["r1"],
			"",
			"the abandoned call must be closed out with nothing, as it was before S19",
		)

	def test_the_same_holds_when_the_later_pause_is_denied(self):
		"""A Deny must not execute it either — and the abandoned call must be told NOTHING.

		The two "nothing ran" assertions alone cannot fail: on the unfixed engine a Deny makes
		`denied_group` true, so the abandoned held-back call takes `group_refused` and the
		abandoned gated one takes `approval_no_longer_applies` — neither runs either way. Found by
		the run 11 QA adversary, which is exactly the class of defect this run exists to remove.

		What actually differs between the two worlds is the RESULT TEXT, and it is not cosmetic:
		both of those sentences are false for a call from a turn nobody is resuming. It was never
		in the group that was refused, and no approval was ever given for it to stop applying.
		"""
		books = _Books()
		agent, messages, asked = self._abandoned_then_a_new_pause(books)

		resumed = agent.resume(messages, {"z9": "Deny"}, asked=asked)

		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])
		results = _tool_results(resumed.messages)
		self.assertEqual(
			results["r1"], "", "an abandoned call was told it was refused with a group it was never in"
		)
		self.assertEqual(
			results["c2"],
			"",
			"an abandoned gated call was told an approval no longer applied to it",
		)

	def _a_reference_the_history_already_answered(self, books: _Books, live_id: str, old_id: str):
		"""An abandoned turn, then a FINISHED turn, then a live gated pause whose call reuses the
		finished turn's reference. Built by hand: the point is the shape of a stored transcript, and
		a provider hands us these references verbatim (`flow/lib/model.py` stores `id` as it comes).
		"""
		agent = Agent(model=FakeModel([_final("unreachable")]), tools=books.tools)
		messages = [
			{"role": "user", "content": "read the ledger"},
			# The wreckage: a turn that paused and was then stopped, so its calls stay pending for ever.
			_assistant_turn([("read_balance", {"account": "victim"}, "w1")]),
			{"role": "user", "content": "read alice"},
			_assistant_turn([("read_balance", {"account": "alice"}, old_id)]),
			{"role": "tool", "tool_call_id": old_id, "content": "120"},
			{"role": "user", "content": "pay bob"},
			_assistant_turn([("send_money", {"to": "bob", "amount": 5}, live_id)]),
		]
		asked = [
			Question(
				prompt="Approve `send_money`?",
				options=list(CONFIRM_ANSWER_OPTIONS),
				allow_other=True,
				key=live_id,
			)
		]
		return agent, messages, asked

	def test_a_reference_the_history_already_answered_refuses_the_resume_and_runs_nothing(self):
		"""S1 (run 11b security review, HIGH, observed). The positional split is defeated by a
		reference, which is the one thing it was built not to trust.

		`live_from` is positional, but the position is computed from which calls still lack a result,
		and `has_result` is a flat set over the whole transcript. So a live gated call whose reference
		was already used by a FINISHED call counts answered: it drops out of `pending`, the last turn
		with anything unanswered is then an older, abandoned one, and the tail — the wreckage — is
		taken for the live turn. It was announced with the model's own arguments and it RAN, on an
		approval the person gave for something else, while the action they did approve got no result
		at all. An ungated neighbour of an abandoned pause is a tool of the model's choosing with
		arguments of the model's choosing.

		Nothing in the transcript can tell the two turns apart — that is F1-1, and its fix is not a
		small one — so this refuses instead of guessing. Fail closed: the approval is lost and the
		person is told, which is the outcome this engine already produces for a pause it cannot read.
		"""
		books = _Books()
		agent, messages, asked = self._a_reference_the_history_already_answered(books, "c1", "c1")

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Approve"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(books.read, [], "a call from a turn the person abandoned ran on their approval")
		self.assertEqual(books.wrote, [])

	def test_the_streamed_resume_of_that_shape_announces_nothing_either(self):
		"""The same refusal on the path a person watches: no card is opened before it raises."""
		books = _Books()
		agent, messages, asked = self._a_reference_the_history_already_answered(books, "c1", "c1")

		seen: list[Any] = []
		with self.assertRaises(ValueError):
			for event in agent.resume(messages, {"c1": "Approve"}, asked=asked, stream=True):
				seen.append(event)

		self.assertEqual([e for e in seen if isinstance(e, ToolStarted)], [])
		self.assertEqual(books.read, [])

	def test_the_same_shape_made_of_empty_references_is_refused_too(self):
		"""S1's second door, and the one this run opened. A stored result whose reference is `""`
		was refused outright by the structural check until run 11b let the replay paths read one —
		so this transcript used to raise before anything ran, and then it ran the wreckage instead.
		The refusal has to cover the shape the relaxation made reachable, not only the tidy one.
		"""
		books = _Books()
		agent, messages, asked = self._a_reference_the_history_already_answered(books, "", "")

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"": "Approve"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])

	def test_the_control_a_live_reference_of_its_own_still_executes_the_approval(self):
		"""The control, and it is what stops the refusal above being written too wide: the identical
		transcript with one token changed — the live call carries its own reference — approves, runs
		the write once, and closes the abandoned call out with nothing.
		"""
		books = _Books()
		agent, messages, asked = self._a_reference_the_history_already_answered(books, "c9", "c1")
		agent.model = FakeModel([_final("paid bob")])

		resumed = agent.resume(messages, {"c9": "Approve"}, asked=asked)

		self.assertEqual(books.wrote, [{"to": "bob", "amount": 5}])
		self.assertEqual(books.read, [], "the abandoned turn's call must still not run")
		self.assertEqual(_tool_results(resumed.messages)["w1"], "")

	def test_an_abandoned_call_is_not_announced_on_a_streamed_resume(self):
		"""The streamed half of the same rule, and the one a person actually sees.

		`announce` was computed from the question record alone, so a call from an abandoned turn —
		which by construction nobody was asked about — was announced with its FULL ARGUMENTS on the
		resumed stream, immediately before being ended with an empty result. The engine correctly
		refused to run it and then drew a card for it, on the screen where the person had just
		approved something else. Those arguments are model-authored text; CLAUDE.md's last lesson
		is that model-controlled values never change the shape of what a person is shown around an
		approval.
		"""
		books = _Books()
		agent, messages, asked = self._abandoned_then_a_new_pause(books)
		agent.model = FakeModel([_final("paid carol")])

		events = list(agent.resume(messages, {"z9": "Approve"}, asked=asked, stream=True))

		# Nothing at all is announced here: the abandoned calls are not going to run, and z9 was
		# announced when the run paused on it — it is the call the person has been looking at.
		# Before the fix this read ['r1', 'c2'], both with their arguments.
		self.assertEqual(
			[e.id for e in events if isinstance(e, ToolStarted)],
			[],
			"a card was opened for an action from a turn the person abandoned",
		)
		self.assertNotIn("alice", json.dumps([e.arguments for e in events if isinstance(e, ToolStarted)]))
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [{"to": "carol", "amount": 5}])

	def test_an_abandoned_call_closes_no_card_either_on_a_streamed_resume(self):
		"""F2-2. The other half of the same frame: the start was gated, the end never was.

		`announce` decided whether a `tool_started` went out, and the `tool_ended` beside it went
		out unconditionally. So a resume replayed an ending for a call from a turn nobody is
		resuming — a call that did not run, has no card, and is not part of the message block the
		client is streaming into. Both shipped clients drop it (a result for a part they do not
		hold), so nothing is visibly broken; the invariant a client is entitled to rely on is
		nonetheless false, and a consumer that draws a card ON a result rather than dropping it
		would draw the abandoned action at the end of an approval it had nothing to do with.

		What the person is answering is one turn. That turn is what the resumed stream describes:
		every id it ends either started in this same stream, or is one of the questions the person
		has been looking at. The abandoned turn is still closed out in `messages` — the record is
		unchanged, and `test_a_held_back_call_from_an_abandoned_pause_does_not_run_on_a_later_approval`
		pins that — it is only no longer narrated to a client that has nowhere to put it.
		"""
		books = _Books()
		agent, messages, asked = self._abandoned_then_a_new_pause(books)
		agent.model = FakeModel([_final("paid carol")])

		events = list(agent.resume(messages, {"z9": "Approve"}, asked=asked, stream=True))

		started = [e.id for e in events if isinstance(e, ToolStarted)]
		ended = [e.id for e in events if isinstance(e, ToolEnded)]
		# Before the fix this read ['r1', 'c2', 'z9']: two endings for calls the person never saw.
		self.assertEqual(ended, ["z9"], "an ending was replayed for a call from an abandoned turn")
		self.assertLessEqual(
			set(ended),
			set(started) | {q.key for q in asked},
			"a tool_ended arrived for an id with no card: not started here, and never asked about",
		)
		# The record is untouched: the abandoned call is still resolved with nothing in `messages`.
		resumed = next(e for e in events if isinstance(e, Done)).result
		self.assertEqual(_tool_results(resumed.messages)["r1"], "")
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [{"to": "carol", "amount": 5}])

	def test_with_no_question_record_a_streamed_resume_announces_nothing_either(self):
		"""The second instance of the same root cause. With `asked=None` — a supported,
		documented call — `question_keys` is empty, so every resolved call looked un-asked-about
		and was announced, including the ones the engine then refuses to act on."""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])

		events = list(agent.resume(paused.messages, {}, asked=None, stream=True))

		self.assertEqual(
			[e.id for e in events if isinstance(e, ToolStarted)],
			[],
			"a card was opened for a call the engine refused to act on",
		)
		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])

	def test_one_approval_cannot_execute_a_gated_call_from_an_abandoned_turn_as_well(self):
		"""SEC-M1. The S17 guarantee across turns, not only within one.

		Every indistinguishability check in the engine is per assistant message. Two SEPARATE
		turns each holding an unanswered call with the same reference are never compared — and
		`_prepare_resume` looks every answer up by `call.id`, so one "Approve" is handed to both.
		If both are gated, `_resolve_confirmation` runs both tools: one approval, two writes,
		which is the single thing this fork exists to prevent.

		Reachable the same way SEC-H1 is: pause, abandon the run, and collide on an id — certain
		if a provider ever emits an empty or constant reference, since such a call can never be
		marked answered and so stays pending for ever.
		"""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])
		gated = {
			"id": "c2",
			"type": "function",
			"function": {"name": "send_money", "arguments": '{"to": "mallory", "amount": 9000}'},
		}
		messages = list(paused.messages)  # abandoned: the pause on c2 was never answered
		messages.append({"role": "user", "content": "actually pay dave"})
		messages.append(
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "c2",  # the same reference as the abandoned turn's gated call
						"type": "function",
						"function": {
							"name": "send_money",
							"arguments": '{"to": "dave", "amount": 5}',
						},
					}
				],
			}
		)
		messages[1]["tool_calls"][1] = gated  # the abandoned one pays mallory 9000
		asked = [
			Question(
				prompt="Approve `send_money`?",
				options=list(CONFIRM_ANSWER_OPTIONS),
				allow_other=True,
				key="c2",
			)
		]
		agent.model = FakeModel([_final("paid dave")])

		agent.resume(messages, {"c2": "Approve"}, asked=asked)

		self.assertEqual(
			books.wrote,
			[{"to": "dave", "amount": 5}],
			"one approval executed a second gated call from a turn nobody answered",
		)
		self.assertEqual(books.read, [])

	def test_control_a_held_back_call_in_the_live_turn_still_runs(self):
		"""The control. Without it, "never defer" would satisfy both tests above and would undo
		the whole of Part A's contract that a held-back call is held, not dropped."""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("done")])

		agent.resume(paused.messages, {"c2": "Approve"}, asked=paused.questions)

		self.assertEqual(books.read, [{"account": "alice"}])
		self.assertEqual(books.wrote, [{"to": "alice", "amount": 500}])


class TestWhatAPartialAnswerDoesToTheHeldBackCalls(UnitTestCase):
	"""L4, from REVIEW-FLOW-10 — pinned rather than changed, so it is a decision and not an
	accident. **The owner's call, recorded OPEN in run 11.**

	Only a denial holds the group back: `_has_denial` matches the exact string "Deny" and nothing
	else. So a person who REDIRECTS ("no, do it differently") and a client that posts `{}` both get
	the held-back calls executed anyway. That follows the documented group rule, and it is no worse
	than before S19, where the held-back read had already run before anyone was asked at all.

	It is not nothing, though: a redirect reads to a person like a refusal, and the read they were
	shown in the same breath as the write goes ahead. The shipped client cannot reach it — it sends
	answers for exactly the recorded questions (`frontend/src/store.js:375-379`), so the deferred
	keys are absent and the group is neither denied nor redirected. Narrowing it means deciding
	that a redirect refuses the group, which changes the reach of an approved spec.

	These tests exist so that a later change to `_has_denial`'s reach is seen rather than
	discovered.
	"""

	def test_a_free_text_redirect_still_runs_the_held_back_call(self):
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("ok")])

		resumed = agent.resume(paused.messages, {"c2": "send 400 instead"}, asked=paused.questions)

		self.assertEqual(books.wrote, [], "a redirect is not an approval")
		self.assertEqual(
			books.read,
			[{"account": "alice"}],
			"today's rule: only an exact Deny holds the group back",
		)
		self.assertFalse(resumed.paused)

	def test_an_empty_answers_map_still_runs_the_held_back_call(self):
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books, extra=[_final("ok")])

		resumed = agent.resume(paused.messages, {}, asked=paused.questions)

		self.assertEqual(books.wrote, [])
		self.assertEqual(books.read, [{"account": "alice"}])
		self.assertFalse(resumed.paused)

	def test_and_an_exact_deny_does_hold_it_back(self):
		"""The control that makes the two above mean something: the group rule is real, it is
		just narrow."""
		books = _Books()
		agent, _model, paused = _pause_on_a_mixed_batch(books)

		agent.resume(paused.messages, {"c2": "Deny"}, asked=paused.questions)

		self.assertEqual(books.read, [])
		self.assertEqual(books.wrote, [])


class TestAnUnattendedRunCannotParkAtAll(UnitTestCase):
	"""M2 — the other way a run pauses, which the rule did not name.

	Part B closes the `requires_confirmation` route. It did not close the second one: a tool whose
	BODY returns a `Question`. `_disposition` deliberately excludes those — by the time such a
	question exists the tool has already run, so holding its neighbours back would protect nothing,
	which is correct for Part A and does not carry to Part B. In an unattended run such a question
	still parked the run in `Paused`, holding its session, with nobody who could ever answer it:
	exactly the failure S19 exists to remove, arriving by the other door.

	Not reachable from shipped configuration — the only `Question(` built outside tests in
	`flow/{tools,lib,memory,knowledge}` is `_confirmation_question` (measured; that same grep is
	the positive control for "no other hits"). It is a supported pattern for code agents and
	upstream exercises it, so it is reachable for anyone writing one.
	"""

	def _asking_tool(self, ran: list[str]):
		@tool
		def ask_user(prompt: str) -> Question:
			"""Ask the user something."""
			ran.append(prompt)
			return Question(prompt=prompt, options=["A", "B"])

		return ask_user

	def test_a_tools_own_question_does_not_park_an_unattended_run(self):
		ran: list[str] = []
		agent = Agent(
			model=FakeModel([_calls(("ask_user", {"prompt": "ok?"}, "c1")), _final("done")]),
			tools=[self._asking_tool(ran)],
			unattended=True,
		)

		result = agent.run("ask me")

		self.assertFalse(result.paused, "an unattended run parked on a question nobody can answer")
		self.assertEqual(result.questions, [])
		self.assertEqual(ran, ["ok?"], "the tool body did not run")
		refused = json.loads(_tool_results(result.messages)["c1"])
		self.assertEqual(refused["status"], "not_executed")
		self.assertEqual(refused["reason"], "unattended")
		self.assertEqual(result.output, "done")

	def test_the_streamed_loop_does_not_park_either(self):
		"""The second copy of the same decision. A fix in one loop and not the other is how the
		web path keeps a defect the unit path no longer has."""
		ran: list[str] = []
		agent = Agent(
			model=FakeModel([_calls(("ask_user", {"prompt": "ok?"}, "c1")), _final("done")]),
			tools=[self._asking_tool(ran)],
			unattended=True,
		)

		events = list(agent.run("ask me", stream=True))

		done = next(e for e in events if isinstance(e, Done))
		self.assertFalse(done.result.paused)
		self.assertEqual(done.result.questions, [])
		self.assertEqual(ran, ["ok?"])
		ended = {e.id: e.result for e in events if isinstance(e, ToolEnded)}
		self.assertEqual(json.loads(ended["c1"])["reason"], "unattended")

	def test_control_an_attended_run_still_pauses_on_a_tools_own_question(self):
		"""Without this, "refuse every question" would satisfy both tests above and would break
		the pattern upstream's own `test_other_tools_run_while_a_question_pauses` relies on."""
		ran: list[str] = []
		agent = Agent(
			model=FakeModel([_calls(("ask_user", {"prompt": "ok?"}, "c1"))]),
			tools=[self._asking_tool(ran)],
		)

		result = agent.run("ask me")

		self.assertTrue(result.paused)
		self.assertEqual([q.key for q in result.questions], ["c1"])
		self.assertEqual(ran, ["ok?"])


class TestAResumeIsNeverUnattended(UnitTestCase):
	"""AT17, the unit half. A resume exists because a person is answering.

	`FlowSession.chat` assigns `unattended` every turn; `FlowSession.resume` assigned neither flag,
	and `flow/lib/session.py:78-79` hands back the CALLER'S OWN `Agent` object when one was passed
	in. So an in-process caller that ran an unattended turn and then resumed on the same object
	carried `unattended=True` into a run a person was answering, and the model's next gated call in
	that run was refused as though nobody were there.
	"""

	def test_a_resume_is_never_unattended(self):
		books = _Books()
		agent = Agent(
			model=FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1"))]),
			tools=books.tools,
		)
		paused = agent.run("pay alice")
		self.assertTrue(paused.paused, "attended: it must ask")

		# A previous unattended turn mutated this object, and nothing clears it.
		agent.unattended = True
		agent.model = FakeModel([_calls(("send_money", {"to": "bob", "amount": 10}, "c2")), _final("done")])
		resumed = agent.resume(paused.messages, {"c1": "Approve"}, asked=paused.questions)

		self.assertEqual(
			books.wrote,
			[{"to": "alice", "amount": 500}],
			"the approval a person gave was refused as though nobody were there",
		)
		self.assertTrue(resumed.paused, "a new gated call in a resumed run must ask, not be refused")
		self.assertEqual([q.key for q in resumed.questions], ["c2"])


class TestASessionResumeIsNeverUnattended(IntegrationTestCase):
	"""AT17, the half that pins the fix. The runtime a session holds is reused across turns, so a
	resume must say what it is rather than inherit what the last turn happened to be.

	Runs as a named non-Administrator, because a resume is a permission-bearing path
	(`assert_run_owner`) and Administrator would not measure it.
	"""

	S19_RESUMER = "s19-resumer@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from flow.tools.builtins import sync_builtin_tools

		sync_builtin_tools()
		cls.enterClassContext(cls.enable_safe_exec())

	def setUp(self):
		if not frappe.db.exists("User", self.S19_RESUMER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.S19_RESUMER,
					"first_name": "S19R",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("System Manager")
		model = frappe.get_doc(
			{
				"doctype": "Flow Model",
				"title": "S19R Model",
				"model_id": "openai/gpt-4o-mini",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.agent_doc = frappe.get_doc(
			{
				"doctype": "Flow Agent",
				"title": "S19R Agent",
				"model": model.name,
				"instructions": "Be terse.",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.S19_RESUMER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_a_resumed_run_still_asks_on_a_runtime_a_previous_turn_left_unattended(self):
		"""The approval itself is not the test: `_resolve_confirmation` runs the approved tool
		without consulting `_disposition`, so a leaked `unattended` cannot show up there. It shows
		up in the CONTINUATION — the model's next gated call in the same run a person is sitting
		in front of, which was refused with "this run has nobody who can approve it" while they
		were the one who had just approved something.
		"""
		from unittest.mock import patch

		from flow.lib.model import Model
		from flow.lib.session import load_session

		seen_users: list[str] = []

		def _script(*args, **kwargs):
			seen_users.append(frappe.session.user)
			call_id = "c1" if len(seen_users) == 1 else "c2"
			if len(seen_users) <= 2:
				return ChatResponse(
					content=None,
					tool_calls=[ToolCall(id=call_id, name="execute", arguments={"code": "result = 7"})],
					finish_reason="tool_calls",
					usage={},
				)
			return _final("done")

		with patch.object(Model, "chat", side_effect=_script):
			run = self.agent_doc.run("compute something")
		self.assertEqual(run.status, "Paused", "an attended run must ask")
		self.assertEqual(seen_users[0], self.S19_RESUMER, "the run did not run as the asking user")

		session = load_session(frappe.db.get_value("Flow Run", run.name, "session"))
		# Stand in for a runtime a previous unattended turn mutated. `FlowSession.resume` never
		# cleared this, and `_disposition` reads it on every later call in the resumed run.
		session._runtime.unattended = True

		with patch.object(Model, "chat", side_effect=_script):
			resumed = session.resume({"c1": "Approve"})

		results = [
			m.content
			for m in frappe.get_all(
				"Flow Session Message",
				filters={"parent": run.session, "role": "tool"},
				fields=["content"],
				order_by="idx",
			)
		]
		self.assertTrue(results, "the resumed run stored no tool result at all")
		self.assertIn("7", results[0], "the approval a person gave did not run")
		self.assertEqual(
			resumed.status,
			"Paused",
			"a new gated call was refused as though nobody were there, in a run a person was in",
		)
		for content in results:
			self.assertNotIn("not_executed", content)


class TestARealTriggerRunRefusesInsteadOfParking(IntegrationTestCase):
	"""AT16. Part B pinned to a real run rather than to a code `Agent`.

	`FlowSession.chat` is the only place that knows a run has nobody in it — it computes
	`unattended` for the memory tool already — and until S19 it never told the runtime. A trigger
	with `auto_approve` OFF therefore raised a question nobody could answer and left the run in
	`Paused`, holding its session. Delete the one line that tells the runtime and this test is
	what goes red.

	It runs as the trigger's own `run_as` user, a named non-Administrator, because that is what
	`flow/triggers/triggers.py:75` sets and what any permission this path relies on would be
	measured against.
	"""

	S19_TESTER = "s19-trigger@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from flow.tools.builtins import sync_builtin_tools

		sync_builtin_tools()
		cls.enterClassContext(cls.enable_safe_exec())

	def setUp(self):
		if not frappe.db.exists("User", self.S19_TESTER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.S19_TESTER,
					"first_name": "S19",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("System Manager")
		model = frappe.get_doc(
			{"doctype": "Flow Model", "title": "S19 Model", "model_id": "openai/gpt-4o-mini", "enabled": 1}
		).insert(ignore_permissions=True)
		agent = frappe.get_doc(
			{
				"doctype": "Flow Agent",
				"title": "S19 Agent",
				"model": model.name,
				"instructions": "Be terse.",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.trigger = frappe.get_doc(
			{
				"doctype": "Flow Trigger",
				"title": "S19 Trigger",
				"agent": agent.name,
				"enabled": 1,
				"event": "DocType Event",
				"target_doctype": "ToDo",
				"doc_event": "after_insert",
				"prompt_template": "New {{ doc.doctype }}",
				"auto_approve": 0,
				"run_as": self.S19_TESTER,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_a_trigger_with_auto_approve_off_refuses_instead_of_pausing(self):
		from unittest.mock import patch

		from flow.lib.model import Model
		from flow.triggers import fire

		seen_users: list[str] = []

		def _script(*args, **kwargs):
			seen_users.append(frappe.session.user)
			if len(seen_users) == 1:
				return ChatResponse(
					content=None,
					tool_calls=[ToolCall(id="c1", name="execute", arguments={"code": "result = 1"})],
					finish_reason="tool_calls",
					usage={},
				)
			return _final("done")

		todo = frappe.get_doc({"doctype": "ToDo", "description": "s19"}).insert(ignore_permissions=True)
		with patch.object(Model, "chat", side_effect=_script):
			run_name = fire(self.trigger.name, target_doctype="ToDo", target_name=todo.name)

		run = frappe.get_doc("Flow Run", run_name)
		self.assertEqual(run.status, "Completed", "the run parked waiting for an answer nobody can give")
		self.assertEqual(json.loads(run.tool_calls or "[]"), [], "the gated tool ran unattended")
		self.assertEqual(seen_users[0], self.S19_TESTER, "the run did not run as the trigger's user")
		results = [
			m.content
			for m in frappe.get_all(
				"Flow Session Message",
				filters={"parent": run.session, "role": "tool"},
				fields=["content"],
				order_by="idx",
			)
		]
		self.assertTrue(results, "the run stored no tool result at all")
		refused = json.loads(results[-1])
		self.assertEqual(refused["status"], "not_executed")
		self.assertEqual(refused["reason"], "unattended")

	def test_a_trigger_with_auto_approve_on_refuses_too_and_the_name_upstream_kept_says_otherwise(self):
		"""AT16b. The fork's accurate copy of upstream's
		`test_fire_auto_approves_confirmation_tools_when_enabled`.

		That upstream test asserts only `status == "Completed"`, which was true BEFORE S19 (the
		tool ran, the run completed) and is true AFTER (the tool is refused, the run completes) —
		it cannot tell the difference, and its name now says the opposite of what happens. Run 10
		renamed it; run 11 put the name back, because the rename was outside the window the owner
		allowed and a rename asserts nothing anyway. The behaviour is asserted here instead, in a
		file the fork owns: the tool did not run, the run did not park, and the refusal is on the
		record with its reason.
		"""
		from unittest.mock import patch

		from flow.lib.model import Model
		from flow.triggers import fire

		self.trigger.auto_approve = 1
		self.trigger.save(ignore_permissions=True)

		seen_users: list[str] = []

		def _script(*args, **kwargs):
			seen_users.append(frappe.session.user)
			if len(seen_users) == 1:
				return ChatResponse(
					content=None,
					tool_calls=[ToolCall(id="c1", name="execute", arguments={"code": "result = 1"})],
					finish_reason="tool_calls",
					usage={},
				)
			return _final("done")

		todo = frappe.get_doc({"doctype": "ToDo", "description": "s19-auto"}).insert(ignore_permissions=True)
		with patch.object(Model, "chat", side_effect=_script):
			run_name = fire(self.trigger.name, target_doctype="ToDo", target_name=todo.name)

		run = frappe.get_doc("Flow Run", run_name)
		self.assertNotEqual(run.status, "Paused", "the run parked with nobody who can answer")
		self.assertEqual(run.status, "Completed")
		self.assertEqual(json.loads(run.tool_calls or "[]"), [], "the gated tool ran unattended")
		self.assertEqual(seen_users[0], self.S19_TESTER, "the run did not run as the trigger's user")
		results = [
			m.content
			for m in frappe.get_all(
				"Flow Session Message",
				filters={"parent": run.session, "role": "tool"},
				fields=["content"],
				order_by="idx",
			)
		]
		self.assertTrue(results, "the run stored no tool result at all")
		refused = json.loads(results[-1])
		self.assertEqual(refused["status"], "not_executed")
		self.assertEqual(refused["reason"], "unattended")


class _Claims:
	"""An ungated read, and an ungated tool that returns a QUESTION of its own.

	The second is the pause `_approval_question_keys` cannot see. Nobody was asked to APPROVE
	anything: the tool's body ran and handed back a question carrying its own options, so the
	record of that pause holds a key whose options are not `CONFIRM_ANSWER_OPTIONS`.

	No tool shipped in this repository returns a `Question` today, which is why C1 is latent
	rather than live — but the engine supports the path in full (`_loop_stream`, "The second way a
	run pauses"), and a bare callable makes an app-side one a one-liner. A defect reachable by
	anyone writing an ordinary tool is a defect.
	"""

	def __init__(self):
		self.read: list[dict[str, Any]] = []
		self.filed: list[dict[str, Any]] = []
		claims = self

		@tool
		def read_balance(account: str) -> str:
			"""Read an account balance."""
			claims.read.append({"account": account})
			return "120"

		@tool
		def file_claim(reference: str) -> Any:
			"""File a claim."""
			claims.filed.append({"reference": reference})
			return Question(
				prompt="Which address should the claim go to?",
				options=["Yes", "No, use the other address"],
				allow_other=True,
			)

		self.read_balance = read_balance
		self.file_claim = file_claim
		self.tools = [read_balance, file_claim]


class TestAPauseThatRaisedNoApprovalQuestionIsHeldToTheSameRule(UnitTestCase):
	"""C1 (REVIEW-FLOW-11c, HIGH). The live-slice guard read the record for APPROVAL questions
	only, so a pause that raised none short-circuited it away and S1 returned verbatim.

	A run pauses two ways: the engine asks a person to approve a gated call, or a tool returns a
	`Question` of its own. The guard was written `if have_record and approval_keys and ...`, and
	`_approval_question_keys` keeps a key only when its options are exactly the engine's two — so
	on the second kind of pause `approval_keys` is empty, the `and` short-circuits, and every rule
	below is the code the security reviewer broke: an abandoned turn's ungated call RUNS, with the
	model's own arguments, announced on the screen where a person had just answered about
	something else, while the action they answered about gets no result at all.

	The record says a pause happened and which calls it was about. Which KIND of question raised
	it changes nothing about that, and a question of either kind belongs to a call that is still
	pending — the tool-question path `continue`s before the line that files a result (C2), so its
	call has none. So the rule is one rule: if the record names calls and none of them is in the
	turn about to be acted on, the record cannot say which turn this answer belongs to.
	"""

	def _a_tool_question_pause(self, claims: _Claims, live_id: str, old_id: str, *, approval=False):
		"""The reviewer's S1 transcript with one token changed: the live pause is a question the
		TOOL returned, not an approval. Hand-built, because that is the shape a STORED transcript
		holds after a run was stopped — and a provider hands these references back verbatim.
		"""
		agent = Agent(model=FakeModel([_final("unreachable")]), tools=claims.tools)
		messages = [
			{"role": "user", "content": "read the ledger"},
			# The wreckage: a turn that paused and was then stopped, so its call stays pending for ever.
			_assistant_turn([("read_balance", {"account": "victim"}, "w1")]),
			{"role": "user", "content": "read alice"},
			_assistant_turn([("read_balance", {"account": "alice"}, old_id)]),
			{"role": "tool", "tool_call_id": old_id, "content": "120"},
			{"role": "user", "content": "file the claim"},
			_assistant_turn([("file_claim", {"reference": "AB-1"}, live_id)]),
		]
		options = list(CONFIRM_ANSWER_OPTIONS) if approval else ["Yes", "No, use the other address"]
		asked = [
			Question(
				prompt="Which address should the claim go to?",
				options=options,
				allow_other=True,
				key=live_id,
			)
		]
		return agent, messages, asked

	def test_a_pause_with_no_approval_question_refuses_the_resume_and_runs_nothing(self):
		"""(a) C1 itself. Walked against the head bytes before it was written, and observed red:
		`ToolStarted(id='w1', name='read_balance', arguments={'account': 'victim'})` went out and
		`read_balance` ran on `{"account": "victim"}` — the model's own argument — because
		`approval_keys` was empty and the guard was never evaluated.
		"""
		claims = _Claims()
		agent, messages, asked = self._a_tool_question_pause(claims, "c1", "c1")

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Yes"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(
			claims.read,
			[],
			"a call from a turn the person abandoned ran on an answer given for something else",
		)
		self.assertEqual(claims.filed, [], "nothing in the live turn re-ran either")

	def test_and_that_refusal_announces_nothing_on_the_streamed_path(self):
		"""(a), on the path a person watches: no card is opened before it raises. The defect drew
		the abandoned call's model-authored arguments onto the screen immediately after the
		person's answer, which is the E5-class defect c7c87dc and 65f18fb removed.
		"""
		claims = _Claims()
		agent, messages, asked = self._a_tool_question_pause(claims, "c1", "c1")

		seen: list[Any] = []
		with self.assertRaises(ValueError):
			for event in agent.resume(messages, {"c1": "Yes"}, asked=asked, stream=True):
				seen.append(event)

		self.assertEqual([e for e in seen if isinstance(e, ToolStarted)], [])
		self.assertEqual([e for e in seen if isinstance(e, ToolEnded)], [])
		self.assertEqual(claims.read, [])

	def test_the_same_shape_with_an_approval_question_is_refused_exactly_as_before(self):
		"""(b) The regression pin. This shape already refused at 3c10043 — it is the half of the
		rule the narrow guard did cover — and widening the guard must not change it by one byte.
		Green before the fix and green after it, and that is the point: the fix ADDS a case, it
		does not move the one that worked.
		"""
		claims = _Claims()
		agent, messages, asked = self._a_tool_question_pause(claims, "c1", "c1", approval=True)

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Approve"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(claims.read, [])
		self.assertEqual(claims.filed, [])

	def test_the_control_a_sound_tool_question_pause_is_not_refused(self):
		"""(c) The control that proves the fix is not over-broad, and the one a mutation has to
		keep green. The identical transcript with one token changed — the live call carries its
		own reference — resolves the tool's question with the person's answer, runs nothing extra,
		and closes the abandoned call out with nothing, exactly as it did before the fix.

		This is also the evidence for C2's correction: if a tool-own-question call really "already
		had a result" it would not be pending, `live_ids` would not hold it, and including
		`question_keys` in the guard would refuse THIS resume. It does not.
		"""
		claims = _Claims()
		agent, messages, asked = self._a_tool_question_pause(claims, "c9", "c1")
		agent.model = FakeModel([_final("filed")])

		resumed = agent.resume(messages, {"c9": "Yes"}, asked=asked)

		results = _tool_results(resumed.messages)
		self.assertEqual(results["c9"], "Yes", "the answer is the tool question's result, as ever")
		self.assertEqual(results["w1"], "", "the abandoned turn's call is still closed out with nothing")
		self.assertEqual(claims.read, [], "the abandoned turn's call must still not run")
		self.assertEqual(claims.filed, [], "the tool's body already ran; a resume must not run it again")

	def test_a_tool_that_asks_its_own_question_leaves_its_call_pending(self):
		"""C2 (MEDIUM). The one-line assertion that pins the fact the old comment denied.

		The comment justifying `approval_keys, never question_keys` said a tool's own question
		"already has a result". `_loop_stream` `continue`s before the only line that files one, so
		the call has NO tool result and is pending exactly like an approval's call. That false
		premise is what left C1 open, and this assertion is what stops it being written again.
		"""
		claims = _Claims()
		agent = Agent(
			model=FakeModel([_calls(("file_claim", {"reference": "AB-1"}, "c1"))]), tools=claims.tools
		)

		paused = agent.run("file the claim")

		self.assertTrue(paused.paused)
		self.assertNotIn("c1", _tool_results(paused.messages))

	def test_an_approval_question_whose_key_is_unusable_still_refuses_the_wreckage(self):
		"""C3 (LOW). The same door, reached by a reference rather than by a kind of question.

		Both key readers drop a key that is not a usable string, so a legacy pause whose only
		question was keyed `None` recorded, as far as the guard could see, no question at all —
		and the guard was skipped, and the wreckage ran. Every other rule in this file folds a
		reference through `_call_reference` for exactly this reason: one definition, so no two
		rules disagree about what counts as usable.
		"""
		claims = _Claims()
		agent, messages, asked = self._a_tool_question_pause(claims, "c1", "c1", approval=True)
		asked[0].key = None

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Approve"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(claims.read, [], "the wreckage ran because a key the record held was dropped")

	def test_an_unusable_reference_is_not_an_identity_that_satisfies_the_guard(self):
		"""M1 (run 11d security review, MEDIUM, EXECUTED). The regression the first draft of this
		fix introduced, and the reason the sentinel is subtracted rather than compared.

		`_call_reference` exists to say a reference is UNUSABLE. Folding it onto BOTH sides of a
		set test turned "unusable" into a value that matches ITSELF: an unusable recorded key and
		an unusable live call id both became the sentinel, the sets intersected, and the guard was
		skipped — on a transcript 3c10043 refused. The abandoned turn's `read_balance` then ran on
		the model's own `{"account": "victim"}` and was announced with them, while the call the
		person approved got no result. A reference that cannot answer anything cannot be evidence
		that the record and the live turn are the same turn.
		"""
		claims = _Claims()
		agent = Agent(model=FakeModel([_final("unreachable")]), tools=claims.tools)
		messages = [
			{"role": "user", "content": "read the ledger"},
			_assistant_turn([("read_balance", {"account": "victim"}, None)]),
			{"role": "user", "content": "file the claim"},
			_assistant_turn([("file_claim", {"reference": "AB-1"}, "c1")]),
			{"role": "tool", "tool_call_id": "c1", "content": "already done"},
		]
		asked = [
			Question(prompt="Approve?", options=list(CONFIRM_ANSWER_OPTIONS), allow_other=True, key="c1"),
			Question(prompt="Which address?", options=["Yes", "No"], allow_other=True, key=None),
		]

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Approve"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(
			claims.read, [], "the abandoned turn's call ran because two unusable references matched"
		)

	def test_and_the_ladder_still_decides_a_literal_sentinel_reference_as_it_always_did(self):
		"""L1 (same review, LOW, EXECUTED). The other half of the same mistake, one branch down.

		`question_keys` is read by `announce` and by three branches of the ladder, all comparing a
		RAW `call.id`. A stored transcript can hold the literal string `"<none>"` as an id, and that
		string IS the sentinel — so folding the keys moved two of those decisions, and one of them
		wrote the CALLER'S OWN ANSWER TEXT into the transcript as that tool's result, which is the
		exact harm the branch above it exists to prevent. The keys are no longer folded; the record
		being non-empty is what the guard reads, and it reads it from `asked`, not from a sentinel.
		"""
		claims = _Claims()
		agent = Agent(model=FakeModel([_final("unreachable")]), tools=claims.tools)
		messages = [
			{"role": "user", "content": "read the ledger"},
			_assistant_turn([("read_balance", {"account": "victim"}, "<none>")]),
		]
		asked = [Question(prompt="Which address?", options=["Yes", "No"], allow_other=True, key=None)]

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"<none>": "INJECTED TEXT AS TOOL RESULT"}, asked=asked)

		self.assertEqual(str(caught.exception), _UNRESOLVABLE_PAUSE)
		self.assertEqual(claims.read, [])
