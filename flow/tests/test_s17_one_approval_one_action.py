# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S17 — one approval answers one action.

Every decision the engine makes about a tool call is keyed by that call's reference: which calls
are still pending, which question a person is answering, which call an answer resolves. When two
calls in one model reply cannot be told apart by that reference, all three collapse onto one. The
interface stamps one card, a person approves one action, and two happen.

Two calls cannot be told apart in two ways, and they fail identically downstream:

  - they carry the same id;
  - neither carries a usable one. A provider sending ``{"id": null}`` twice, or a gateway that
    omits the field, or a stream that never delivers it, all produce a turn whose calls share the
    empty reference. Nothing in the engine refused that before, and it is the likelier shape.

Such a turn is REFUSED — nothing runs, nothing is written, and the turn never enters the
transcript — and a stored transcript already carrying one cannot be resumed.

What these tests do NOT cover, said plainly rather than left to be inferred: the `auto_approve`
switch and the order in which a batch executes. Both are separate known defects with their own
entries, and nothing here changes either.

No permission surface, with one exception: every test here but one drives `flow/lib/agent.py` with
a fake model and reads no document, so the named-non-Administrator rule does not apply.
`TestASessionWhoseHistoryIsPoisonedStaysUsable` does create a `Flow Session` and its message rows,
and runs as Administrator deliberately: what it measures is whether a stored transcript can still be
replayed at all, and no permission rule is under test in it.
"""

from typing import Any
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from flow.lib import agent as agent_module
from flow.lib.agent import _UNANSWERABLE_TURN, _UNFILEABLE_CALL, Agent, Done, ToolEnded, ToolStarted
from flow.lib.model import ChatResponse, Model, ToolCall, ToolCallBegin
from flow.lib.session import load_session
from flow.lib.tool import tool

FORBIDDEN = ("frappe", "erpnext", "mariadb", "openai", "anthropic", "gpt-", "claude", "flow")


class FakeModel:
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
	"""A scripted stream, including the mid-stream tool announcements the real one carries.

	Without the `ToolCallBegin`s this helper produces no `ToolStarted` events at all, so any test
	claiming to observe what a client draws would be asserting over an empty list and could not
	fail. That is exactly what the first draft of `TestTheStreamedRefusalIsHonest` did.
	"""
	if response.content:
		yield response.content
	for call in response.tool_calls or []:
		yield ToolCallBegin(id=call.id, name=call.name)
	return response


def _final(text: str) -> ChatResponse:
	return ChatResponse(
		content=text,
		finish_reason="stop",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


def _calls(*specs: tuple[str, dict[str, Any], Any]) -> ChatResponse:
	"""One assistant turn asking for several tools at once: (name, arguments, call_id).

	`call_id` is passed through untouched — `None` and `""` are the shapes a provider actually
	produces (a null in the payload, or a field never streamed), and this helper must be able to
	build them.
	"""
	return ChatResponse(
		content=None,
		tool_calls=[ToolCall(id=call_id, name=name, arguments=args) for name, args, call_id in specs],
		finish_reason="tool_calls",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


class _Recorder:
	"""One gated tool and one ungated one, both recording every execution.

	"Nothing ran" is asserted against this list and never inferred from the shape of a result.
	The ungated tool is the one that matters: a gated pair pauses today, so a gated batch cannot
	show the double execution. An ungated pair runs, twice, with nobody asked anything.
	"""

	def __init__(self):
		self.ran: list[tuple[str, dict[str, Any]]] = []
		recorder = self

		@tool(requires_confirmation=True)
		def send_money(to: str, amount: int) -> str:
			"""Send money to someone."""
			recorder.ran.append(("send_money", {"to": to, "amount": amount}))
			return f"sent {amount} to {to}"

		@tool
		def append_line(text: str) -> str:
			"""Append a line to the log."""
			recorder.ran.append(("append_line", {"text": text}))
			return f"appended {text}"

		self.send_money = send_money
		self.append_line = append_line
		self.tools = [send_money, append_line]


def _assistant_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")]


def _transcript_with_two_colliding_calls(call_id: Any = "c1") -> list[dict[str, Any]]:
	"""A stored transcript paused on an assistant turn whose two calls share one reference.

	Hand-built as the doctype stores it — plain dicts, not `ToolCall`s — because this is the shape
	a resume reads back, and it is the one input a site could already be holding.
	"""
	call = {
		"id": call_id,
		"type": "function",
		"function": {"name": "send_money", "arguments": '{"to": "alice", "amount": 500}'},
	}
	return [
		{"role": "user", "content": "pay alice"},
		{"role": "assistant", "content": None, "tool_calls": [dict(call), dict(call)]},
	]


class TestAColl1dingTurnIsRefused(UnitTestCase):
	"""AT1, AT1b, AT2, AT3 — the forward path, gated and ungated, streamed and not."""

	def test_a_colliding_gated_batch_raises_before_any_tool_runs(self):
		"""AT1. Two gated calls sharing `c1`.

		`recorder.ran == []` is ALREADY true here before this change, because a gated batch
		pauses rather than executing — so that assertion is not what discriminates. The raise is.
		The execution is watched in the test below, on an ungated pair.
		"""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("send_money", {"to": "alice", "amount": 500}, "c1"),
					("send_money", {"to": "alice", "amount": 500}, "c1"),
				)
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("pay alice")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_colliding_ungated_batch_raises_and_neither_call_runs(self):
		"""AT1b. The test that watches the defect on the path being fixed.

		Two calls to an UNGATED tool, sharing `c1`. Nobody is asked anything on this path, so
		before this change the tool simply ran twice. Delete the refusal and `recorder.ran` holds
		two entries — that is the defect, reproduced forward, not merely a pause that failed to
		happen.
		"""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("append_line", {"text": "x"}, "c1"),
					("append_line", {"text": "x"}, "c1"),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("append x twice")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def _colliding_agent(self):
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("append_line", {"text": "x"}, "c1"),
					("append_line", {"text": "x"}, "c1"),
				)
			]
		)
		return recorder, Agent(model=model, tools=recorder.tools)

	def test_the_colliding_turn_never_enters_the_transcript(self):
		"""AT2. The refusal happens while the message is being BUILT, not after it is appended,
		so nothing downstream can ever see it.

		Driven through `_loop` on purpose. `run` hands the loop a COPY of a caller's list
		(`_build_initial_messages` returns `list(input)`), so asserting on the list passed to
		`run` would observe a list the loop never touched and would stay green even if the
		message were appended — which is exactly what happened when the mutation for this test
		was first run. The transcript the loop actually builds is the one that has to be checked.
		"""
		recorder, agent = self._colliding_agent()
		messages = [{"role": "user", "content": "append x twice"}]

		with self.assertRaises(ValueError):
			agent._loop(messages)

		self.assertEqual(_assistant_turns(messages), [])
		self.assertEqual(messages, [{"role": "user", "content": "append x twice"}])
		self.assertEqual(recorder.ran, [])

	def test_the_colliding_turn_never_enters_the_streamed_transcript_either(self):
		"""AT2b. The same claim on the streamed loop, which builds its transcript separately."""
		recorder, agent = self._colliding_agent()
		messages = [{"role": "user", "content": "append x twice"}]

		with self.assertRaises(ValueError):
			for _event in agent._loop_stream(messages):
				pass

		self.assertEqual(_assistant_turns(messages), [])
		self.assertEqual(recorder.ran, [])

	def test_it_raises_identically_in_the_streamed_loop(self):
		"""AT3. One check covers both loops, so the streamed path must refuse with the same
		literal — not merely raise something."""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("append_line", {"text": "x"}, "c1"),
					("append_line", {"text": "x"}, "c1"),
				)
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			for _event in agent.run("append x twice", stream=True):
				pass

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])


class TestTwoCallsWithNoUsableReference(UnitTestCase):
	"""AT10, AT10b, AT10c — the shapes a provider actually produces, and their controls."""

	def _refused(self, call_id: Any):
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("append_line", {"text": "x"}, call_id),
					("append_line", {"text": "y"}, call_id),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=recorder.tools)
		with self.assertRaises(ValueError) as caught:
			agent.run("append twice")
		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_two_calls_with_no_id_are_refused_like_any_other_collision(self):
		"""AT10. `None` from a provider that sends a null, `""` from one that omits the field or
		never streams it. Both become the same question key, the same answer lookup and the same
		membership test — which IS the defect. Skipping them rather than folding them into one
		bucket would leave the likelier half of it live."""
		for call_id in (None, ""):
			with self.subTest(id=call_id):
				self._refused(call_id)

	def test_a_single_call_with_no_id_is_refused_as_well(self):
		"""AT10b, INVERTED in run 11b by the owner's decision, and renamed to say what it now
		pins. It read: "ONE call with no reference is answerable — there is nothing to confuse it
		with — so it behaves exactly as it did."

		That was right about confusion and wrong about cost. A reference is not only how an answer
		is matched, it is how a result is FILED: the loops write `tool_call_id=call.id`, and a tool
		message with no reference is one the structural check has always rejected. So waving a
		single one through wrote a message into the stored transcript that made every later turn in
		that conversation raise — the conversation was over, recoverable only by deleting the
		stored row. The refusal is not a collision rule here; it is the same rule one door along:
		a reply nobody can answer or file is refused before it is stored.

		The control this test used to be is not lost — see
		`TestAReplyWithNoUsableReferenceIsRefusedBeforeItIsStored.test_the_control_a_usable_
		reference_still_runs`, and AT10c below, which both pin that usable references still run.

		The sentence is its OWN, and that is the second half of what this pins. One call collides
		with nothing: telling a person "two actions could not be told apart, so one approval would
		have answered both" when there was one action and — the tool here is ungated — no approval
		at all is a false sentence, the very defect class the other run-11b fixes remove.
		"""
		recorder = _Recorder()
		model = FakeModel([_calls(("append_line", {"text": "x"}, None)), _final("done")])
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("append once")

		self.assertEqual(str(caught.exception), _UNFILEABLE_CALL)
		self.assertEqual(recorder.ran, [])

	def test_ids_differing_only_by_case_or_whitespace_are_two_answerable_calls(self):
		"""AT10c. Nothing downstream normalises a reference — membership, the answer lookup and
		the question key all compare raw — so neither may this. `.strip().lower()` here would
		refuse two calls a person could genuinely answer apart."""
		for first, second in (("c1", "C1"), ("c1", "c1 ")):
			with self.subTest(ids=(first, second)):
				recorder = _Recorder()
				model = FakeModel(
					[
						_calls(
							("append_line", {"text": "x"}, first),
							("append_line", {"text": "y"}, second),
						),
						_final("done"),
					]
				)
				agent = Agent(model=model, tools=recorder.tools)

				result = agent.run("append twice")

				self.assertEqual(result.output, "done")
				self.assertEqual(
					recorder.ran,
					[("append_line", {"text": "x"}), ("append_line", {"text": "y"})],
				)


class TestDistinguishableTurnsAreUntouched(UnitTestCase):
	"""AT4, AT5 — the positive controls. Without these, every refusal above could be passing
	because the engine refuses everything."""

	def test_two_distinct_ids_still_both_execute(self):
		"""AT4."""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("append_line", {"text": "x"}, "c1"),
					("append_line", {"text": "y"}, "c2"),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		result = agent.run("append twice")

		self.assertEqual(result.output, "done")
		self.assertEqual(recorder.ran, [("append_line", {"text": "x"}), ("append_line", {"text": "y"})])
		self.assertEqual(
			[m["tool_call_id"] for m in result.messages if m.get("role") == "tool"], ["c1", "c2"]
		)

	def test_a_single_ungated_call_is_untouched(self):
		"""AT5, first half."""
		recorder = _Recorder()
		model = FakeModel([_calls(("append_line", {"text": "x"}, "c1")), _final("done")])
		agent = Agent(model=model, tools=recorder.tools)

		result = agent.run("append x")

		self.assertEqual(result.output, "done")
		self.assertEqual(recorder.ran, [("append_line", {"text": "x"})])

	def test_a_single_gated_call_still_pauses_with_one_question(self):
		"""AT5, second half. The options are the whole approval contract and must not move."""
		recorder = _Recorder()
		model = FakeModel([_calls(("send_money", {"to": "alice", "amount": 500}, "c1"))])
		agent = Agent(model=model, tools=recorder.tools)

		result = agent.run("pay alice")

		self.assertTrue(result.paused)
		self.assertEqual([q.key for q in result.questions], ["c1"])
		self.assertEqual(result.questions[0].options, ["Approve", "Deny"])
		self.assertEqual(recorder.ran, [])


class TestAStoredTranscriptCannotBeResumed(UnitTestCase):
	"""AT6, AT7 — the resume path. This is the half that protects a site already holding one."""

	def test_a_stored_colliding_transcript_cannot_be_resumed(self):
		"""AT6. The defect, reproduced on the resume path.

		The fake model carries a following final turn ON PURPOSE: without it, deleting the
		refusal would make this test red because the script ran out, which is the wrong reason.
		With it, deleting the refusal lets the resume run to completion and the tool executes
		twice on one "Approve".

		Honest about what this test itself sees: it goes red on `assertRaises`, BEFORE
		`recorder.ran` is evaluated, so the two executions are not what this assertion reports.
		They were observed separately, on the unwired engine, and are recorded in the run log;
		`test_a_stored_colliding_transcript_double_executes_without_the_guard` below is the one
		that asserts the count.
		"""
		recorder = _Recorder()
		model = FakeModel([_final("paid")])
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_stored_transcript_with_no_usable_reference_cannot_be_resumed_either(self):
		"""AT6b. The same on the shape a provider is likelier to produce."""
		for call_id in (None, ""):
			with self.subTest(id=call_id):
				recorder = _Recorder()
				agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)
				with self.assertRaises(ValueError) as caught:
					agent.resume(_transcript_with_two_colliding_calls(call_id), {call_id: "Approve"})
				self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
				self.assertEqual(recorder.ran, [])

	def test_the_same_history_handed_to_run_is_read_but_still_cannot_execute(self):
		"""AT6c, narrowed by the owner in run 10 (R7), and made into the sharper pair.

		The third way in — history handed to `run` — is no longer refused at the door, because
		refusing it prevented no double write and killed the conversation instead (see
		`TestReplayedHistoryIsNotRefused`). What AT6c was really protecting is asserted here
		directly and on the identical input: reading that history executes NOTHING, and resuming
		it — the one path that can reach the tool from those stored calls — is still refused.
		"""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()

		read_only = Agent(model=FakeModel([_final("sure")]), tools=recorder.tools)
		self.assertEqual(read_only.run(list(history)).output, "sure")
		self.assertEqual(recorder.ran, [])

		resuming = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)
		with self.assertRaises(ValueError) as caught:
			resuming.resume(list(history), {"c1": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_stored_transcript_with_distinct_ids_still_resumes(self):
		"""AT7. The control for AT6, and the proof that `resume_run`'s answer contract has not
		moved: the same `{key: answer}` map, resolved exactly as it was."""
		recorder = _Recorder()
		call = {
			"id": "c1",
			"type": "function",
			"function": {"name": "send_money", "arguments": '{"to": "alice", "amount": 500}'},
		}
		second = {
			"id": "c2",
			"type": "function",
			"function": {"name": "send_money", "arguments": '{"to": "bob", "amount": 10}'},
		}
		messages = [
			{"role": "user", "content": "pay alice and bob"},
			{"role": "assistant", "content": None, "tool_calls": [call, second]},
		]
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		result = agent.resume(messages, {"c1": "Approve", "c2": "Deny"})

		# A Deny anywhere in the group stops the group — S14's contract, unchanged by S17.
		self.assertEqual(recorder.ran, [])
		results = {m["tool_call_id"] for m in result.messages if m.get("role") == "tool"}
		self.assertEqual(results, {"c1", "c2"})


class TestTheRefusalIsFitToBeRead(UnitTestCase):
	"""AT9 — it reaches a person on every path, so it is checked as person-facing text."""

	def test_the_refusal_names_no_platform_vendor_or_model(self):
		"""Both the forward refusal and the resume refusal, which are one literal."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_final("x")]), tools=recorder.tools)

		raised = []
		model = FakeModel(
			[_calls(("append_line", {"text": "x"}, "c1"), ("append_line", {"text": "x"}, "c1"))]
		)
		forward = Agent(model=model, tools=recorder.tools)
		with self.assertRaises(ValueError) as caught:
			forward.run("go")
		raised.append(str(caught.exception))
		with self.assertRaises(ValueError) as caught:
			agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"})
		raised.append(str(caught.exception))

		self.assertEqual(len(set(raised)), 1)  # one literal, so neither path can drift
		for text in raised:
			for word in FORBIDDEN:
				with self.subTest(word=word):
					self.assertNotIn(word, text.lower())

		# The control, IN THE IDENTICAL FORM: the same loop, over the same text with one forbidden
		# word planted into it, must report it. (The first draft asserted that a string built to
		# contain "frappe" contained it, which no mutation could redden and which never ran the
		# loop above at all.)
		planted = f"{raised[0]} Frappe".lower()
		caught_words = [word for word in FORBIDDEN if word in planted]
		self.assertEqual(caught_words, ["frappe"])

	def test_the_refusal_says_what_happened_and_that_nothing_was_done(self):
		"""A person reads this in the run's error field, or over the stream. It has to be a
		sentence, not a diagnostic."""
		self.assertIn("nothing was carried out", _UNANSWERABLE_TURN.lower())
		self.assertNotIn("tool_call", _UNANSWERABLE_TURN)
		self.assertNotIn("messages[", _UNANSWERABLE_TURN)

	def test_the_unfileable_refusal_is_held_to_the_same_two_rules(self):
		"""Run 11b's second literal reaches a person by the identical path — `mark_failed`, the
		run's error field, the stream — so it is checked identically. A literal that is only ever
		read by whoever wrote it is not what either of these rules is about."""
		for word in FORBIDDEN:
			with self.subTest(word=word):
				self.assertNotIn(word, _UNFILEABLE_CALL.lower())
		# the control, in the identical form: the same loop over the same text with one forbidden
		# word planted must report it, or the loop above proves nothing.
		planted = f"{_UNFILEABLE_CALL} Frappe".lower()
		self.assertEqual([word for word in FORBIDDEN if word in planted], ["frappe"])

		self.assertIn("nothing was carried out", _UNFILEABLE_CALL.lower())
		self.assertNotIn("tool_call", _UNFILEABLE_CALL)
		self.assertNotIn("messages[", _UNFILEABLE_CALL)


class TestTheCheckItself(UnitTestCase):
	"""The predicate, directly. Its return shape is part of the contract: a caller must never be
	able to decide on the truthiness of the value, because the empty reference is both a real
	collision and falsy."""

	def test_it_reports_a_collision_without_relying_on_truthiness(self):
		from flow.lib.agent import NO_CALL_REFERENCE, _indistinguishable_tool_call

		self.assertIsNone(_indistinguishable_tool_call(["c1", "c2"]))
		self.assertIsNone(_indistinguishable_tool_call([]))
		self.assertIsNone(_indistinguishable_tool_call(["c1"]))
		self.assertIsNone(_indistinguishable_tool_call([None]))
		self.assertEqual(_indistinguishable_tool_call(["c1", "c1"]), (True, "c1"))
		# Both no-reference shapes fold to ONE bucket, so they collide with each other too.
		self.assertEqual(_indistinguishable_tool_call([None, ""]), (True, NO_CALL_REFERENCE))
		self.assertEqual(_indistinguishable_tool_call([None, None]), (True, NO_CALL_REFERENCE))
		self.assertEqual(_indistinguishable_tool_call(["", ""]), (True, NO_CALL_REFERENCE))

	def test_a_guard_written_on_truthiness_would_be_wrong(self):
		"""The reason the return is a tuple. `bool((True, ""))` is True but `bool("")` is not:
		had the predicate returned the bare reference, `if collided:` would have waved the
		empty-reference collision — the likeliest one — straight through."""
		from flow.lib.agent import _indistinguishable_tool_call

		collided = _indistinguishable_tool_call([None, None])
		self.assertIsNotNone(collided)
		self.assertTrue(collided)
		self.assertFalse(collided[1] == "")  # it is the sentinel, never the raw empty string

	def test_it_reads_a_generator_once_and_does_not_need_a_sequence(self):
		"""Both call sites pass a generator expression."""
		from flow.lib.agent import _indistinguishable_tool_call

		self.assertEqual(_indistinguishable_tool_call(i for i in ["a", "a"]), (True, "a"))
		self.assertIsNone(_indistinguishable_tool_call(i for i in ["a", "b"]))


class TestNothingElseMoved(UnitTestCase):
	"""What it must not change."""

	def test_the_four_reviewed_functions_were_not_touched(self):
		"""A CONSTRAINT CHECK, not an acceptance test of S17: it is green before and after this
		change and no edit S17 makes can move it. `test_deny_stops_batch` owns the same pin with
		its own control; this restates it so the constraint is visible in S17's own file."""
		from flow.tests.test_deny_stops_batch import TestTheLoadBearingFunctionsAreUntouched as Pin

		pin = Pin("test_the_four_functions_are_byte_identical_to_their_reviewed_form")
		found = pin._digests(pin._engine_source())

		self.assertEqual(sorted(found), sorted(Pin.BASELINE_DIGESTS))
		for name, digest in Pin.BASELINE_DIGESTS.items():
			self.assertEqual(found[name], digest, f"{name} changed; rule 4 requires a spec naming it")

	def test_the_check_reads_nothing_but_the_calls_it_was_given(self):
		"""It must not reach the database, the session or anything else: it runs before the turn
		is admitted, on input a model controls."""
		import frappe

		recorder = _Recorder()
		model = FakeModel(
			[_calls(("append_line", {"text": "x"}, "c1"), ("append_line", {"text": "x"}, "c1"))]
		)
		agent = Agent(model=model, tools=recorder.tools)

		def explode(*args, **kwargs):
			raise AssertionError("the refusal path read the database")

		with patch.object(frappe, "get_all", explode), patch.object(frappe, "get_doc", explode):
			with self.assertRaises(ValueError) as caught:
				agent.run("go")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)


class TestTheStreamedRefusalIsHonest(UnitTestCase):
	"""R1a, pinned rather than left as prose: the streamed loop announces each call before the
	turn is admitted, so a client draws both cards and then gets the error. Nothing executes and
	nothing persists, so this is cosmetic — but it is real, and a client has to clear them."""

	def test_the_stream_announces_both_calls_before_it_refuses(self):
		recorder = _Recorder()
		model = FakeModel(
			[_calls(("append_line", {"text": "x"}, "c1"), ("append_line", {"text": "x"}, "c1"))]
		)
		agent = Agent(model=model, tools=recorder.tools)

		seen = []
		with self.assertRaises(ValueError):
			for event in agent.run("go", stream=True):
				seen.append(event)

		started = [e for e in seen if isinstance(e, ToolStarted)]
		self.assertEqual([(e.id, e.name) for e in started], [("c1", "append_line")] * 2)
		self.assertFalse([e for e in seen if isinstance(e, ToolEnded)])  # neither ever finished
		self.assertFalse(any(isinstance(e, Done) for e in seen))
		self.assertEqual(recorder.ran, [])


class TestTheAnswerContractDidNotMove(UnitTestCase):
	"""Criterion 13, asserted rather than argued.

	The only thing a web app has to get right about an approval is that a question carries a `key`
	and that posting `{key: answer}` resolves exactly that call. S17 refuses some turns earlier
	than before; it must not have moved anything about the turns that still pause.
	"""

	def test_a_pause_still_carries_one_key_per_call_and_the_same_two_options(self):
		from flow.lib.agent import CONFIRM_ANSWER_OPTIONS

		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("send_money", {"to": "alice", "amount": 500}, "c1"),
					("send_money", {"to": "bob", "amount": 10}, "c2"),
				)
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		result = agent.run("pay alice and bob")

		self.assertTrue(result.paused)
		self.assertEqual([q.key for q in result.questions], ["c1", "c2"])
		self.assertEqual(CONFIRM_ANSWER_OPTIONS, ("Approve", "Deny"))
		for question in result.questions:
			self.assertEqual(question.options, ["Approve", "Deny"])
			self.assertTrue(question.allow_other)
		self.assertEqual(recorder.ran, [])

	def test_posting_that_key_back_resolves_exactly_that_call(self):
		"""The whole wire contract in one assertion: the key the client was given is the key the
		engine looks the answer up by, and only the approved call runs."""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("send_money", {"to": "alice", "amount": 500}, "c1"),
					("send_money", {"to": "bob", "amount": 10}, "c2"),
				)
			]
		)
		agent = Agent(model=model, tools=recorder.tools)
		paused = agent.run("pay alice and bob")

		fresh = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)
		resumed = fresh.resume(
			[dict(m) for m in paused.messages],
			{q.key: ("Approve" if q.key == "c1" else "no, hold off") for q in paused.questions},
		)

		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])
		self.assertEqual(
			{m["tool_call_id"] for m in resumed.messages if m.get("role") == "tool"}, {"c1", "c2"}
		)


class TestTheEdgeOfTheFoldIsDeliberate(UnitTestCase):
	"""What the "not a non-empty string" fold costs, pinned so the cost is a decision.

	The rule folds every reference that is not a non-empty `str` into one bucket. For `None` and
	`""` that is the whole point — they are the shapes a provider actually produces and they really
	are indistinguishable downstream. For two DISTINCT non-string references it is stricter than the
	defect requires: two calls carrying `1` and `2` would be told apart perfectly well by a set of
	ids, by `answers.get(...)` and as question keys, and they are refused anyway.

	That is fail-closed by choice, not by accident, and it is pinned here so a later reader sees a
	decision rather than an oversight. Note `True`/`1` genuinely DO collide downstream (they are
	equal and hash alike), so folding those is correct on the merits.
	"""

	def test_two_distinct_non_string_references_are_refused_although_answerable(self):
		from flow.lib.agent import NO_CALL_REFERENCE, _indistinguishable_tool_call

		self.assertEqual(_indistinguishable_tool_call([1, 2]), (True, NO_CALL_REFERENCE))
		# the control: as strings, the same two references are two answerable calls
		self.assertIsNone(_indistinguishable_tool_call(["1", "2"]))

	def test_an_integer_beside_a_string_is_not_folded_into_it(self):
		"""The fold must not make a usable reference collide with an unusable one."""
		from flow.lib.agent import _indistinguishable_tool_call

		self.assertIsNone(_indistinguishable_tool_call([1, "1"]))
		self.assertIsNone(_indistinguishable_tool_call([None, "c1"]))

	def test_three_calls_where_only_two_collide_are_refused(self):
		"""The rule is per turn, not per adjacent pair."""
		from flow.lib.agent import _indistinguishable_tool_call

		self.assertEqual(_indistinguishable_tool_call(["c1", "c2", "c1"]), (True, "c1"))
		self.assertIsNone(_indistinguishable_tool_call(["c1", "c2", "c3"]))

	def test_a_whitespace_only_reference_is_a_reference(self):
		"""It is a non-empty string, so it is compared as one — consistent with taking ids
		exactly, and with the control that nothing strips them."""
		from flow.lib.agent import _indistinguishable_tool_call

		self.assertEqual(_indistinguishable_tool_call(["  ", "  "]), (True, "  "))
		self.assertIsNone(_indistinguishable_tool_call(["  ", ""]))


class TestThePathsTheFirstDraftDidNotReach(UnitTestCase):
	"""Four shapes the acceptance table does not name, each of which could have been a hole."""

	def test_a_streamed_resume_refuses_too(self):
		"""`_resume_stream` is a GENERATOR, so `resume(..., stream=True)` returns without running
		anything — the refusal only happens on the first `next()`. A caller that builds the
		generator and never drains it would see no error at all, so the draining is the test."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		stream = agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"}, stream=True)

		with self.assertRaises(ValueError) as caught:
			for _event in stream:
				pass

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_auto_approve_does_not_get_past_it(self):
		"""The one flag that turns every approval gate off must not also turn this off — the
		refusal is not a gate, it is a malformed reply. It sits before `_invoke`, which is where
		`auto_approve` is read, so the flag never comes into it."""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(
					("send_money", {"to": "alice", "amount": 500}, "c1"),
					("send_money", {"to": "alice", "amount": 500}, "c1"),
				),
				_final("done"),
			]
		)
		agent = Agent(model=model, tools=recorder.tools, auto_approve=True)

		with self.assertRaises(ValueError) as caught:
			agent.run("pay alice")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_colliding_second_turn_is_refused_after_a_clean_first_one(self):
		"""The rule is per assistant turn, and a run does not become immune by starting well.
		The first turn executes; the second is refused and the first turn's work stands."""
		recorder = _Recorder()
		model = FakeModel(
			[
				_calls(("append_line", {"text": "first"}, "a1")),
				_calls(
					("append_line", {"text": "x"}, "b1"),
					("append_line", {"text": "y"}, "b1"),
				),
			]
		)
		agent = Agent(model=model, tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("go twice")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [("append_line", {"text": "first"})])

	def test_a_colliding_turn_that_already_has_one_result_is_still_refused(self):
		"""The nastiest stored shape: one of the two already ran, so a rule that only looked at
		PENDING calls would see a single call and wave it through — and the answer would then
		resolve the one that had already executed. The check is over the assistant turn as
		written, never over what is still pending, which is what closes this."""
		recorder = _Recorder()
		messages = _transcript_with_two_colliding_calls()
		messages.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(messages, {"c1": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])


class TestTheGuardIsWhatStopsTheDoubleExecution(UnitTestCase):
	"""The count, asserted — not inferred from a raise.

	Every other test here observes the refusal, which means it stops at `assertRaises` and never
	evaluates the recorder. This one removes the guard from the engine's own predicate for the
	duration of one call and counts what happens without it, so the number this whole spec exists
	to change is written down in a test rather than only in a run log.
	"""

	def _resume_with_the_guard_disabled(self, recorder):
		"""`_indistinguishable_tool_call` forced to find nothing: the engine as it was."""
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)
		with patch.object(agent_module, "_indistinguishable_tool_call", lambda ids: None):
			return agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"})

	def test_a_stored_colliding_transcript_double_executes_without_the_guard(self):
		recorder = _Recorder()

		result = self._resume_with_the_guard_disabled(recorder)

		# ONE approval, TWO transfers. This is the defect, in a number.
		self.assertEqual(
			recorder.ran,
			[("send_money", {"to": "alice", "amount": 500})] * 2,
		)
		self.assertEqual(result.output, "paid")

	def test_and_with_the_guard_the_same_input_executes_nothing(self):
		"""The control, on the identical input. Together these two are the before and after."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])


class TestReplayedHistoryIsNotRefused(UnitTestCase):
	"""R7, narrowed by the owner in run 10: the refusal guards where a tool can be reached.

	Until run 10 the check lived in `_validate_messages`, which is reached from
	`_build_initial_messages` as well as from `_prepare_resume`. A conversation is replayed
	through the first on EVERY later message, so one indistinguishable turn anywhere in a stored
	transcript refused not just the resume but every future turn of that conversation, forever,
	with no user-reachable recovery.

	That half bought no execution safety at all: on the `run(list)` path `_loop` only ever invokes
	calls from the CURRENT reply, never from history — `_pending_calls`/`_prepare_resume` are not
	on that path. It only turned a survivable session into a dead one.

	So the refusal now fires on the two paths where execution actually happens — the model's NEW
	reply (`_assistant_message`) and a resume (`_prepare_resume`) — and replayed history is read
	as the record of what already happened. `TestTheGuaranteeSurvivesTheNarrowing` is the other
	half of this decision and must be read with it.

	This is the test that the run 9 build named as the one to change if the owner narrowed the
	rule. The owner narrowed it (run 10, R7).
	"""

	def test_a_stored_colliding_turn_no_longer_refuses_every_later_turn(self):
		"""The bricking scenario, at the agent level: a history nothing can execute from."""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		history.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		history.append({"role": "assistant", "content": "done"})
		history.append({"role": "user", "content": "now something completely unrelated"})
		agent = Agent(model=FakeModel([_final("sure")]), tools=recorder.tools)

		result = agent.run(history)

		self.assertEqual(result.output, "sure")
		# Replay executes nothing — that is the whole reason this path may be read.
		self.assertEqual(recorder.ran, [])
		# The poisoned turn is replayed to the model verbatim, not dropped or rewritten.
		replayed = _assistant_turns(agent.model.calls[0]["messages"])
		self.assertEqual([tc["id"] for tc in replayed[0]["tool_calls"]], ["c1", "c1"])

	def test_a_pending_colliding_turn_in_history_is_also_replayed(self):
		"""The harder half: the calls have NO results, so this is the shape the resume refuses.

		Replay still invokes nothing, so reading it is safe; a resume of the same transcript is
		refused, and `TestTheGuaranteeSurvivesTheNarrowing` asserts exactly that on this input.
		"""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		agent = Agent(model=FakeModel([_final("sure")]), tools=recorder.tools)

		self.assertEqual(agent.run(history).output, "sure")
		self.assertEqual(recorder.ran, [])

	def test_an_ordinary_history_is_of_course_unaffected(self):
		"""The replay path reads an ordinary history unchanged.

		Not a control for the refusal any more, and it says so: `run(list)` no longer runs that
		check at all, so no mutation of it can redden this. The live control on the path that
		still checks is `test_a_stored_transcript_with_distinct_ids_still_resumes`.
		"""
		recorder = _Recorder()
		history = [
			{"role": "user", "content": "append x"},
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "a1",
						"type": "function",
						"function": {"name": "append_line", "arguments": '{"text": "x"}'},
					}
				],
			},
			{"role": "tool", "tool_call_id": "a1", "content": "appended x"},
			{"role": "user", "content": "thanks"},
		]
		agent = Agent(model=FakeModel([_final("sure")]), tools=recorder.tools)

		self.assertEqual(agent.run(history).output, "sure")

	def test_a_tool_calls_entry_the_check_cannot_read_is_folded_not_skipped(self):
		"""`_transcript_calls` iterates any sequence and subscripts `tc["id"]`, so a shape the
		check SKIPS but it still consumes is the same hole v1 had with `None`. Folded instead."""
		from flow.lib.agent import _validate_messages

		call = {
			"id": "c1",
			"type": "function",
			"function": {"name": "send_money", "arguments": "{}"},
		}
		# a tuple, not a list — iterated downstream, formerly skipped by the check entirely
		with self.assertRaises(ValueError) as caught:
			_validate_messages(
				[{"role": "assistant", "content": None, "tool_calls": (dict(call), dict(call))}]
			)
		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)

		# two entries the check cannot read at all fold together rather than vanishing
		with self.assertRaises(ValueError):
			_validate_messages(
				[{"role": "assistant", "content": None, "tool_calls": ["not-a-dict", "nor-this"]}]
			)


class TestTheGuaranteeSurvivesTheNarrowing(UnitTestCase):
	"""The other half of R7. Narrowing where the check fires must not narrow WHAT it guarantees.

	Two actions in one reply that cannot be told apart still run nothing, on both paths that can
	reach a tool: the model's new reply, and a resume of a stored transcript. If either of these
	goes green-by-accident the narrowing has eaten the fix rather than scoped it.
	"""

	def test_a_new_reply_with_a_duplicate_reference_is_still_refused_and_runs_nothing(self):
		recorder = _Recorder()
		agent = Agent(
			model=FakeModel(
				[
					_calls(
						("send_money", {"to": "alice", "amount": 500}, "c1"),
						("send_money", {"to": "bob", "amount": 500}, "c1"),
					)
				]
			),
			tools=recorder.tools,
		)

		with self.assertRaises(ValueError) as caught:
			agent.run("pay them both")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_new_reply_with_no_usable_reference_is_still_refused_and_runs_nothing(self):
		"""The ungated, no-reference shape — the one a gateway that never streams ids produces,
		and the only one that executed twice with nobody asked anything."""
		recorder = _Recorder()
		agent = Agent(
			model=FakeModel(
				[
					_calls(
						("append_line", {"text": "one"}, ""),
						("append_line", {"text": "two"}, ""),
					)
				]
			),
			tools=recorder.tools,
		)

		with self.assertRaises(ValueError) as caught:
			agent.run("log both")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_resume_of_a_stored_colliding_turn_is_still_refused_and_runs_nothing(self):
		"""The same transcript `test_a_pending_colliding_turn_in_history_is_also_replayed` reads
		without complaint. Reading it is safe; resuming it is where the tool would run."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_streamed_resume_of_a_stored_colliding_turn_is_still_refused(self):
		"""A generator that is never drained raises nothing, so the drain is the assertion."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			list(agent.resume(_transcript_with_two_colliding_calls(), {"c1": "Approve"}, stream=True))

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])


class TestASessionWhoseHistoryIsPoisonedStaysUsable(IntegrationTestCase):
	"""R7 at the level it was reported: a real conversation, not a hand-built message list.

	`FlowSession.chat` rebuilds the prompt from the whole stored transcript on every message
	(`_build_prompt_messages` -> `run(list)`), and `_row_to_message` restores the stored
	`tool_calls` each time. Before the narrowing, one indistinguishable assistant turn stored in
	`Flow Session Message.tool_calls` made every later message raise, mark the run Failed and
	leave an orphan user message — forever, recoverable only by deleting the row.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def _poisoned_session(self):
		"""A session whose stored transcript holds a turn whose two calls share one reference."""
		recorder = _Recorder()
		agent = Agent(model=Model(model_id="openai/gpt-4o-mini"), name="Payer", tools=recorder.tools)
		with patch.object(Model, "chat", return_value=_final("hello")):
			run = agent.new_session().chat("hi")

		session = load_session(run.session, agent=agent)
		call = {
			"id": "c1",
			"type": "function",
			"function": {"name": "send_money", "arguments": '{"to": "alice", "amount": 500}'},
		}
		session.append_run_messages(
			[
				{"role": "assistant", "content": None, "tool_calls": [dict(call), dict(call)]},
				{"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"},
			],
			run.name,
		)
		return agent, recorder, load_session(run.session, agent=agent)

	def test_a_later_message_in_that_session_still_gets_an_answer(self):
		_agent, recorder, session = self._poisoned_session()

		with patch.object(Model, "chat", return_value=_final("sure")) as chat:
			run = session.chat("now something unrelated")

		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.output, "sure")
		self.assertEqual(recorder.ran, [])
		# The poisoned turn really was in the prompt this turn was built from — without this the
		# test could pass against a session that had quietly dropped it.
		replayed = _assistant_turns(
			chat.call_args.args[0] if chat.call_args.args else chat.call_args.kwargs["messages"]
		)
		self.assertEqual([tc["id"] for tc in replayed[0]["tool_calls"]], ["c1", "c1"])


class TestWhatIsStillRefusedOnTheApprovalPath(UnitTestCase):
	"""R10 — narrowed by the owner in run 11, after being pinned unchanged in run 10.

	R7 moved the refusal off the replay path, so a session whose history holds an
	indistinguishable turn can chat again. `_prepare_resume` still validated the WHOLE transcript,
	so a collision anywhere in that history — including one whose calls already have results and
	can therefore never execute — refused every later resume in that session, forever, recoverable
	only by someone who can delete the stored row. The person was shown a sentence that was false
	for their situation: nobody was about to approve the old turn.

	The owner's rule, the same one R7 settled: **validation refuses what is about to RUN, never old
	history.** A resume now checks the turn it is resolving and only that turn.

	Nothing is given away by it, and the sibling test below is the measurement: once either of a
	colliding pair has a result, `_transcript_calls` counts BOTH answered, so `_prepare_resume`
	never iterates them and nothing from such a turn can execute on resume. Refusing it bought
	nothing. The S17 guarantee is untouched — a resumed reply that itself cannot be told apart is
	still refused and still runs nothing, including when there is a bad turn behind it too.
	"""

	def test_a_resolved_collision_in_history_no_longer_refuses_a_later_approval(self):
		"""R10, the narrowing itself. The person is approving z9; c1 is history and can never
		execute again. Before run 11 this raised and the session could never approve anything."""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		history.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		history.append({"role": "assistant", "content": "done"})
		history.append({"role": "user", "content": "now pay bob"})
		history.append(
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "z9",
						"type": "function",
						"function": {"name": "send_money", "arguments": '{"to": "bob", "amount": 10}'},
					}
				],
			}
		)
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		resumed = agent.resume(history, {"z9": "Approve"})

		self.assertEqual(
			recorder.ran,
			[("send_money", {"to": "bob", "amount": 10})],
			"one bad turn in the past refused an approval that had nothing to do with it",
		)
		self.assertEqual(resumed.output, "paid")

	def test_an_abandoned_colliding_turn_does_not_refuse_a_later_approval_either(self):
		"""R10, the half the first narrowing missed. Found by the run 11 QA adversary.

		"Live" was "any call in this turn has no result". An ABANDONED pause is exactly that, for
		ever — Stop clears a run's questions but not its messages — so a legacy colliding turn
		left unanswered still refused every later approval in that session, which is the whole of
		the defect R10 exists to remove, one door further along.

		And refusing it buys nothing, for the same reason the resolved case bought nothing: since
		the abandoned-turn branch in `_prepare_resume`, a call from a turn nobody is resuming is
		closed out with nothing and can never execute. Liveness is positional now, like the count
		that decides what may run: the LAST turn with an unanswered call, plus any turn a person
		is actually answering.
		"""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()  # abandoned: no tool result, ever
		history.append({"role": "user", "content": "now pay bob"})
		history.append(
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "z9",
						"type": "function",
						"function": {"name": "send_money", "arguments": '{"to": "bob", "amount": 10}'},
					}
				],
			}
		)
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		resumed = agent.resume(history, {"z9": "Approve"})

		self.assertEqual(
			recorder.ran,
			[("send_money", {"to": "bob", "amount": 10})],
			"an abandoned turn refused an approval that had nothing to do with it",
		)
		self.assertEqual(resumed.output, "paid")

	def test_a_bad_turn_in_the_past_does_not_excuse_a_bad_turn_being_resumed(self):
		"""The S17 guarantee, under the narrowed rule. The history holds a RESOLVED collision and
		the turn being resumed holds a LIVE one: the live one is still refused and nothing runs.

		Without this, "check only the pending turn" could have been read as "check nothing when
		the history is already dirty".
		"""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		history.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		history.append({"role": "user", "content": "do it again"})
		history.extend(_transcript_with_two_colliding_calls("z9")[1:])
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(history, {"z9": "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_a_pending_turn_with_no_usable_reference_is_still_refused_behind_a_dirty_history(self):
		"""The likelier half of the same shape: two calls carrying no reference at all, in the
		turn being resumed, with a resolved collision behind them."""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		history.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		history.append({"role": "user", "content": "do it again"})
		history.extend(_transcript_with_two_colliding_calls(None)[1:])
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.resume(history, {None: "Approve"})

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_and_the_old_collision_could_not_have_executed_anyway(self):
		"""Why R10 is a cost with no matching benefit: once either of a colliding pair has a
		result, `_transcript_calls` counts BOTH answered, so a resume never iterates them."""
		recorder = _Recorder()
		history = _transcript_with_two_colliding_calls()
		history.append({"role": "tool", "tool_call_id": "c1", "content": "sent 500 to alice"})
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		self.assertEqual(agent._pending_calls(history), [])
		self.assertEqual([c.id for c in agent._answered_calls(history)], ["c1", "c1"])
		self.assertEqual(recorder.ran, [])


class TestAReplyWithNoUsableReferenceIsRefusedBeforeItIsStored(UnitTestCase):
	"""SEC-L4 / F7-3 — one call carrying no reference at all is as unanswerable as two.

	`_assistant_message` refused a REPEATED unusable reference and let a single one through, on
	the reasoning that one call cannot be confused with another. But a reference is not only how
	an answer is matched, it is how the tool's RESULT is attached: `_prepare_resume` writes
	`{"role": "tool", "tool_call_id": call.id, ...}`, and a tool message with no reference is one
	the structural check has always rejected. So a single empty reference did not misroute an
	approval — it wrote a message into the stored transcript that made every later turn in that
	conversation raise. The conversation was over, recoverable only by someone who could delete
	the stored row.

	The module already says this shape is real: `NO_CALL_REFERENCE` exists because a provider
	"omits the field or never streams it". So it is refused where every other unanswerable reply
	is refused — before the message is returned to be appended, and therefore before anything is
	invoked. Nothing is written, and the conversation carries on.
	"""

	def test_a_single_empty_reference_is_refused_and_nothing_runs(self):
		"""The exact sentence, asserted, because it is the sentence a person reads. `assertEqual`
		and not `assertIn`: the text is the contract here, not a substring of it."""
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_calls(("append_line", {"text": "one"}, ""))]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("append a line")

		self.assertEqual(str(caught.exception), _UNFILEABLE_CALL)
		self.assertEqual(recorder.ran, [])

	def test_a_single_null_reference_is_refused_too(self):
		recorder = _Recorder()
		agent = Agent(model=FakeModel([_calls(("append_line", {"text": "one"}, None))]), tools=recorder.tools)

		with self.assertRaises(ValueError) as caught:
			agent.run("append a line")

		self.assertEqual(str(caught.exception), _UNFILEABLE_CALL)
		self.assertEqual(recorder.ran, [])

	def test_the_two_refusals_cannot_be_conflated_again(self):
		"""One reply, two different things wrong with it, two different true sentences — and they
		are not the same string, so neither branch can quietly start raising the other's.

		A single unusable reference is not a collision and must not be described as one. Two calls
		that share a reference ARE a collision, and the collision sentence is the one that matters
		for them: it is the shape where one approval would have run two actions."""
		self.assertNotEqual(_UNFILEABLE_CALL, _UNANSWERABLE_TURN)
		self.assertNotIn("two", _UNFILEABLE_CALL.lower())
		self.assertNotIn("approval", _UNFILEABLE_CALL.lower())

	def test_a_duplicate_reference_is_still_refused(self):
		"""Unchanged by this: the rule gains a shape, it does not trade one for another. The
		sentence is unchanged too — for two calls sharing a reference, "one approval would have
		answered both" is exactly what is true, and it stays theirs."""
		recorder = _Recorder()
		agent = Agent(
			model=FakeModel(
				[_calls(("append_line", {"text": "one"}, "c1"), ("append_line", {"text": "two"}, "c1"))]
			),
			tools=recorder.tools,
		)

		with self.assertRaises(ValueError) as caught:
			agent.run("append two lines")

		self.assertEqual(str(caught.exception), _UNANSWERABLE_TURN)
		self.assertEqual(recorder.ran, [])

	def test_the_control_a_usable_reference_still_runs(self):
		"""Without this the three above are satisfied by refusing every reply there is."""
		recorder = _Recorder()
		agent = Agent(
			model=FakeModel([_calls(("append_line", {"text": "one"}, "c1")), _final("done")]),
			tools=recorder.tools,
		)

		result = agent.run("append a line")

		self.assertEqual(result.output, "done")
		self.assertEqual(recorder.ran, [("append_line", {"text": "one"})])


class TestASessionAlreadyBrickedByOneStaysUsable(IntegrationTestCase):
	"""The other half, and the one the refusal above cannot reach: transcripts that already hold
	such a message. Refusing the reply stops new ones; it does nothing for a conversation that has
	one stored already, and those are exactly the conversations this defect has ruined.

	The owner's rule, the same one settled for R7 and R10: **validation refuses what is about to
	RUN, never old history.** A stored tool result with no reference is not about to run anything
	— it is a record of something that already did — so replaying it must not end the
	conversation. Runs as Administrator deliberately: what is under test is whether a stored
	transcript can be replayed at all, and no permission rule is involved.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def _bricked_session(self):
		recorder = _Recorder()
		agent = Agent(model=Model(model_id="openai/gpt-4o-mini"), name="Payer", tools=recorder.tools)
		with patch.object(Model, "chat", return_value=_final("hello")):
			run = agent.new_session().chat("hi")

		session = load_session(run.session, agent=agent)
		session.append_run_messages(
			[
				{
					"role": "assistant",
					"content": None,
					"tool_calls": [
						{
							"id": "",
							"type": "function",
							"function": {"name": "append_line", "arguments": '{"text": "one"}'},
						}
					],
				},
				{"role": "tool", "tool_call_id": "", "content": "appended one"},
			],
			run.name,
		)
		return agent, recorder, load_session(run.session, agent=agent)

	def test_a_later_message_in_that_session_still_gets_an_answer(self):
		_agent, recorder, session = self._bricked_session()

		with patch.object(Model, "chat", return_value=_final("sure")) as chat:
			run = session.chat("now something unrelated")

		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.output, "sure")
		self.assertEqual(recorder.ran, [])
		# The unusable turn really was in the prompt this turn was built from — without this the
		# test could pass against a session that had quietly dropped it.
		replayed = chat.call_args.args[0] if chat.call_args.args else chat.call_args.kwargs["messages"]
		self.assertIn(
			("tool", ""),
			[(m.get("role"), m.get("tool_call_id")) for m in replayed if m.get("role") == "tool"],
		)


class TestTheUnusableResultRuleAndBothOfItsOptOuts(UnitTestCase):
	"""`_validate_messages`' unusable-RESULT rule, and the two call sites that switch it off.

	The rule refuses a tool message whose `tool_call_id` is present but carries no usable
	reference. Both callers that replay stored history pass `refuse_unusable_tool_results=False`,
	on the rule R7 and R10 settled: **validation refuses what is about to RUN, never old history.**
	A tool result with no reference is a record of something that already happened, so refusing it
	ends a conversation and prevents nothing; the reply that would CREATE one is refused in
	`_assistant_message` instead, before it is stored.

	Everything in that paragraph was true of the code and pinned by almost nothing. The default was
	reachable from no call site and asserted by no test, so the branch could be deleted with the
	suite still green; and of the two opt-outs only `_build_initial_messages`' was covered, by one
	integration test — deleting `_prepare_resume`'s re-bricked every PAUSED conversation that
	already holds such a message, silently, with nothing going red. One test each, here.
	"""

	def _bricked_history(self) -> list[dict[str, Any]]:
		"""A stored transcript holding the message this whole rule is about: a tool result filed
		under an empty reference, written before run 11b refused the reply that creates one."""
		return [
			{"role": "user", "content": "log one"},
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "",
						"type": "function",
						"function": {"name": "append_line", "arguments": '{"text": "one"}'},
					}
				],
			},
			{"role": "tool", "tool_call_id": "", "content": "appended one"},
		]

	def test_the_default_refuses_an_unusable_result_and_the_replay_flag_is_what_allows_it(self):
		"""The `True` default, directly — the only thing that can reach it, since both call sites
		opt out. Without this the branch is deletable with the whole suite still green, which is a
		gate whose failure mode has never been observed."""
		from flow.lib.agent import _validate_messages

		bad = [{"role": "tool", "tool_call_id": "", "content": "appended one"}]

		with self.assertRaises(ValueError) as caught:
			_validate_messages(bad)
		self.assertIn("no usable tool_call_id", str(caught.exception))

		# and the opt-out the two replay paths pass is what lets the same message through
		_validate_messages(bad, refuse_unusable_tool_results=False)

		# the control: the FIELD missing altogether is malformed rather than historical, and is
		# refused on every path, opt-out or not — so the two are not one lenient rule.
		with self.assertRaises(ValueError):
			_validate_messages([{"role": "tool", "content": "x"}], refuse_unusable_tool_results=False)

	def test_the_replay_opt_out_on_the_run_path_keeps_such_a_transcript_readable(self):
		"""`_build_initial_messages`. Red if its `refuse_unusable_tool_results=False` is removed:
		every later turn of a conversation holding one such message raises again, which is the
		defect fbccf45 was for. Pinned at the unit level as well as by
		`TestASessionAlreadyBrickedByOneStaysUsable`, which needs a site and a stored session."""
		recorder = _Recorder()
		history = self._bricked_history()
		history.append({"role": "user", "content": "now something unrelated"})
		agent = Agent(model=FakeModel([_final("sure")]), tools=recorder.tools)

		result = agent.run(history)

		self.assertEqual(result.output, "sure")
		self.assertEqual(recorder.ran, [])
		# the unusable message was replayed, not quietly dropped — without this the test would
		# pass against a path that had simply discarded it.
		self.assertIn(("tool", ""), [(m.get("role"), m.get("tool_call_id")) for m in result.messages])

	def test_the_replay_opt_out_on_the_resume_path_keeps_a_paused_conversation_answerable(self):
		"""`_prepare_resume`. The half nothing pinned: a conversation that was bricked while
		PAUSED on an approval. With the opt-out the person answers and the tool runs; remove it
		and the resume raises before any of that, so the approval can never be given.

		Red if `refuse_unusable_tool_results=False` is removed from `_prepare_resume` — and only
		that, which is why the pending call here carries a perfectly usable reference."""
		recorder = _Recorder()
		history = self._bricked_history()
		history.append(
			{
				"role": "assistant",
				"content": None,
				"tool_calls": [
					{
						"id": "c1",
						"type": "function",
						"function": {
							"name": "send_money",
							"arguments": '{"to": "alice", "amount": 500}',
						},
					}
				],
			}
		)
		agent = Agent(model=FakeModel([_final("paid")]), tools=recorder.tools)

		result = agent.resume(history, {"c1": "Approve"})

		self.assertEqual(result.output, "paid")
		self.assertEqual(recorder.ran, [("send_money", {"to": "alice", "amount": 500})])
		self.assertIn(("tool", ""), [(m.get("role"), m.get("tool_call_id")) for m in result.messages])

	def test_a_reference_that_is_not_a_string_folds_the_same_way_on_both_paths(self):
		"""L1 — the structural check and `_assistant_message` read a reference through the SAME
		definition, so they cannot disagree about what counts as usable.

		`_call_reference` folds anything that is not a non-empty string to `NO_CALL_REFERENCE`,
		because that is what every lookup downstream does with it. The unusable-result check used
		to test `not message["tool_call_id"]` instead, which accepts a truthy non-string — `42`, a
		dict — while a REPLY carrying that same `42` is refused. The docstring claiming one
		definition fed both rules was the thing that was not true.

		**Which behaviour the code chose, and why it is safe.** Both, one per path, and the split
		is the same one the rule already makes:

		- by DEFAULT (a caller handing in a list to validate) `42` is now REFUSED, matching the
		  reply rule exactly. Safe because it can only tighten a path no shipped call site takes
		  and no provider reaches — `flow/lib/model.py` accumulates ids into a slot initialised to
		  `""` and defaults to `""`, so a reference from the model layer is always a `str`;
		- on the REPLAY paths it is folded and FILED — allowed through as history, like the empty
		  reference beside it. Safe because replayed history is read, never executed (`_loop`
		  invokes only the current reply's calls; `_prepare_resume` closes out every call outside
		  the live turn), and because refusing it would do the one thing this rule exists to avoid:
		  end a conversation over a record of something that already happened.
		"""
		from flow.lib.agent import _validate_messages

		for reference in (42, {"id": "c1"}, ["c1"]):
			with self.subTest(reference=reference):
				result = [{"role": "tool", "tool_call_id": reference, "content": "x"}]

				with self.assertRaises(ValueError) as caught:
					_validate_messages(result)
				self.assertIn("no usable tool_call_id", str(caught.exception))

				_validate_messages(result, refuse_unusable_tool_results=False)

		# the control: a usable reference is refused on neither path, so the fold has an edge.
		usable = [{"role": "tool", "tool_call_id": "c1", "content": "x"}]
		_validate_messages(usable)
		_validate_messages(usable, refuse_unusable_tool_results=False)
