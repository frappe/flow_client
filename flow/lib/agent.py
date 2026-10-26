# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import json
import math
import numbers
import re
import unicodedata
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from frappe import _

from flow.lib.model import ChatResponse, Model, ToolCall, ToolCallBegin
from flow.lib.tool import Tool

if TYPE_CHECKING:
	from flow.knowledge import Knowledge

DEFAULT_MAX_ITERATIONS = 20
ERROR_MESSAGE_LIMIT = 500
# An approval question is read by a person before they decide. Past this it stops being read —
# and a question nobody finishes reading is worse than a plain one, so an over-long sentence is
# abandoned rather than cut.
CONFIRM_BODY_LIMIT = 2000
# No single value may crowd out the sentence around it. A longer one is not shortened; the whole
# sentence is abandoned, because a value shown in part reads exactly like a value shown in full.
CONFIRM_VALUE_LIMIT = 200
# The entire grammar of an approval question: a name in braces, replaced by the argument of that
# name. There are no expressions, filters, attribute access, indexing, loops or conditionals, and
# no engine is involved — a general template engine stood here once and could read the database
# from inside a question nobody had answered yet. A question that can COMPUTE is a question someone
# can steer, and this one is read by a person about to authorise a write.
CONFIRM_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]{0,63})\}")
# Shown whole, or not at all. `None`, lists and objects are not; the arguments below the sentence
# show them properly.
CONFIRM_SCALAR_TYPES = (str, bool, int, float)
# Every approval question the engine raises carries exactly these options, in this order —
# `_confirmation_question` builds them and nothing else in the engine does. At resume they are how
# a question the person was asked to APPROVE is told apart from a question a tool asked itself.
CONFIRM_ANSWER_OPTIONS = ("Approve", "Deny")
# Said to the model when a pending call will not be acted on. Both are literals and neither carries
# the person's answer: recording that answer as the call's result is the defect these exist to
# stop, because the model then reads its own tool call as having returned the word a person typed.
NOT_EXECUTED_MESSAGES = {
	"unavailable": (
		"This action was not carried out and nothing was done. It is no longer available. "
		"Do not report it as done. Tell the user it did not happen."
	),
	"approval_no_longer_applies": (
		"This action was not carried out and nothing was done. What it requires changed while the "
		"question was open, so the answer that was given no longer applies to it. "
		"Do not report it as done. Ask again before doing it."
	),
	"unattended": (
		"This action was not carried out and nothing was done. It needs someone to approve it, and "
		"this run has nobody who can. Do not report it as done. Say it needs a person."
	),
	"group_refused": (
		"This action was not carried out and nothing was done. It was held back with the other "
		"actions in the same reply, and one of them was refused. "
		"Do not report it as done. Ask before doing it on its own."
	),
}
VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})


@dataclass
class Question:
	"""An LLM-authored prompt shown to the user when a run pauses.

	The same shape covers a free-text ask (empty `options`), a single- or
	multi-select. When `allow_other` is true the picker always offers an "Other"
	choice that opens a textbox for the user to reiterate or redirect.
	`key` routes the answer back (e.g. the tool_call_id it belongs to).
	"""

	prompt: str
	options: list[str] = field(default_factory=list)
	multi_select: bool = False
	allow_other: bool = True
	key: str | None = None


@dataclass
class RunResult:
	output: str | None
	messages: list[dict[str, Any]]
	tool_calls: list[ToolCall] = field(default_factory=list)
	iterations: int = 0
	usage: dict[str, int] = field(default_factory=dict)
	paused: bool = False
	questions: list[Question] = field(default_factory=list)


@dataclass
class TextChunk:
	"""A token delta from the model. Emitted as the LLM streams its reply."""

	text: str


@dataclass
class ToolStarted:
	"""A tool call is about to execute. Lets the UI render a 'thinking' indicator. Emitted as soon
	as the model starts streaming the call, so `arguments` may still be empty at that point — the
	full arguments arrive on the matching ToolEnded."""

	id: str
	name: str
	arguments: dict[str, Any]


@dataclass
class ToolEnded:
	"""A tool call finished. `result` is the JSON-serialized return value."""

	id: str
	name: str
	result: str


@dataclass
class Done:
	"""Terminal event: the run finished (Completed or Paused)."""

	result: RunResult


Event = TextChunk | ToolStarted | ToolEnded | Done


class Agent:
	def __init__(
		self,
		*,
		model: Model | str,
		name: str = "agent",
		instructions: str | None = None,
		tools: list[Tool] | None = None,
		knowledge: Knowledge | list[Knowledge] | None = None,
		max_iterations: int = DEFAULT_MAX_ITERATIONS,
		auto_approve: bool = False,
		unattended: bool = False,
	):
		if max_iterations < 1:
			raise ValueError("max_iterations must be at least 1")

		# A run with nobody in it: a trigger, a queued or background run, a run created with
		# approvals waived. Nobody can be asked anything, so a tool that requires asking is
		# refused rather than run or parked. Kept separate from `auto_approve` because a trigger
		# with that flag OFF has nobody in it too — it used to raise a question and wait forever.
		self.unattended = unattended
		self.auto_approve = auto_approve
		self.name = name
		self.model = Model(model) if isinstance(model, str) else model
		self.instructions = instructions
		self.tools = list(tools or [])
		if knowledge:
			from flow.tools.builtins import bind_search_knowledge

			items = knowledge if isinstance(knowledge, list) else [knowledge]
			self.tools.append(bind_search_knowledge([k.name for k in items]))
		self.max_iterations = max_iterations

		self._tools_by_name: dict[str, Tool] = {}
		for tool in self.tools:
			if tool.name in self._tools_by_name:
				raise ValueError(f"Duplicate tool name: {tool.name!r}")
			self._tools_by_name[tool.name] = tool

	def run(self, input: str | list[dict[str, Any]], *, stream: bool = False) -> RunResult | Generator[Event]:
		"""Run the agent on `input`. With `stream=True`, returns a generator of `Event`s
		(text deltas, tool start/end markers, and a final `Done` carrying the `RunResult`)."""
		messages = self._build_initial_messages(input)
		if stream:
			return self._loop_stream(messages)
		return self._loop(messages)

	def resume(
		self,
		messages: list[dict[str, Any]],
		answers: dict[str, Any],
		*,
		stream: bool = False,
		asked: list[Any] | None = None,
	) -> RunResult | Generator[Event]:
		"""Continue a run that paused on a question.

		`answers` maps each pending tool_call_id to the user's answer: "Approve" runs
		the tool, "Deny" records the rejection and stops the run, and any other free
		text is returned to the LLM as redirect feedback so it can adjust and retry.

		`asked` is the questions this pause raised, as they were recorded when it paused —
		`Question`s or the rows stored from them. The runtime resuming a run is not always the
		one that paused it, so what the person was asked cannot be re-derived from the tools
		present now; it is read from the record or not at all. Passing nothing is supported and
		safe: see `_prepare_resume`.
		"""
		# A resume exists because a person is answering, so it is attended by definition — and the
		# runtime that resumes is not always a fresh one. `flow/lib/session.py:78-79` hands back the
		# CALLER'S OWN object, and `FlowSession.chat` mutates this attribute on it every turn, so an
		# in-process caller that ran one unattended turn and then resumed carried `unattended=True`
		# into a run somebody was sitting in front of: their approval was honoured, and the model's
		# very next gated call in the same run was refused as having nobody to approve it.
		# Set here rather than in each caller, because every resume means the same thing.
		# `auto_approve` is deliberately left alone: it is a caller's standing instruction about the
		# whole run, not a statement about who is present, and upstream's callers rely on it.
		self.unattended = False
		if stream:
			return self._resume_stream(messages, answers, asked)
		messages, _ = self._prepare_resume(messages, answers, asked)
		if _has_denial(answers):
			return self._stopped_result(messages)
		return self._loop(messages, self._answered_calls(messages))

	def _resume_stream(
		self, messages: list[dict[str, Any]], answers: dict[str, Any], asked: list[Any] | None = None
	) -> Generator[Event]:
		"""Stream a resume: first replay the just-resolved tool results so the UI can fill in
		the tool cards that were awaiting an answer, then continue the agent loop (or stop
		if the user denied)."""
		messages, resolved = self._prepare_resume(messages, answers, asked)
		for call, content, announce in resolved:
			# A call held back for the group has no card: it was not announced when the run
			# paused, because it was not starting then. Here it is — with the arguments that ran,
			# so the card the client draws is the action, not an empty box.
			if announce:
				yield ToolStarted(id=call.id, name=call.name, arguments=call.arguments)
			yield ToolEnded(id=call.id, name=call.name, result=content)
		if _has_denial(answers):
			yield Done(result=self._stopped_result(messages))
			return
		yield from self._loop_stream(messages, self._answered_calls(messages))

	def _stopped_result(self, messages: list[dict[str, Any]]) -> RunResult:
		"""Terminal result for a run the user denied: pending calls are already resolved in
		`messages`, so end the turn here without another model call (no further tokens)."""
		return RunResult(
			output=None,
			messages=messages,
			tool_calls=self._answered_calls(messages),
			iterations=0,
		)

	def new_session(self, *, title: str | None = None) -> Any:
		"""Start a persisted conversation driven by this code agent (session's agent link is left empty)."""
		from flow.lib.session import new_session

		return new_session(self, title=title)

	def snapshot(self) -> dict[str, Any]:
		"""Config record stored on each Flow Run for traceability."""
		return {
			"title": self.name,
			"model": self.model.model_id,
			"instructions": self.instructions,
			"tools": [t.name for t in self.tools],
			"max_iterations": self.max_iterations,
		}

	def _prepare_resume(
		self, messages: list[dict[str, Any]], answers: dict[str, Any], asked: list[Any] | None = None
	) -> tuple[list[dict[str, Any]], list[tuple[ToolCall, str, bool]]]:
		"""Append a tool result for each pending call. Returns the new messages plus the
		(call, content, announce) triples a streaming resume may replay as events — one per call
		of the turn being resumed, and none for an earlier, abandoned turn, whose calls are
		resolved in `messages` but described to nobody: the client holds no part for them.
		`announce` is true for a call no question was ever raised for — one held back for
		the group. No card was drawn for it when the run paused, because it was not starting then;
		the client is told about it here, where it is, with the arguments that are about to run —
		and not at all when the answers hold a denial, because then it is not about to run either.

		A pause can hold several questions, and they are answered as one group. If any answer
		in the group is a denial, nothing in the group runs: an "Approve" beside it is recorded
		as approved and withheld rather than executed. Refusing one of several actions shown
		together is refusing all of them, not leaving the rest to go ahead.

		The denial is read from the same `_has_denial` the caller uses to halt the run, so the
		halt and the withholding can never disagree about what the answers said.

		The runtime that resumes a run is rebuilt from the record and is not always the one that
		paused it, so a pending call's tool may be gone, or may no longer be gated. Neither may be
		acted on and neither may be closed out with the person's own answer as the tool's result —
		a person who approved something and was told it was done, when nothing ran, has been
		misled by the engine rather than by anyone. Both fail closed, in that order:

		1. the tool is not here at all — nothing can honour the answer, whatever it said;
		2. the tool is here and gated — today's path, unchanged, group rule included;
		3. what the person was asked and what the tool now requires disagree in either direction —
		   the gate was turned off, or turned on, while the question was open — so the basis of
		   the answer is gone and it must be asked again rather than acted on;
		4. anything else — the tool asked its own question, and the answer is its result, as ever.

		Row 3 is symmetric, and deliberately so. A gate turned OFF while the question was open is
		an approval that no longer applies; a gate turned ON is a tool about to execute on an
		answer to a question nobody was asked to approve. The second of those EXECUTES if it is
		not caught, so both directions end in the same place: not executed, ask again.

		Rows 2 and 3 read `asked`, because it is the only thing that still knows what was asked.
		With no record the tool's own gate stands in for it, so the two can never disagree, row 3
		cannot fire, and behaviour is exactly what it was — the right fallback for a run that
		paused before any of this existed. Row 1 needs no record at all.
		"""
		# Structure over the whole list; indistinguishability over the turn about to be acted on,
		# and only that turn. A collision whose calls already have results can never execute again
		# — `_transcript_calls` counts BOTH of a colliding pair answered, so `_prepare_resume` does
		# not even iterate them — so refusing it stops nothing and costs everything: it refused
		# every later approval in that session, forever, recoverable only by deleting the stored
		# row, with a sentence that was false for the person reading it. Validation refuses what is
		# about to RUN, never old history — the same rule R7 settled for the replay path.
		_validate_messages(messages, refuse_indistinguishable_calls=False, refuse_unusable_tool_results=False)
		_refuse_indistinguishable_live_turn(messages, answers)
		messages = list(messages)
		pending = self._pending_calls(messages)
		if not pending:
			raise ValueError("No questions awaiting an answer in the provided messages")

		denied_group = _has_denial(answers)
		# Where the turn this pause is on begins in `pending`. Everything before it is the
		# wreckage of a run that was stopped or that failed; it is resolved with nothing and never
		# acted on — see the first branch of the ladder below.
		live_from = len(pending) - _live_turn_pending_count(messages)
		approval_keys = _approval_question_keys(asked)
		question_keys = _all_question_keys(asked)
		have_record = bool(asked)
		# The turn the person answered has to be the turn this is about to act on, and `live_from`
		# alone cannot promise that. It is positional, but the position is read off which calls
		# still lack a result, and `has_result` is flat over the whole transcript — so a live call
		# whose reference was ALREADY USED by a finished call counts answered, drops out of
		# `pending`, and takes its whole turn out of the reckoning. The last turn with anything
		# unanswered is then an older, abandoned one, `index >= live_from` holds for its calls, and
		# one of them RAN — announced with the model's own arguments — on an approval the person
		# gave for something else, while the action they did approve got no result at all. A
		# provider hands us these references verbatim and scopes them to nothing, and the model can
		# see, in the transcript it is given, which of them already have results.
		#
		# Nothing here can tell those two turns apart (the review's F1-1: pairing each result with
		# the turn it follows is a real change, not this one), so refuse rather than guess.
		#
		# EVERY key the record holds, of either kind, and the reason is one fact about both: a
		# question of either kind belongs to a call that is still PENDING, so its absence from the
		# live slice is a signal rather than a shrug. An approval's call has not run. A tool's own
		# question is filed no differently — `_loop_stream` `continue`s before the line that writes
		# that call's tool result, so it has none either, which the ladder's own last branch below
		# relies on. This comment said the opposite until run 11d ("its call already has a result"),
		# and gated the guard on `approval_keys` alone on the strength of it; a pause that raised no
		# APPROVAL question then made `approval_keys` empty, short-circuited the whole guard away,
		# and let all of the above happen exactly as it did before the guard existed. Including
		# `question_keys` refuses no sound resume, for the same reason it closes this one.
		#
		# An UNUSABLE reference is subtracted, never folded to a value that matches itself, and
		# the record's emptiness is read from `asked` rather than from its keys. Folding both
		# sides of this test was the obvious-looking way to fold it, and it was wrong in the one
		# way that matters: `_call_reference` exists to say a reference cannot answer anything, so
		# making two of them equal turned "neither of these can be identified" into "these are the
		# same call", skipped the guard, and ran the wreckage on a transcript the narrower version
		# had refused (the 11d review's M1, executed). A reference that identifies nothing is not
		# evidence that the record and the live turn are the same turn.
		#
		# `have_record` alone, with no `and recorded`: a pause whose keys are ALL unusable recorded
		# questions all the same, and cannot say which turn they were about — which is the case to
		# refuse, not the case to wave through. That short-circuit is what C1 was made of, and it
		# is gone rather than narrowed. With no record at all there is nothing to check against,
		# and that path already runs nothing it was not asked about.
		live_ids = {_call_reference(call.id) for call in pending[live_from:]} - {NO_CALL_REFERENCE}
		recorded = approval_keys | question_keys
		if have_record and recorded.isdisjoint(live_ids):
			raise ValueError(_UNRESOLVABLE_PAUSE)
		resolved: list[tuple[ToolCall, str, bool]] = []
		for index, call in enumerate(pending):
			answer = answers.get(call.id)
			# Nothing was asked about this call, so the client has no card for it: it was held
			# back, and a held-back call is announced when it runs, not before.
			#
			# All four clauses, and each closes a real card. `index >= live_from`: a call from a
			# turn nobody is resuming is not going to run, and announcing it drew model-authored
			# arguments onto the screen where the person had just approved something else — a
			# question's shape is never steered by values a model wrote. `have_record`: with no
			# record the engine cannot tell a held-back call from an unanswered one and runs
			# neither, so it announces neither. `not denied_group`: a denial starts nothing, so
			# it opens no card — drawing one, with the model's own arguments, for the action the
			# person had just declined is the same defect on the one path where the answer was
			# no. Announce exactly what this resume will run.
			announce = (
				index >= live_from and have_record and not denied_group and call.id not in question_keys
			)
			tool = self._tools_by_name.get(call.name)
			# What the person was asked. With no record of the pause there is nothing to read it
			# from, so the tool's own gate stands in and the two can never disagree — which is
			# exactly the behaviour that existed before any of this was recorded.
			asked_to_approve = (
				call.id in approval_keys if have_record else bool(tool and tool.requires_confirmation)
			)
			if index < live_from:
				# Not the turn this pause is on. `_pending_calls` spans the WHOLE transcript, so
				# every batch that paused and was then abandoned — Stop clears a run's questions
				# but not its messages, and a resume that raises does the same — leaves its calls
				# pending for ever. Decided FIRST, above every other rule, because acting on such
				# a call at all is the mistake: it ran a held-back action from a decision the
				# person walked away from, and where its reference happened to match the live
				# turn's it took the live turn's answer as its own, so one "Approve" executed two
				# gated writes. By POSITION, never by reference: two turns can carry the same
				# reference, and that is exactly the case this exists to separate.
				# Nothing here is a decision anybody is making. Closed out with
				# nothing, as it was before S19 — which also stops it being pending a second time.
				content = _serialize_tool_result(None)
			elif tool is None:
				content = _not_executed("unavailable")
			elif asked_to_approve and tool.requires_confirmation:
				# Only the exact "Approve" ever executes, so that is the only answer the group's
				# denial has to hold back; everything else resolves exactly as it always has.
				if denied_group and answer == "Approve":
					content = _withheld_confirmation()
				else:
					content = self._resolve_confirmation(call, answer)
			elif asked_to_approve or tool.requires_confirmation:
				content = _not_executed("approval_no_longer_applies")
			elif have_record and call.id not in answers and call.id not in question_keys:
				# Nobody was asked about this call: it was held back so that nothing in its turn
				# ran before the person answered. `not in`, never `.get(...) is None` — an answer
				# of None is an answer, and running a tool on the strength of one would be the
				# same defect one branch down. Refusing one action in the group refuses this one
				# with it, because it was held back for the group's sake.
				#
				# Reached only for the live turn — everything else was decided above.
				#
				# `have_record` first: a call HELD BACK and a call
				# whose own question went unanswered are indistinguishable from `answers` alone —
				# both simply have no answer — and only the record tells them apart. Without one,
				# running is the wrong guess in both directions: the second has already executed
				# once, and the first has no answer of any kind behind it. So with no record this
				# falls through to the pre-existing branch below and nothing runs, which is what
				# the ladder in this docstring promises for a pause it cannot read.
				content = (
					_not_executed("group_refused")
					if denied_group
					else _serialize_tool_result(self._run_tool(call))
				)
			elif have_record and call.id in answers and call.id not in question_keys:
				# An answer arrived for a call no question was ever raised for. `answers` is
				# validated for shape only, so this is reachable from the web: acting on it would
				# hand the model whatever text was sent as this tool's result.
				#
				# `call.id in answers` is what the sentence above always meant, and it has to be
				# said out loud now that the branch above can decline a call with no answer: an
				# UNANSWERED call from a turn nobody is resuming is not an answer that no longer
				# applies — nothing was asked and nothing was given — so it falls through to the
				# branch below and is closed out with nothing, exactly as it was before S19.
				content = _not_executed("approval_no_longer_applies")
			else:
				content = _serialize_tool_result(answer)
			messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
			# The record gets every resolution; the CLIENT gets the turn it is answering. A call
			# before `live_from` belongs to a turn nobody is resuming: it has no card — none was
			# drawn when its own run was abandoned, and `announce` is false for it here — so an
			# ending replayed for it is a result for a part the client does not hold. Both shipped
			# clients drop exactly that, which is why nothing looked broken; the invariant a
			# consumer is entitled to rely on, that every `tool_ended` in a stream is one the same
			# stream started or one the person was asked about, was false all the same. Dropped
			# from the events only: `messages` above still closes the call out with nothing, and
			# the stored record is byte-for-byte what it was.
			if index >= live_from:
				resolved.append((call, content, announce))
		return messages, resolved

	def _resolve_confirmation(self, call: ToolCall, answer: Any) -> str:
		"""Run the tool if approved; deny if rejected; redirect with user feedback otherwise."""
		if answer == "Approve":
			result = self._run_tool(call)
			return _serialize_tool_result(result)
		if answer == "Deny":
			return json.dumps({"status": "denied", "message": "User denied this tool call."})
		# Free-text "Other"
		return json.dumps(
			{
				"status": "redirect",
				"message": "Tool not executed.",
				"user_feedback": answer,
				"instruction": "The user wants changes before this proceeds. Read their feedback carefully, adjust your approach, and try again.",
			}
		)

	def _loop(
		self, messages: list[dict[str, Any]], executed_calls: list[ToolCall] | None = None
	) -> RunResult:
		tool_schemas = [t.to_dict() for t in self.tools] or None
		executed_calls = executed_calls if executed_calls is not None else []
		usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

		for iteration in range(1, self.max_iterations + 1):
			response = self.model.chat(messages, tools=tool_schemas)
			_accumulate_usage(usage_total, response.usage)
			messages.append(_assistant_message(response))

			if not response.tool_calls:
				return RunResult(
					output=response.content,
					messages=messages,
					tool_calls=executed_calls,
					iterations=iteration,
					usage=usage_total,
				)

			questions: list[Question] = []
			# The whole batch is classified before any of it runs. A model can ask for a read and
			# a write in one breath; if the write needs a person, the read must not already have
			# happened in their name by the time they are asked, and a Deny must not leave them
			# with a done thing nobody mentioned. The calls nobody was asked about are held back
			# with no tool result, which is what makes them pending at resume.
			plan = [(call, self._disposition(call)) for call in response.tool_calls]
			if any(disposition == "ask" for _call, disposition in plan):
				for call, disposition in plan:
					if disposition != "ask":
						continue
					question = self._invoke(call)
					question.key = call.id
					questions.append(question)
				return RunResult(
					output=response.content,
					messages=messages,
					tool_calls=executed_calls,
					iterations=iteration,
					usage=usage_total,
					paused=True,
					questions=questions,
				)

			for call, disposition in plan:
				result = self._invoke(call)
				if isinstance(result, Question):
					# The second way a run pauses, and the one `_disposition` cannot classify:
					# a question the TOOL ITSELF returned, after its body had already run. In a
					# run with nobody in it that parks the run in `Paused`, holding its session,
					# waiting for an answer that can never come — the same failure a gated tool
					# used to cause, arriving by the other door. The body has run and is not
					# undone; what is refused is the QUESTION, so the model is told the action
					# was not carried through rather than being left mid-sentence.
					if not self._is_unattended():
						result.key = call.id
						questions.append(result)
						continue
					result = _not_executed("unattended")

				# A refused call is told to the model like any other result, and the run carries
				# on — but it did not run, so it is not one of the calls this turn executed.
				if disposition != "refuse":
					executed_calls.append(call)
				messages.append(
					{
						"role": "tool",
						"tool_call_id": call.id,
						"content": _serialize_tool_result(result),
					}
				)

			if questions:
				return RunResult(
					output=response.content,
					messages=messages,
					tool_calls=executed_calls,
					iterations=iteration,
					usage=usage_total,
					paused=True,
					questions=questions,
				)

		raise RuntimeError(f"Agent {self.name!r} exceeded max_iterations ({self.max_iterations})")

	def _loop_stream(
		self, messages: list[dict[str, Any]], executed_calls: list[ToolCall] | None = None
	) -> Generator[Event]:
		tool_schemas = [t.to_dict() for t in self.tools] or None
		executed_calls = executed_calls if executed_calls is not None else []
		usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

		for iteration in range(1, self.max_iterations + 1):
			chunks = self.model.chat(messages, tools=tool_schemas, stream=True)
			# Tool calls are announced (ToolCallBegin) the moment the model starts emitting them,
			# so the UI can show the tool before its arguments finish streaming. They are held
			# here rather than sent straight out: whether a call runs in this step is a property
			# of the WHOLE reply — one call needing a person holds every other call in that reply
			# back — and that cannot be known until the reply is complete. Announcing mid-stream
			# opened a card for an action that was not starting, on exactly the screen where
			# someone was being asked to approve its neighbour.
			held: list[ToolStarted] = []
			try:
				while True:
					item = next(chunks)
					if isinstance(item, ToolCallBegin):
						held.append(ToolStarted(id=item.id, name=item.name, arguments={}))
					else:
						yield TextChunk(text=item)
			except StopIteration as e:
				response = e.value
			_accumulate_usage(usage_total, response.usage)
			# Classified before the turn is admitted, only so the announcements can be released in
			# the order a client has always seen them. `_disposition` reads the tool's own flag and
			# nothing else — it runs no tool body and touches no message — so the refusal
			# `_assistant_message` may raise below still happens before anything is invoked.
			plan = [(call, self._disposition(call)) for call in response.tool_calls or []]
			asked_ids = {call.id for call, disposition in plan if disposition == "ask"}
			for event in held:
				# Nothing is announced that will not run in this step. When the reply has to ask
				# someone, the only calls that go anywhere are the ones being asked about; the rest
				# are held back and are announced on resume, when they run.
				if not asked_ids or event.id in asked_ids:
					yield event
			messages.append(_assistant_message(response))

			if not response.tool_calls:
				yield Done(
					result=RunResult(
						output=response.content,
						messages=messages,
						tool_calls=executed_calls,
						iterations=iteration,
						usage=usage_total,
					)
				)
				return

			questions: list[Question] = []
			# The same one decision as `_loop`, in the loop the web apps actually use. A held-back
			# call produces NO event here — not a start, not an end. It is not running, so there is
			# nothing to draw; `_resume_stream` announces it when the answers come back and it
			# actually runs, with its full arguments. (`plan` was built above.)
			if asked_ids:
				for call, disposition in plan:
					if disposition != "ask":
						continue
					yield ToolStarted(id=call.id, name=call.name, arguments=call.arguments)
					question = self._invoke(call)
					question.key = call.id
					questions.append(question)
					yield ToolEnded(id=call.id, name=call.name, result="")
				yield Done(
					result=RunResult(
						output=response.content,
						messages=messages,
						tool_calls=executed_calls,
						iterations=iteration,
						usage=usage_total,
						paused=True,
						questions=questions,
					)
				)
				return

			for call, disposition in plan:
				# Re-announce with the full arguments now that they've finished streaming, before the
				# tool runs — so the UI shows the arguments during execution, not only with the result.
				yield ToolStarted(id=call.id, name=call.name, arguments=call.arguments)
				result = self._invoke(call)
				if isinstance(result, Question):
					# The second way a run pauses, and the one `_disposition` cannot classify:
					# a question the TOOL ITSELF returned, after its body had already run. In a
					# run with nobody in it that parks the run in `Paused`, holding its session,
					# waiting for an answer that can never come — the same failure a gated tool
					# used to cause, arriving by the other door. The body has run and is not
					# undone; what is refused is the QUESTION, so the model is told the action
					# was not carried through rather than being left mid-sentence.
					if not self._is_unattended():
						result.key = call.id
						questions.append(result)
						yield ToolEnded(id=call.id, name=call.name, result="")
						continue
					result = _not_executed("unattended")

				if disposition != "refuse":
					executed_calls.append(call)
				serialized = _serialize_tool_result(result)
				messages.append({"role": "tool", "tool_call_id": call.id, "content": serialized})
				yield ToolEnded(id=call.id, name=call.name, result=serialized)

			if questions:
				yield Done(
					result=RunResult(
						output=response.content,
						messages=messages,
						tool_calls=executed_calls,
						iterations=iteration,
						usage=usage_total,
						paused=True,
						questions=questions,
					)
				)
				return

		raise RuntimeError(f"Agent {self.name!r} exceeded max_iterations ({self.max_iterations})")

	def _pending_calls(self, messages: list[dict[str, Any]]) -> list[ToolCall]:
		"""Tool calls in the transcript that have no tool result yet (awaiting an answer)."""
		return self._transcript_calls(messages, answered=False)

	def _answered_calls(self, messages: list[dict[str, Any]]) -> list[ToolCall]:
		"""Tool calls in the transcript that already have a tool result (executed)."""
		return self._transcript_calls(messages, answered=True)

	def _transcript_calls(self, messages: list[dict[str, Any]], *, answered: bool) -> list[ToolCall]:
		has_result = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
		calls: list[ToolCall] = []
		for message in messages:
			if message.get("role") != "assistant":
				continue
			for tc in message.get("tool_calls") or []:
				if (tc["id"] in has_result) != answered:
					continue
				fn = tc["function"]
				arguments = fn.get("arguments") or "{}"
				calls.append(ToolCall(id=tc["id"], name=fn["name"], arguments=json.loads(arguments)))
		return calls

	def _build_initial_messages(self, input: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
		"""For a string, build [system?, user]. For a list, trust the caller and use it as-is —
		the caller owns the system message and any history."""
		if isinstance(input, str):
			messages: list[dict[str, Any]] = []
			if self.instructions:
				messages.append({"role": "system", "content": self.instructions})
			messages.append({"role": "user", "content": input})
			return messages
		# Replayed history is read, never executed: on this path `_loop` only ever invokes calls
		# from the CURRENT reply, and `_pending_calls`/`_prepare_resume` are not reachable from
		# here. Refusing an indistinguishable turn in a caller's history therefore prevents no
		# double write, while a conversation is replayed through here on EVERY later message — so
		# one such turn stored in a transcript would refuse every future turn of that
		# conversation, forever, recoverable only by someone who can delete the stored row.
		# The refusal belongs where a tool can be reached from the calls in question: the model's
		# new reply, and a resume.
		_validate_messages(input, refuse_indistinguishable_calls=False, refuse_unusable_tool_results=False)
		return list(input)

	def _is_unattended(self) -> bool:
		"""A run with nobody who can answer a question."""
		return bool(self.unattended or self.auto_approve)

	def _disposition(self, call: ToolCall) -> str:
		"""What happens to this call before anything in its turn runs: "refuse", "ask" or "run".

		Read from the tool's own flag, never from the tool body, so a whole batch can be decided
		before any of it executes. A question a TOOL returns is not an approval and is not
		classified here: by the time it exists its body has already run, so holding its
		neighbours back would protect nothing.
		"""
		tool = self._tools_by_name.get(call.name)
		if call.error or tool is None:
			return "run"
		if not tool.requires_confirmation:
			return "run"
		# Refuse is decided BEFORE ask, and the order is the whole rule: an unattended run must
		# never reach the question at all. Read once and in one place, so a batch can never be
		# classified by a rule that differs from the one that executes it.
		return "refuse" if self._is_unattended() else "ask"

	def _invoke(self, call: ToolCall) -> Any:
		"""Run a tool and return its raw result. A Question (returned or synthesized for
		`requires_confirmation` tools) signals a pause."""
		if call.error:
			return json.dumps({"error": call.error})
		tool = self._tools_by_name.get(call.name)
		if tool is None:
			return json.dumps({"error": f"Unknown tool: {call.name!r}"})
		disposition = self._disposition(call)
		if disposition == "refuse":
			return _not_executed("unattended")
		if disposition == "ask":
			return _confirmation_question(call, tool)
		return self._run_tool(call)

	def _run_tool(self, call: ToolCall) -> Any:
		"""Invoke the tool, returning its result or a serialized error message."""
		tool = self._tools_by_name[call.name]
		try:
			return tool(**call.arguments)
		except Exception as e:
			return json.dumps({"error": _failure_sentence(e)})


# A tool call that cannot be told apart from another in the same turn cannot be approved separately
# from it. There are two such shapes and they fail the same way downstream, so they are one rule
# here: two calls carrying the same id, and two calls carrying no usable id at all — `None` from a
# provider that sends a null, `""` from one that omits the field or never streams it. Both end up as
# the same question key, the same answer lookup and the same membership test, which is the defect.
# Anything that is not a non-empty string is folded into one bucket rather than skipped: skipping it
# is what would leave the likelier half of this defect live.
#
# A SINGLE call folding to this sentinel is refused as well, by the sibling rule in
# `_assistant_message` and with its own sentence. That is not this rule reaching further: one call
# collides with nothing. It is the other thing a reference is for — filing the result — and the
# comment there says why waving one through ended the conversation rather than misrouting an answer.
NO_CALL_REFERENCE = "<none>"

# A plain literal, deliberately, like every other module-level message in this file. `_()` here
# would run at IMPORT time and freeze the translation for the whole worker in whatever language
# happened to be current then — and it would mean the vendor-word check over this string only ever
# inspects the English one, which is the single thing that check exists to prevent.
_UNANSWERABLE_TURN = (
	"Two actions in one reply could not be told apart, so one approval would have answered both. "
	"Nothing was carried out."
)

# Its sibling, and deliberately not the same sentence. A single call carrying no usable reference
# is refused too (see `_assistant_message`), but nothing collided: there is one action, nothing to
# tell it apart from, and — the shape a provider actually produces is as often an ungated tool as a
# gated one — frequently no approval question at all. Telling that person two actions could not be
# told apart and that one approval would have answered both is false on every clause, and a refusal
# a person cannot believe is the defect the rest of this run exists to remove. What IS true is the
# reason: a reference is how an answer is matched AND how the result is filed, and this reply
# carries neither.
_UNFILEABLE_CALL = (
	"An action in this reply arrived with nothing to answer or record it by. Nothing was carried out."
)

# The third sentence of the family, and it is about a STORED transcript rather than a new reply. A
# reference the model reused from a call that already has a result takes the live turn out of the
# reckoning `live_from` is computed from, and then nothing in the transcript can say which turn the
# person just answered. Its own sentence again, for the reason `_UNFILEABLE_CALL` has one: nothing
# collided inside a single turn, and no reply was refused before it was stored — this is an answer
# arriving for a conversation whose record can no longer be read, and saying so is all that is true.
_UNRESOLVABLE_PAUSE = (
	"An action still waiting here cannot be told apart from one already carried out in this "
	"conversation, so nothing was carried out. Please ask again."
)


def _call_reference(id: Any) -> str:
	"""The reference a call will be answered by, and have its result filed under.

	Anything that is not a non-empty string folds to one sentinel, because that is what every
	lookup downstream does with it: the question key, the answer lookup, the `has_result`
	membership test, and the `tool_call_id` a result is written with. One definition, used by
	every rule that asks the question — the collision check, the reply check in
	`_assistant_message`, and the unusable-result check in `_validate_messages` — so no two of
	them can disagree about what counts as usable. `_validate_messages` tested the value's own
	truthiness until run 11b, and that is exactly where they did disagree.
	"""
	return id if isinstance(id, str) and id else NO_CALL_REFERENCE


def _indistinguishable_tool_call(ids: Iterable[Any]) -> tuple[bool, str] | None:
	"""The first reference that appears twice in one assistant turn, or None.

	Returns `(found, reference)` rather than a bare string, so no caller can ever decide on the
	truthiness of the value — an empty reference is a real collision and the most likely one, and a
	guard written `if collided:` would wave it through.

	References are compared EXACTLY: no case-folding and no stripping, because nothing downstream
	normalises either. Membership, the answer lookup and the question key all compare raw, so "c1"
	and "C1" are two answerable calls and must stay two.
	"""
	seen: set[str] = set()
	for id in ids:
		reference = _call_reference(id)
		if reference in seen:
			return True, reference
		seen.add(reference)
	return None


def _live_turn_pending_count(messages: list[Any]) -> int:
	"""How many of `_pending_calls`'s results belong to the turn the pause is on.

	`_transcript_calls` walks the transcript in order, so the unanswered calls of the LAST
	assistant turn that has any are exactly the TAIL of the list it returns. This returns the
	length of that tail.

	Counted, never matched by reference, and that is the whole point: two turns can carry the same
	`tool_call_id`, which is precisely the case where taking the live turn's answer for an older
	turn's call executes a second gated write on one approval. A reference is not an identity
	across turns, so nothing here uses one.

	Everything before that tail is the wreckage of a run that was stopped or that failed — Stop
	clears a run's questions but not its messages, and a resume that raises does the same — and a
	transcript is replayed whole on every later turn, so that wreckage stays pending for ever.

	`messages` is a list, not an `Iterable`: this walks it twice, and a generator would make the
	second pass see nothing, return 0, and quietly treat EVERY pending call as wreckage — the
	person's approval would resolve nothing, with no error anywhere. `_prepare_resume` validates
	for a list before calling this, and the annotation now says so rather than inviting one.
	"""
	has_result = {m.get("tool_call_id") for m in messages if isinstance(m, dict) and m.get("role") == "tool"}
	count = 0
	for message in messages:
		if not isinstance(message, dict) or message.get("role") != "assistant":
			continue
		tool_calls = message.get("tool_calls")
		if not tool_calls:
			continue
		ids = [tc.get("id") if isinstance(tc, dict) else None for tc in tool_calls]
		unanswered = [id for id in ids if id not in has_result]
		if unanswered:
			count = len(unanswered)
	return count


def _refuse_indistinguishable_live_turn(messages: list[Any], answers: Any) -> None:
	"""Refuse an assistant turn a resume is LIVE on and whose calls cannot be told apart.

	The resume-path half of the rule `_validate_messages` applies to a model's new reply. A turn is
	live if it is the LAST one still holding a call with no result — the turn this pause is on —
	or if one of its calls is a key in `answers`, which is a person answering THAT turn. The second
	half is what keeps the nastiest stored shape closed: two colliding calls, one of which already
	ran, leaves nothing pending (`_transcript_calls` counts BOTH of a colliding pair answered), yet
	an answer for that reference would resolve the one that had already executed.

	Everything else is history — a turn already finished, or a pause the person abandoned, which
	stays unanswered for ever because Stop clears a run's questions and not its messages. Neither
	can execute: `_prepare_resume` closes every call outside the live turn out with nothing before
	any other rule is consulted. So refusing them stops nothing and costs a session every later
	approval it will ever make, which is the whole of what R10 is about. "Last turn with something
	pending", not "any turn with something pending", is the difference between the two.

	A call whose reference is `None` or `""` CAN be in `has_result`, and until run 11b this
	paragraph said it could not: it reasoned from `_validate_messages` rejecting such a tool
	message outright, which is what both replay paths stopped doing. What holds now is the other
	way round — a reply carrying an unusable reference is refused in `_assistant_message` before it
	can be stored, so only a transcript written earlier can hold one, and the replay paths READ
	those rather than execute from them.

	Where one is held, references are matched raw (`_transcript_calls`), so a single stored
	empty-reference result marks EVERY empty-reference call in the transcript answered. A turn
	carrying only those then counts as holding nothing pending, and the last turn with something
	pending is a later turn than the old sentence implied. Nothing executes wrongly either way: the
	worst case is a legacy transcript whose still-pending empty-reference call is counted answered,
	and that resume ends on the ordinary "No questions awaiting an answer in the provided
	messages" rather than running anything. A turn whose references are duplicate STRINGS — the
	shape this function is really for — is unaffected, and is still the last-pending turn it was.

	`messages` is a list, not an `Iterable`: this walks it twice, and a generator would silently
	report that no turn is live at all.
	"""
	answered_keys = answers if isinstance(answers, dict) else {}
	has_result = {m.get("tool_call_id") for m in messages if isinstance(m, dict) and m.get("role") == "tool"}

	def _ids(message: Any) -> list[Any] | None:
		if not isinstance(message, dict) or message.get("role") != "assistant":
			return None
		tool_calls = message.get("tool_calls")
		if not tool_calls:
			return None
		return [tc.get("id") if isinstance(tc, dict) else None for tc in tool_calls]

	last_pending = None
	for message in messages:
		ids = _ids(message)
		if ids is not None and any(id not in has_result for id in ids):
			last_pending = message

	for message in messages:
		ids = _ids(message)
		if ids is None:
			continue
		if message is not last_pending and not any(id in answered_keys for id in ids):
			continue
		if _indistinguishable_tool_call(ids) is not None:
			raise ValueError(_UNANSWERABLE_TURN)


def _validate_messages(
	messages: Any,
	*,
	refuse_indistinguishable_calls: bool = True,
	refuse_unusable_tool_results: bool = True,
) -> None:
	"""Structural checks on a message list, plus — unless asked not to — the refusal of an
	assistant turn whose calls cannot be told apart, and of a tool result carrying no reference.

	Both flags default to True so a new call site is guarded unless it says otherwise. The callers
	that opt out are the two that replay STORED history, and they say why: validation refuses what
	is about to RUN, never old history. A tool result with no reference is a record of something
	that already happened, so refusing it ends a conversation and prevents nothing — exactly the
	blast radius R7 and R10 settled for the other rule. A reply that would CREATE one is refused
	where every other unanswerable reply is, in `_assistant_message`, before it is stored.

	`refuse_unusable_tool_results` governs an EMPTY reference only. A tool message missing the
	field altogether is malformed rather than historical, and is refused on every path.
	"""
	if not isinstance(messages, list):
		raise TypeError(f"input must be a str or list of message dicts, got {type(messages).__name__}")
	for i, message in enumerate(messages):
		if not isinstance(message, dict):
			raise TypeError(f"messages[{i}] must be a dict, got {type(message).__name__}")
		role = message.get("role")
		if role not in VALID_ROLES:
			raise ValueError(f"messages[{i}].role must be one of {sorted(VALID_ROLES)}, got {role!r}")
		if role == "tool" and "tool_call_id" not in message:
			raise ValueError(f"messages[{i}] is a tool message but has no tool_call_id")
		# Through `_call_reference`, never `not message["tool_call_id"]`: one definition of "usable"
		# for the structural check and for `_assistant_message`, so the two cannot disagree. They
		# did — a truthy non-string (`42`, a dict) is unusable to every lookup downstream and was
		# refused in a REPLY, while a RESULT carrying the same value passed here.
		if (
			refuse_unusable_tool_results
			and role == "tool"
			and _call_reference(message["tool_call_id"]) == NO_CALL_REFERENCE
		):
			# Two different defects, and only one of them is history's. A message with no
			# `tool_call_id` FIELD is malformed — the caller built the wrong shape, and that is
			# refused wherever it arrives. A field that is present and empty is a RECORD of
			# something that already ran and was filed under nothing; refusing it ends a
			# conversation and prevents nothing, so the replay paths let it through.
			raise ValueError(f"messages[{i}] is a tool message with no usable tool_call_id")
		if "content" not in message and "tool_calls" not in message:
			raise ValueError(f"messages[{i}] must have 'content' or 'tool_calls'")
		if refuse_indistinguishable_calls and role == "assistant" and message.get("tool_calls"):
			# What makes this fix complete rather than only forward-looking: a run that paused
			# BEFORE it, with a transcript the engine would now refuse, is refused at resume
			# instead of double-executing. `_prepare_resume` validates here, so the ordinary
			# resume is closed as well as the model's new reply (`_assistant_message`).
			# Person-facing on the resume path — the text reaches the run's error field — so it
			# is the same one sentence, not a diagnostic.
			# Iterated exactly as `_transcript_calls` iterates it — any sequence, not only a list —
			# and an entry this cannot read folds to the sentinel instead of being SKIPPED.
			# Skipping is what let v1 of this rule wave two `None` ids through; a shape the check
			# drops but `_transcript_calls` still turns into a ToolCall is that hole in a new hat.
			if (
				_indistinguishable_tool_call(
					tc.get("id") if isinstance(tc, dict) else None for tc in message["tool_calls"]
				)
				is not None
			):
				raise ValueError(_UNANSWERABLE_TURN)


def _assistant_message(response: ChatResponse) -> dict[str, Any]:
	message: dict[str, Any] = {"role": "assistant", "content": response.content}
	if response.tool_calls:
		references = [_call_reference(call.id) for call in response.tool_calls]
		# Two rules, two sentences, and the order between them is what decides which sentence a
		# person reads. Refused HERE, before the message is returned to be appended and therefore
		# before anything is invoked — both loops build this message before they touch
		# `response.tool_calls`.
		#
		# COLLISION FIRST, and not for tidiness. Two calls that both carry no usable reference are
		# both things at once, and the collision is the graver of the two: one question cannot
		# address two actions — both would carry the same key, one answer would resolve both, and
		# the tool would run twice on one approval. That is what such a person needs told, so that
		# shape keeps the sentence it has always had.
		#
		# `is not None`, never `if collided:` — the no-reference case is a real collision and its
		# reference is the falsy one. The predicate returns a tuple so this cannot be "simplified"
		# into a bug.
		if _indistinguishable_tool_call(references) is not None:
			raise ValueError(_UNANSWERABLE_TURN)
		# What is left here is a SINGLE unusable reference, and it is refused for a different
		# reason than confusion: one call is confusable with nothing. A reference is also how a
		# result is FILED — `_prepare_resume` and both loops write `tool_call_id=call.id`, and a
		# tool message with no usable reference is one the structural check has always rejected.
		# So letting one through wrote a message into the stored transcript that made every later
		# turn in that conversation raise: the conversation ended, recoverable only by deleting
		# the stored row. Refused before anything is written, so nothing is lost but the one
		# unanswerable reply. Its own sentence, because the collision one is false for it — there
		# was one action, and the tool is as often ungated, so there was no approval either.
		if NO_CALL_REFERENCE in references:
			raise ValueError(_UNFILEABLE_CALL)
		message["tool_calls"] = [
			{
				"id": call.id,
				"type": "function",
				"function": {
					"name": call.name,
					"arguments": json.dumps(call.arguments),
				},
			}
			for call in response.tool_calls
		]
	return message


# Unicode's own `Default_Ignorable_Code_Point` property: "a conformant renderer paints nothing
# here". `unicodedata` does not expose it, so it is written out — 17 ranges, 4174 code points,
# derived from the same property the panel's `/\p{Default_Ignorable_Code_Point}/u` matches and
# cross-checked against it, because the two escapers are one rule ported and drifting is the whole
# risk (`frontend/src/lib/display.js`, `frontend/tests/displayProperty.spec.js`).
#
# WHY IT IS HERE AT ALL, since the rule beside it already takes every C* and Z* category: **267 of
# these are in neither.** Four are category `Lo` — LETTERS — so no rule about controls, formats,
# separators or combining marks could ever have reached them, and they are invisible, which is the
# entire attack. A reviewer found this by measuring the property against the rule; reading the rule
# would not have shown it.
_DEFAULT_IGNORABLE_RANGES = (
	(0x00AD, 0x00AD),
	(0x034F, 0x034F),
	(0x061C, 0x061C),
	(0x115F, 0x1160),
	(0x17B4, 0x17B5),
	(0x180B, 0x180F),
	(0x200B, 0x200F),
	(0x202A, 0x202E),
	(0x2060, 0x206F),
	(0x3164, 0x3164),
	(0xFE00, 0xFE0F),
	(0xFEFF, 0xFEFF),
	(0xFFA0, 0xFFA0),
	(0xFFF0, 0xFFF8),
	(0x1BCA0, 0x1BCA3),
	(0x1D173, 0x1D17A),
	(0xE0000, 0xE0FFF),
)


def _paints_nothing(ch: str) -> bool:
	"""True for a code point a conformant renderer draws as nothing, whatever category it is filed
	under. Seventeen ranges is short enough that a scan is cheaper than building a set per call and
	clearer than a bisect; the list is sorted and the scan stops early."""
	cp = ord(ch)
	for low, high in _DEFAULT_IGNORABLE_RANGES:
		if cp < low:
			return False
		if cp <= high:
			return True
	return False


# The two joiners are the one deliberate exception to the rule above, and the reason is that in
# Sinhala, Tamil, Devanagari and every other Indic script a joiner is not decoration — it is
# SPELLING. A conjunct is written CONSONANT + VIRAMA + ZWJ + CONSONANT, so `\u0dc1\u0dca\u200d\u0dbb\u0dd3`
# is one word and marking the joiner inside it drops six characters of machine escape into the
# middle of it. The defence that exists so a person can read what they are approving was making the
# text unreadable for the people who read it.
#
# PORTED, NOT INVENTED. Two sibling front ends decided this first and tested it
# (`joinsRatherThanHides`): "a joiner that FOLLOWS a virama is orthography, not hiding, and is
# kept." Their version is widened here in one direction and narrowed in two; every difference is
# written down in `brain/40-architecture/the-invisible-character-rule.md` beside the reason for it.
_JOINERS = ("\u200c", "\u200d")  # ZERO WIDTH NON-JOINER, ZERO WIDTH JOINER

# Unicode's own Virama combining class. READ FROM THE LIBRARY rather than written out, because the
# front ends write out sixteen viramas by hand and `unicodedata` knows sixty-nine (measured
# 29 Sep 2026, UCD 16.0.0) — the same table drift in miniature, and a table nobody has to maintain
# cannot drift.
_VIRAMA_COMBINING_CLASS = 9

# ...AND THE COMBINING CLASS ALONE IS NOT ENOUGH, which an adversarial review measured after the
# first version of this shipped. Combining class 9 says how a mark REORDERS. It does not say that
# the mark's script spells conjuncts with a joiner, and several that carry it do not: Thai U+0E3A
# PHINTHU, Lao U+0EBA, Tifinagh U+2D7F, Myanmar U+103A ASAT (a killer, not a stacker) and Brahmi
# U+1107F NUMBER JOINER. A joiner kept after one of those paints nothing AND forms nothing — two
# different writes, one set of pixels, and not even a quote to say so. That is the very attack this
# escaper exists to stop, readmitted by its own exception.
#
# So the exception is confined to the range whose joiner orthography the Unicode Standard actually
# documents: U+0900..U+0DFF, the ten Brahmi-derived blocks — Devanagari, Bengali, Gurmukhi,
# Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam, Sinhala. Twelve viramas, measured 29 Sep 2026
# on UCD 16.0.0.
#
# THIS IS ALSO WHAT MAKES CLAUSE 4 EXACT RATHER THAN A HEURISTIC. The same review measured the
# direction the first version had not: 27 viramas across Unicode have a letter of a DIFFERENT script
# inside their own 128-point block (U+2D7F TIFINAGH would have licensed U+2D00 GEORGIAN, U+A953
# REJANG licensed U+A960 HANGUL, U+10A3F KHAROSHTHI licensed U+10A60 OLD SOUTH ARABIAN), so clause 4
# admitted precisely the cross-script joiner it was invented to refuse. Inside U+0900..U+0DFF there
# are ZERO such pairs: each of the ten blocks holds the letters of exactly one script, which is why
# `cp >> 7` is the script here and only here. `TestTheExceptionIsConfinedToScriptsThatSpellWithIt`
# asserts both facts over the whole of Unicode rather than over examples.
#
# The cost is that a script outside the range keeps no exception and escapes its own conjuncts, as
# it did before this rule existed. That is an ugly card, never a hidden character: the rule fails
# CLOSED, and widening it is a decision with a measurement attached, not a one-line change.
_JOINING_SCRIPT_RANGE = (0x0900, 0x0DFF)


def _spells_rather_than_hides(text: str, index: int) -> bool:
	"""True for a joiner at `index` that is forming a conjunct, rather than sitting invisibly.

	Four clauses, and each one is the shape of an attack it refuses:

	1. NOT AT EITHER EDGE. A joiner with nothing on one side of it joins nothing; it can only hide.
	2. A VIRAMA IMMEDIATELY BEFORE, AND IN U+0900..U+0DFF. Combining class 9 is what makes it a
	   virama; the range is what makes its script one that spells with a joiner at all. See the
	   comment on `_JOINING_SCRIPT_RANGE` for the five combining-class-9 marks that take no joiner.
	3. A LETTER IMMEDIATELY AFTER. This disposes of the doubled and the run cases for free: the code
	   point after the first joiner of `VIRAMA ZWJ ZWJ LETTER` is a joiner, which is not a letter,
	   and the one after the second has no virama before it.
	4. THE TWO NEIGHBOURS IN THE SAME 128-CODE-POINT ALIGNED BLOCK. This clause the front ends do
	   not have, and it closes a hole they still carry: `SO-000A\u094d\u200dx` — a Latin letter, a
	   Devanagari virama, a joiner, a Latin `x` — satisfies 1 to 3 while the joiner forms a conjunct
	   with nothing, so it is purely hidden. Inside the range clause 2 allows, each 128-point block
	   holds the letters of exactly one script, so `cp >> 7` IS the script rather than a proxy for
	   it. The nine Devanagari letters that fall outside their own block (the Extended-A candrabindu
	   signs and `DEVANAGARI LETTER AY`) simply keep no exception, which is where they were before
	   this function existed. The rule fails CLOSED.

	Reads `text` and nothing else.
	"""
	if index == 0 or index + 1 >= len(text):
		return False
	before = text[index - 1]
	after = text[index + 1]
	low, high = _JOINING_SCRIPT_RANGE
	if not low <= ord(before) <= high:
		return False
	if unicodedata.combining(before) != _VIRAMA_COMBINING_CLASS:
		return False
	if unicodedata.category(after)[0] != "L":
		return False
	return ord(before) >> 7 == ord(after) >> 7


def _escaped(text: str) -> str:
	"""Text made safe to read: every character that could move the cursor is shown, never obeyed.

	The values in an approval question are chosen by the model. A newline in one would start a line
	of its own and could write a second, friendlier question underneath the real one; a right-to-left
	override would reorder the sentence around it while leaving every character in place. Both are
	ways to show a person a question other than the one being asked, so every control and format
	character is printed as an escape instead.

	The backslash and the quote are escaped too. Without that, `\\n` in the output could be either a
	real line break or those two characters, and a quote inside a value could close the pair holding
	it — the point of escaping is that the reader can tell exactly what the value was.

	The rule is a whitelist and has to stay one. It began as a list of the categories that looked
	dangerous — Cc and Cf — and that list missed U+2028 and U+2029, which `str.splitlines` and every
	layout engine treat as line breaks, so a value could still open a line of its own. Everything in
	a C* or Z* category is escaped now, the ordinary space excepted: unassigned code points, private
	use and lone surrogates included, so a later revision of Unicode cannot quietly add a new way
	through.

	THE ONE EXCEPTION IS A JOINER DOING ITS JOB — see `_spells_rather_than_hides`. A joiner inside
	an Indic conjunct is spelling, not hiding, and escaping it destroys the word. Nothing else is
	exempt, and a joiner anywhere else is escaped exactly as it was: the exception is narrow on
	purpose, because the defence it is an exception to is what makes what you see what runs.
	"""
	return "".join(_escaped_at(text, index) for index in range(len(text)))


def _escaped_at(text: str, index: int) -> str:
	"""The displayed form of ONE character of `text`, decided in the context of the whole value.

	THE WHOLE VALUE IS THE POINT, and this function exists because a reviewer found the place that
	had forgotten it. `flow/tools/builtins.py` escapes and caps in one pass, and it did so by
	handing `escape_for_display` one character at a time. A one-character string has no character
	before or after it, so clause 1 of `_spells_rather_than_hides` refused every joiner
	unconditionally: the exception was STRUCTURALLY UNREACHABLE on the path the six shipped write
	builtins use, which is where production write confirmations come from. `_escaped` had been
	fixed and the card a person actually reads had not.

	So the decision is exposed under a name a capping caller can use (`escape_for_display_at`),
	taking the index into the whole value rather than a character torn out of it. There is still
	exactly one rule; the caller chooses where to CUT, never what a character means.
	"""
	ch = text[index]
	if ch in '\\"':
		return "\\" + ch
	if ch == "\n":
		return "\\n"
	if ch == "\r":
		return "\\r"
	if ch == "\t":
		return "\\t"
	if ch in _JOINERS and _spells_rather_than_hides(text, index):
		return ch
	if ch != " " and (unicodedata.category(ch)[0] in "CZ" or _paints_nothing(ch)):
		return f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}"
	return ch


def _quoted_argument(value: Any) -> str | None:
	"""One argument, ready to read: escaped, quoted, and never shortened.

	None when it cannot be shown whole — not a scalar, or longer than the cap once escaped. The
	caller then abandons the sentence entirely rather than show a shortened value, because a
	question holding part of a value reads exactly like one holding all of it, and the part left
	out is the part someone needed.
	"""
	if not isinstance(value, CONFIRM_SCALAR_TYPES):
		return None
	# Escaping only ever lengthens, so a value already over the cap is refused before the work of
	# escaping it: the value is chosen by the model and can be megabytes.
	if isinstance(value, str) and len(value) > CONFIRM_VALUE_LIMIT:
		return None
	shown = _escaped(value if isinstance(value, str) else json.dumps(value))
	if len(shown) > CONFIRM_VALUE_LIMIT:
		return None
	return f'"{shown}"'


def _readable_arguments(value: Any, depth: int = 0) -> str:
	"""The call's arguments, laid out as `json.dumps(..., indent=2, default=str)` laid them out,
	with every string escaped by THIS module's rule instead of by `ensure_ascii`.

	**The defect.** `json.dumps` defaults to `ensure_ascii=True`, and the untemplated body never
	passed through `_escaped` at all. So on the commonest card of all — a gated tool with neither a
	`confirm_prompt` nor a `confirm_template` — every non-ASCII character arrived as a backslash-u
	sequence. Not the joiner: every letter of every writing system that is not English. A Sinhala
	value was twenty-odd escapes, and so was a Tamil, Arabic or Chinese one.

	**Why the flag was not simply turned off.** Nobody chose `ensure_ascii=True` — it is a default
	this call never passed — but by accident it was the only thing escaping a right-to-left
	override, a line separator or a hidden joiner on this path, and turning it off alone would have
	put all three onto the card raw. The guard was real; it was indiscriminate, catching every
	letter of four scripts in order to catch three attackers.

	So the guard is replaced rather than removed, by the stricter rule this module already has.
	`_escaped` covers a SUPERSET of what `ensure_ascii` was catching — everything in a C* or Z*
	category, the ordinary space excepted, plus anything that paints nothing — and it escapes none
	of the letters. One rule for everything a person reads, which is the point of `_escaped`
	existing under a public name at all.

	**The English card does not move.** The layout is `json.dumps(indent=2)`'s, reproduced, so
	arguments that were already ASCII render byte for byte as they shipped. Two deliberate
	divergences, both stricter: `\b`, `\f` and DEL come out as `\u0008`, `\u000c` and `\u007f`
	rather than as JSON's own shorthands or, for DEL, as nothing at all.

	It also cannot raise, which the thing it replaces could: `json.dumps` rejects a dict key that
	is not a basic type outright, and `_confirmation_question`'s own comment says that function
	must never be the reason nobody is asked. Here such a key is shown as text.
	"""
	pad, closing = "  " * (depth + 1), "  " * depth
	if isinstance(value, dict):
		if not value:
			return "{}"
		rows = [
			f"{pad}{_readable_text(_readable_key(key))}: {_readable_arguments(item, depth + 1)}"
			for key, item in value.items()
		]
		return "{\n" + ",\n".join(rows) + "\n" + closing + "}"
	if isinstance(value, list | tuple):
		if not value:
			return "[]"
		rows = [f"{pad}{_readable_arguments(item, depth + 1)}" for item in value]
		return "[\n" + ",\n".join(rows) + "\n" + closing + "]"
	if isinstance(value, str):
		return _readable_text(value)
	# `bool` before `int`, because it is one: `json.dumps` writes `true`, not `1`.
	if value is None or isinstance(value, bool | int | float):
		return json.dumps(value)
	# What `default=str` did, and for the same reason: an argument nothing can serialise must not
	# be the reason a person is never asked.
	return _readable_text(str(value))


def _readable_key(key: Any) -> str:
	"""A dict key as JSON would have named it. Strings are already right; the rest are the four
	`json.dumps` coerces rather than rejects, and anything else is shown as text rather than
	raising."""
	if isinstance(key, str):
		return key
	if key is None:
		return "null"
	if key is True:
		return "true"
	if key is False:
		return "false"
	if isinstance(key, int | float):
		return json.dumps(key)
	return str(key)


def _readable_text(text: str) -> str:
	"""One string, quoted and escaped by the module's one rule.

	`_escaped` already escapes the backslash and the quote, so what comes back sits inside the
	quotes as a JSON string body would — it is simply a stricter one.
	"""
	return f'"{_escaped(text)}"'


def _render_confirm_template(template: str, arguments: dict[str, Any]) -> str | None:
	"""Fill an administrator's sentence in from this call's own arguments, or give up.

	This is a substitution, not an evaluation: `{name}` becomes the argument called `name` and
	nothing else happens, so there is nothing here for a value to be interpreted AS. Returns None
	whenever the sentence cannot be produced in full — a name the call did not supply, a value that
	is not a scalar or will not fit — and the caller falls back to the arguments as they are.

	Reads `template` and `arguments` and nothing else: no record, no session, no database, no disk.
	It cannot raise, because a badly written question must never be able to stop a person being
	asked.
	"""
	try:
		# The author's own line breaks are not the value's: the sentence is one line, so the
		# arguments printed beneath it can never be mistaken for part of it.
		sentence = " ".join(template.split())
		if not sentence:
			return None

		incomplete = False

		def substitute(match: re.Match[str]) -> str:
			nonlocal incomplete
			shown = _quoted_argument(arguments[match.group(1)]) if match.group(1) in arguments else None
			if shown is None:
				incomplete = True
				return ""
			return shown

		rendered = CONFIRM_PLACEHOLDER.sub(substitute, sentence)
		if incomplete or len(rendered) > CONFIRM_BODY_LIMIT:
			return None
		return rendered
	except Exception:
		return None


def _confirmation_question(call: ToolCall, tool: Tool) -> Question:
	"""Build the approval prompt shown to the user for a `requires_confirmation` tool call.

	The body is the tool's `confirm_prompt` when it has one — that is code, written and reviewed
	alongside the tool itself. Otherwise it is the record's plain-language sentence followed ALWAYS
	by the arguments that will execute, and the arguments alone when there is no sentence or it
	could not be filled in whole.

	The sentence never replaces the arguments. Its wording comes from an administrator, and a
	question reading "Read the invoices" above a call that deletes them must not be the only thing
	anyone sees. `confirm_prompt` is the exception, deliberately: it is code, written and reviewed
	with the tool rather than typed into a record, and `test_confirm_prompt_renders_plain_english_body`
	asserts that the argument shape does not appear beneath it.

	Wording only: what executes, and on which answer, is decided elsewhere and nothing here can
	reach it.
	"""
	body = tool.confirm_prompt(call.arguments) if tool.confirm_prompt else None
	if not body:
		# Built only where it is used. `json.dumps` can raise on an exotic argument, and this
		# function must not be the reason nobody is asked -- `_readable_arguments` reproduces its
		# layout, cannot raise, and escapes by this module's rule rather than by `ensure_ascii`,
		# which was turning every non-English letter on this card into a backslash-u sequence.
		dump = _readable_arguments(call.arguments)
		sentence = (
			_render_confirm_template(tool.confirm_template, call.arguments) if tool.confirm_template else None
		)
		body = f"{sentence}\n\n{dump}" if sentence else dump

	title = _escaped(" ".join((tool.title or "").split()))
	# Joined, not interpolated. The body carries the model's own words and is never an argument to
	# a formatter, so there is nothing for a value shaped like `{0}` or `%s` to be read as.
	return Question(
		prompt=_("Approve {0}?").format(title or f"`{call.name}`") + "\n\n" + body,
		options=["Approve", "Deny"],
		allow_other=True,
	)


# The same escaping, under a name other modules may use. `_escaped` and every function that calls
# it stay byte-identical: a second escaper elsewhere in the codebase would be a second rule, and the
# first thing to drift. Text shown to a person, and text a person's answer depends on, is escaped
# here or nowhere.
escape_for_display = _escaped

# The same rule, one character at a time, for a caller that has to CUT the escaped text somewhere —
# `flow/tools/builtins.py` escapes and caps in one pass. It takes the index into the whole value
# because the whole value is what the joiner exception is decided against; a caller that passed a
# one-character string would silently lose it.
escape_for_display_at = _escaped_at


def _approval_question_keys(asked: list[Any] | None) -> frozenset[str]:
	"""The keys of the questions in a pause that asked a person to APPROVE something.

	Read from the questions the pause raised, never from the runtime — the runtime is the thing
	that may have changed. An approval question is known by its options: every one the engine
	raises carries `CONFIRM_ANSWER_OPTIONS`, in that order, and nothing else in the engine does.

	Accepts `Question`s or the rows stored from them, because the caller that has this record is
	usually reading it back from storage. Anything it cannot read is simply not an approval
	question here: the branch this guards only ever withholds, so failing to recognise one costs
	today's behaviour and never an unasked execution.

	That safety argument covers what this set WITHHOLDS, and no longer covers every caller: since
	run 11b a resume is also REFUSED when the record's keys are absent from the turn about to be
	acted on. A tool that returns a question of its own carrying these two options is
	indistinguishable from an engine approval here, so its key lands in this set (the review's
	C4). The direction is fail-closed — a sound resume refused, nothing run — and since run 11d
	that guard reads `_all_question_keys` as well, so such a key is in its set either way and
	recognising it wrongly changes nothing there. Marking engine-authored approvals explicitly,
	rather than inferring them from their options, is the real answer and wants a spec.
	"""
	keys: set[str] = set()
	for question in asked or []:
		if isinstance(question, dict):
			key, options = question.get("key"), question.get("options")
		else:
			key, options = getattr(question, "key", None), getattr(question, "options", None)
		if (
			isinstance(key, str)
			and isinstance(options, list | tuple)
			and tuple(options) == CONFIRM_ANSWER_OPTIONS
		):
			keys.add(key)
	return frozenset(keys)


def _all_question_keys(asked: list[Any] | None) -> frozenset[str]:
	"""Every key in a pause's record, whatever kind of question raised it.

	`_approval_question_keys` filters to the ones that asked a person to APPROVE something, which
	is the wrong question for a call that was HELD BACK: a tool's own question is not an approval
	and its call is not deferred. Both are read from the record for the same reason — the runtime
	resuming a run is not always the one that paused it.

	A key the reader cannot use is dropped, and this set is therefore NOT the answer to "did the
	record hold a question". It was briefly folded through `_call_reference` so that it would be,
	and that was wrong twice over: the sentinel is a real string, a stored transcript can hold it
	as a literal `tool_call_id`, and every reader below compares a RAW `call.id` — so the fold
	moved `announce` and the ladder's own branches, one of them into writing a caller's answer
	text in as a tool's result, which is the harm that branch exists to prevent (the 11d review's
	L1, executed). The live-slice guard asks its question of `asked` itself instead.
	"""
	keys: set[str] = set()
	for question in asked or []:
		key = question.get("key") if isinstance(question, dict) else getattr(question, "key", None)
		if isinstance(key, str):
			keys.add(key)
	return frozenset(keys)


# A refusal that says nothing is worse than a refusal that says the wrong thing, and until run 17
# this was the commoner of the two. A permission check in the surrounding framework raises an
# exception whose own text is EMPTY -- its sentence goes to a message log this module does not read
# -- so `str(e)` was `""` and the model was handed `{"error": ""}`: told an action failed, given no
# reason, and left to invent one. It turned up on the resume path, where an approved call is now
# carried out as the person who ASKED for it and may be refused for exactly that reason.
#
# The log is deliberately not read instead. It is written by the framework, names its own record
# types and tables, and this string goes straight into the model's context.
#
# Matched by the class's NAME rather than by the class, because this module touches no framework
# object of its own -- `grep -n "frappe\." flow/lib/agent.py` is empty and is meant to stay empty;
# `from frappe import _` is the whole of the coupling. The builtin of the same name never reaches
# here: it always carries a message, so the branch above returns first.
_PERMISSION_ERROR_NAMES = frozenset({"PermissionError"})

_NOT_ALLOWED = (
	"This action was not carried out. The person it is being done for is not allowed to do it, and "
	"nothing was changed. Do not report it as done, and do not attempt it another way -- tell the "
	"user it did not happen."
)

# Its sibling, and deliberately vaguer, because less is known. An empty message from anything else
# says nothing about whether the action took effect, and a sentence claiming it did not would be a
# guess presented as a fact.
_NO_REASON_GIVEN = (
	"This action failed and reported no reason, so whether it took effect is not known. Do not "
	"report it as done; tell the user it failed."
)


def _failure_sentence(error: Exception) -> str:
	"""What the model is told when a tool raised. Never nothing."""
	text = str(error).strip()
	if text:
		return text[:ERROR_MESSAGE_LIMIT]
	if type(error).__name__ in _PERMISSION_ERROR_NAMES or any(
		base.__name__ in _PERMISSION_ERROR_NAMES for base in type(error).__mro__
	):
		return _NOT_ALLOWED
	return _NO_REASON_GIVEN


def _not_executed(reason: str) -> str:
	"""Result for a pending call the engine will not act on, because the tool is gone or because
	the approval that was given no longer applies to it.

	Every part of this is a literal. The person's answer is deliberately absent: writing it here
	is the defect this exists to stop, since the model then reads its own tool call as having
	returned the word a person typed, and may report the action done when nothing ran.
	"""
	return json.dumps({"status": "not_executed", "reason": reason, "message": NOT_EXECUTED_MESSAGES[reason]})


def _withheld_confirmation() -> str:
	"""Result for a call the user approved inside a group that also held a denial.

	It says approved-and-not-run, which is not the same as denied and not the same as never
	asked. `user_answer` is a fixed literal, not the value from the answers map: nothing a
	caller supplies is echoed back into the model's context from here.
	"""
	return json.dumps(
		{
			"status": "not_executed",
			"message": "Nothing in this group ran. The user approved this action but denied another action in the same group.",
			"user_answer": "Approve",
		}
	)


def _has_denial(answers: dict[str, Any]) -> bool:
	"""A Deny answer halts the run — the user rejected an action, so stop rather than
	continue. Approve and free-text (redirect) answers let the run proceed."""
	return any(answer == "Deny" for answer in answers.values())


def _serialize_tool_result(result: Any) -> str:
	if isinstance(result, str):
		return result
	if result is None:
		return ""
	try:
		return json.dumps(result, default=str)
	except (TypeError, ValueError):
		return str(result)


def _accumulate_usage(total: dict[str, int], delta: dict[str, int]) -> None:
	"""Add one model call's counts onto the running total for the turn.

	ADDS, and adds EVERY key, including ones this function has never heard of. It used to sum exactly
	three hard-coded names, so any further count a call reported — a cached-input count, a cost in
	micros, a count of calls served by something other than what was asked for — was dropped for every
	call in the turn. That matters because of how the obvious repair goes wrong: "sum what we know,
	create what we do not" is naturally written `if key in total: continue`, and that guard skips a key
	precisely once it has a value to add to. The first call of a turn sets it, every later call is
	skipped, and the result is assignment wearing the shape of addition — a number understated by more
	the more work is done, which is the opposite of the direction an error should take. So there is no
	key list here at all, and the rule is the same one `_merge_usage` already applies when it folds a
	turn's total onto the record's.

	`bool` is rejected outright. `isinstance(True, int)` is True in Python, so a flag emitted as `True`
	rather than `1` would sum to 1, then 2, then 3, and be read downstream as a count of something that
	happened three times. A flag is not a quantity; anything that wants to say "this happened" says it
	as the integer 1 and is then countable on purpose.

	A FRACTION IS KEPT AS A FRACTION. This used to coerce with `int()`, which floored a per-call cost
	of 0.004 to ZERO on every call and totalled nothing, with no log — and the docstring above offers
	"a cost in micros" as exactly the sort of key it now sums, so the invitation and the trap were in
	the same paragraph. Truncation applied per call, so the error grew with the number of calls,
	which is the direction this function is supposed to be fixing. Integers still add as integers;
	only a value that arrives fractional stays fractional.

	NOTHING NON-FINITE GETS IN. `json.loads('{"prompt_tokens": Infinity}')` succeeds — the standard
	library accepts that non-standard literal — so `inf` and `nan` can arrive from a malformed or
	hostile upstream body. `int(float("inf"))` raises `OverflowError`, which the previous
	`except (TypeError, ValueError)` did not catch, so a turn that had already done its work died
	over its own meter. A count is skipped instead: the person is owed the answer whatever the meter
	says, and a total holding `nan` is worse than a total missing a key, because `nan` propagates
	silently through every sum downstream while a missing key is visible.

	Everything else that will coerce to an integer still does, exactly as before, and anything that
	will not is skipped rather than crashing the turn over a number.
	"""
	for key, value in delta.items():
		if isinstance(value, bool):
			continue
		if isinstance(value, numbers.Number) and not isinstance(value, complex):
			# NOT `numbers.Real`, and the difference is the whole point of this branch: `Decimal` is
			# registered against `numbers.Number` and DELIBERATELY NOT against `Real`, so a
			# `Real` test sends it to the `int()` fall-through and floors it to zero on every call —
			# the very defect the float branch was added to fix, one type over, and `Decimal` is what
			# the framework's Currency reads hand back and the obvious type for a cost. `complex` is
			# excluded because it is a `Number` that `math.isfinite` will not even accept.
			if not math.isfinite(value):
				continue
			amount: Any = value
		else:
			try:
				amount = int(value)
			except Exception:
				# Deliberately every exception, not a list of the ones someone thought of. The list
				# was `(TypeError, ValueError)`, which did not include the `OverflowError` that
				# `int(float("inf"))` raises, and then `(TypeError, ValueError, OverflowError)`,
				# which did not include whatever a foreign object's `__int__` raises. A count is
				# never worth a turn: the work is done and the person is owed the answer.
				continue
		total[key] = total.get(key, 0) + amount
