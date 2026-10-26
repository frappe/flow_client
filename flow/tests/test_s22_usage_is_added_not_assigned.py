# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE
"""What a turn's counts add up to, and whether the reply was answered by what was asked for.

Two defects, one of them live and one of them a hole where a number should be.

C4 — `_accumulate_usage` summed three hard-coded names and dropped every other count a call
reported. A turn with a tool call makes more than one call, so any further count — a cost, a
cached-input count, a count of calls answered by something else — survived from the first call of
the turn and from none of the others. The natural repair is worse than the bug: "sum what we know,
create what we do not" is written `if key in total: continue`, and that guard skips a key precisely
once it has something to add to. Assignment wearing the shape of addition, understating by more the
more work is done.

H2 — cost is worked out against the rate for the thing that was ASKED FOR, while the money was spent
on whatever actually answered. Those differ whenever an administrator-set fallback fires, and the
request keyword dictionary is built so that anything the client library accepts flows straight
through. Nothing captured that they had differed, so the figure could be labelled with the most
authoritative source the record has and still be a figure for a different thing.
"""

from decimal import Decimal
from types import SimpleNamespace

from frappe.tests import UnitTestCase

from flow.lib.agent import Agent, _accumulate_usage
from flow.lib.model import ChatResponse, ToolCall, _consume_stream, _normalize
from flow.lib.tool import tool
from flow.tests.test_ai_agent import FakeModel, _final


class TestUsageIsAddedNotAssigned(UnitTestCase):
	def test_a_key_the_function_has_never_heard_of_is_summed_not_kept_from_the_first_call(self):
		"""The whole of C4, at the unit that decides it."""
		total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
		for _ in range(3):
			_accumulate_usage(total, {"prompt_tokens": 10, "provider_cost_usd_micros": 4321})

		self.assertEqual(total["prompt_tokens"], 30)
		# Three calls at 4321 is 12963. Under the old rule it was 4321 — the first call's figure,
		# wearing the label of the whole turn.
		self.assertEqual(total["provider_cost_usd_micros"], 12963)

	def test_a_key_absent_from_the_first_call_still_totals(self):
		"""The other direction: a count some calls carry and others do not."""
		total = {"prompt_tokens": 0}
		_accumulate_usage(total, {"prompt_tokens": 1})
		_accumulate_usage(total, {"prompt_tokens": 1, "served_model_mismatch": 1})
		_accumulate_usage(total, {"prompt_tokens": 1, "served_model_mismatch": 1})

		self.assertEqual(total["served_model_mismatch"], 2)
		self.assertEqual(total["prompt_tokens"], 3)

	def test_a_flag_sent_as_true_is_refused_rather_than_counted(self):
		"""`isinstance(True, int)` is True, so a flag would sum to 1, then 2, then 3 and be read as a
		count of something that happened three times. A flag is not a quantity."""
		total = {}
		_accumulate_usage(total, {"cache_hit": True, "other": False, "real_count": 1})

		self.assertNotIn("cache_hit", total)
		self.assertNotIn("other", total)
		self.assertEqual(total["real_count"], 1)

	def test_a_value_that_is_not_a_number_at_all_is_skipped_rather_than_ending_the_turn(self):
		total = {"prompt_tokens": 0}
		_accumulate_usage(total, {"prompt_tokens": 5, "model_name": "something", "missing": None})

		self.assertEqual(total, {"prompt_tokens": 5})

	def test_a_fractional_count_is_summed_and_not_floored_to_zero(self):
		"""A reviewer's finding, and the docstring invited it: this function's own comment offers
		"a cost in micros" as the kind of key it now sums, and `int()` floored anything smaller than
		one to ZERO on every call. A cost emitted in dollars rather than micros totalled 0 with no
		log, and `1.9` three times came to 3 rather than 5.7 — truncation applied per call, so the
		error grew with the number of calls, which is the direction the docstring says it guards
		against."""
		total = {}
		for _ in range(3):
			_accumulate_usage(total, {"provider_cost_usd": 0.004, "reasoning_tokens": 1.9})

		self.assertAlmostEqual(total["provider_cost_usd"], 0.012)
		self.assertAlmostEqual(total["reasoning_tokens"], 5.7)

	def test_an_integer_count_stays_an_integer(self):
		"""The other side of it. Accepting floats must not turn every token count into one."""
		total = {}
		_accumulate_usage(total, {"prompt_tokens": 5})
		_accumulate_usage(total, {"prompt_tokens": 5})

		self.assertIsInstance(total["prompt_tokens"], int)
		self.assertEqual(total["prompt_tokens"], 10)

	def test_a_decimal_is_a_fraction_too(self):
		"""The same defect one type over, and it is the type a money count actually arrives as.

		The first repair branched on `int`, then `float`, and let everything else fall through to
		`int()` — so `Decimal("0.004")` was floored to 0 on every call exactly as the float had been,
		while the docstring above said "A FRACTION IS KEPT AS A FRACTION". `Decimal` is what the
		framework's Currency reads hand back and the obvious type for the "cost" key that same
		docstring invites, so this is the path the feature would have been built on."""
		total = {}
		for _ in range(3):
			_accumulate_usage(total, {"cost": Decimal("0.004")})

		self.assertEqual(total["cost"], Decimal("0.012"))

	def test_a_number_that_refuses_to_become_one_does_not_end_the_turn_either(self):
		"""`except (TypeError, ValueError, OverflowError)` was still a list of the exceptions someone
		thought of — the same shape as the `OverflowError` hole it had just replaced. An object whose
		`__int__` raises anything else killed the turn. A count is never worth a turn."""

		class Awkward:
			def __int__(self):
				raise ZeroDivisionError("boom")

		total = {"prompt_tokens": 1}
		_accumulate_usage(total, {"prompt_tokens": 2, "weird": Awkward()})

		self.assertEqual(total, {"prompt_tokens": 3})

	def test_a_non_finite_decimal_is_skipped_like_a_non_finite_float(self):
		total = {"prompt_tokens": 1}
		_accumulate_usage(total, {"a": Decimal("NaN"), "b": Decimal("Infinity")})

		self.assertEqual(total, {"prompt_tokens": 1})

	def test_a_non_finite_number_does_not_end_the_turn(self):
		"""`json.loads('{"prompt_tokens": Infinity}')` succeeds — the standard library accepts that
		non-standard literal — so `inf` can reach here from a malformed or hostile upstream body.
		`int(float('inf'))` raises `OverflowError`, which the old `except (TypeError, ValueError)`
		did not catch, so the turn died over a number. Skipping is right and crashing is not: the
		work was done and the person is owed the answer, whatever the meter says."""
		total = {"prompt_tokens": 1}
		_accumulate_usage(total, {"prompt_tokens": float("inf"), "completion_tokens": float("nan")})

		self.assertEqual(total, {"prompt_tokens": 1})

	def test_two_calls_in_one_turn_total_the_extra_count(self):
		"""C4's own test, and the one that matters: the loop, not the helper. A turn with a tool call
		makes two calls, which is every turn this is sold on."""

		@tool
		def ping() -> str:
			"""Ping."""
			return "pong"

		model = FakeModel(
			[
				ChatResponse(
					content=None,
					tool_calls=[ToolCall(id="c1", name="ping", arguments={})],
					usage={"prompt_tokens": 5, "total_tokens": 7, "provider_cost_usd_micros": 4321},
				),
				_final(
					"done",
					usage={"prompt_tokens": 3, "total_tokens": 4, "provider_cost_usd_micros": 4321},
				),
			]
		)

		result = Agent(model=model, tools=[ping]).run("hi")

		self.assertEqual(result.usage["prompt_tokens"], 8)
		self.assertEqual(result.usage["total_tokens"], 11)
		# 8642, not 4321. This is the assertion the review names, and a single-call test stays green
		# through the defect it catches.
		self.assertEqual(result.usage["provider_cost_usd_micros"], 8642)


def _reply(model_name, usage=None):
	usage = usage or {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
	message = SimpleNamespace(content="hi", tool_calls=None)
	choice = SimpleNamespace(message=message, finish_reason="stop")
	reply = SimpleNamespace(choices=[choice], usage=SimpleNamespace(**usage))
	if model_name is not None:
		reply.model = model_name
	return reply


def _chunk(model_name=None, content=None, usage=None):
	delta = SimpleNamespace(content=content, tool_calls=None)
	choice = SimpleNamespace(delta=delta, finish_reason=None)
	chunk = SimpleNamespace(choices=[choice], usage=SimpleNamespace(**usage) if usage else None)
	if model_name is not None:
		chunk.model = model_name
	return chunk


class TestTheReplySaysWhatAnsweredIt(UnitTestCase):
	def test_a_reply_from_something_else_is_counted(self):
		response = _normalize(_reply("other-thing"), "the-one-asked-for")

		self.assertEqual(response.usage["served_model_mismatch"], 1)

	def test_a_reply_from_what_was_asked_for_adds_nothing(self):
		"""Absence is the ordinary case, and it has to stay absent rather than become a zero: a key
		that is always present teaches a consumer nothing, and the accumulator creates keys on first
		sight, so nothing needs one seeded."""
		response = _normalize(_reply("the-one-asked-for"), "the-one-asked-for")

		self.assertNotIn("served_model_mismatch", response.usage)

	def test_a_reply_that_does_not_say_is_not_counted_as_a_mismatch(self):
		"""Not knowing is not the same as knowing it differed, and only the second is a reason to
		refuse to price. A reply carrying no identifier at all must not be read as one."""
		self.assertNotIn("served_model_mismatch", _normalize(_reply(None), "asked").usage)
		self.assertNotIn("served_model_mismatch", _normalize(_reply(""), "asked").usage)
		self.assertNotIn("served_model_mismatch", _normalize(_reply("served"), None).usage)

	def test_the_provider_prefix_is_not_a_different_model(self):
		"""THE DEFECT A REVIEWER FOUND, and it made the counter fire on 100% of calls.

		`asked_for` is `Model.model_id`, and `Flow Model` VALIDATES that it is in `provider/model`
		form — `flow_model.py` refuses anything else in as many words. The client library strips that
		prefix before the request goes out, so the identifier that comes back on the reply is the
		bare model name and NEVER equals what was asked for. Every call mismatched, every turn
		became unpriceable, and the stored count was just a duplicate of the model-call count.

		The prefix is ROUTING SYNTAX, not identity: it says which library adapter places the call,
		not which model answers. Stripping it is therefore not the "helpful comparison" the next test
		refuses — the thing being compared is still exactly the model part, unlowercased and
		undated."""
		self.assertNotIn(
			"served_model_mismatch", _normalize(_reply("gpt-4o-mini"), "openai/gpt-4o-mini").usage
		)
		self.assertNotIn(
			"served_model_mismatch",
			_normalize(_reply("claude-sonnet-4-6"), "anthropic/claude-sonnet-4-6").usage,
		)

	def test_only_the_last_segment_is_the_model_and_a_route_of_its_own_still_counts(self):
		"""A prefix is stripped; a genuinely different name behind one is not excused by it."""
		self.assertEqual(_normalize(_reply("gpt-4o"), "openai/gpt-4o-mini").usage["served_model_mismatch"], 1)

	def test_a_trailing_slash_does_not_make_every_call_a_mismatch(self):
		"""The degenerate config, which the validator permits: `MODEL_ID_PATTERN` allows a trailing
		slash, `rsplit` then yields the empty string, and such a model counted on every single call —
		the same always-fires failure the prefix bug had, surviving in a corner of it."""
		self.assertNotIn("served_model_mismatch", _normalize(_reply("gpt4"), "openai/gpt4/").usage)

	def test_a_dated_build_behind_a_prefix_is_still_a_different_thing(self):
		"""The two halves together, which is the case this actually has to get right in production:
		the prefix goes, the date does not. Asking for a floating alias and being answered by one
		pinned build is the case with the largest price difference, and it is the whole reason the
		counter exists."""
		self.assertEqual(
			_normalize(_reply("gpt-4o-mini-2024-07-18"), "openai/gpt-4o-mini").usage["served_model_mismatch"],
			1,
		)

	def test_the_streamed_path_strips_the_prefix_too(self):
		"""Half the calls in production go the other way, and the first version of this counter was
		wrong on both."""
		stream = _consume_stream([_chunk("gpt-4o-mini", content="hi")], "openai/gpt-4o-mini")
		try:
			while True:
				next(stream)
		except StopIteration as done:
			response = done.value

		self.assertNotIn("served_model_mismatch", response.usage)

	def test_the_comparison_is_exact_and_a_dated_build_is_a_different_thing(self):
		"""Deliberately NOT a helpful comparison. Treating a floating alias and one pinned dated build
		as the same name is the case with the largest price difference between them, and therefore
		exactly the one worth being told about."""
		response = _normalize(_reply("a-name-2026-08-06"), "a-name")

		self.assertEqual(response.usage["served_model_mismatch"], 1)

	def test_a_streamed_reply_is_counted_the_same_way(self):
		"""The streamed path assembles its own counts, so it needs its own assertion or half the calls
		in production are unmeasured."""
		stream = _consume_stream(
			[
				_chunk("other-thing", content="hi"),
				_chunk("other-thing", usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
			],
			"the-one-asked-for",
		)
		try:
			while True:
				next(stream)
		except StopIteration as done:
			response = done.value

		self.assertEqual(response.usage["served_model_mismatch"], 1)
		self.assertEqual(response.usage["total_tokens"], 2)

	def test_a_streamed_reply_from_what_was_asked_for_adds_nothing(self):
		stream = _consume_stream([_chunk("asked", content="hi")], "asked")
		try:
			while True:
				next(stream)
		except StopIteration as done:
			response = done.value

		self.assertNotIn("served_model_mismatch", response.usage)

	def test_the_count_reaches_the_turn_total_through_the_accumulator(self):
		"""The two halves joined: the counter only means anything if it survives being summed."""
		total = {}
		_accumulate_usage(total, _normalize(_reply("other"), "asked").usage)
		_accumulate_usage(total, _normalize(_reply("other"), "asked").usage)

		self.assertEqual(total["served_model_mismatch"], 2)


# The counts the engine emits, and the whole of what it may emit. A module constant rather than a
# class attribute so that a reader looking for "what does a turn record" finds it without a class.
EMITTED = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})


class TestNoCountIsCapturedThatNothingCanUse(UnitTestCase):
	"""H4, decided: the engine does NOT capture a cached-input count, and that is a decision.

	Pricing one needs a cached rate to price it AGAINST, and the rate table is a doctype in another
	repository whose seven fields do not include one. Capturing the number here would therefore put a
	count in the record that nothing can turn into money — and the review's own instruction is that
	capturing a number and not using it is the one option not available, because the moment it exists
	someone reads it as evidence the estimate accounts for caching when the estimate does not.

	Dropping it also keeps the shipped caveat true. The caveat says an estimate cannot see cached
	input; that sentence stops being honest the day this side starts seeing it, and the caveat is not
	in this repository to amend.

	SO THIS IS NOT A TEST OF NOTHING. `_accumulate_usage` now sums EVERY key it is handed, which is
	what makes the drop fragile in a way it was not before: one line added to `_normalize` and a
	cached count flows all the way to the stored record with no further edit and no review. This pins
	the shape of what the engine emits so that line cannot land quietly. It fails RED when a cached
	count is captured — proved by mutation, not assumed.

	The exact platform-side change that would let this decision be reversed, recorded so that reversing
	it is a known piece of work rather than a discovery: add `cached_input_per_1k` (Currency) to
	`Veyqon Model Rate`'s `field_order`; price `(prompt_tokens - cached_prompt_tokens)` at the full
	input rate plus `cached_prompt_tokens` at the cached rate; and resolve a rate row that has no
	cached rate to `unpriceable` / `no-cached-rate` whenever the cached count is non-zero, rather than
	silently pricing it at full rate. Until all three exist, capturing the count is premature.
	"""

	def test_the_engine_emits_no_count_it_cannot_price(self):
		usage = _normalize(_reply("asked"), "asked").usage

		self.assertEqual(set(usage), EMITTED)

	def test_the_streamed_path_emits_the_same_set(self):
		"""Two code paths build this dictionary and only one of them is the one people read."""
		stream = _consume_stream(
			[
				_chunk("asked", content="hi"),
				_chunk("asked", usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
			],
			"asked",
		)
		try:
			while True:
				next(stream)
		except StopIteration as done:
			response = done.value

		self.assertEqual(set(response.usage), EMITTED)

	def test_the_only_key_that_may_join_them_is_the_mismatch_counter(self):
		"""The one addition this run made, named here so the set above is a whitelist and not a
		freeze: anything else appearing is a count someone added without deciding who prices it."""
		usage = _normalize(_reply("other"), "asked").usage

		self.assertEqual(set(usage), EMITTED | {"served_model_mismatch"})

	def test_a_cached_count_is_specifically_the_one_not_captured(self):
		"""Named rather than implied, so a failure says WHICH decision was reversed."""
		for key in ("cached_prompt_tokens", "cache_read_input_tokens", "cached_tokens"):
			with self.subTest(key=key):
				self.assertNotIn(key, _normalize(_reply("asked"), "asked").usage)
