# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import frappe

DEFAULT_TIMEOUT = 60


@dataclass
class ToolCall:
	id: str
	name: str
	arguments: dict[str, Any]
	# Set when the model emitted unparseable arguments; the agent feeds this back so it can retry
	# instead of the whole run failing.
	error: str | None = None


@dataclass
class ToolCallBegin:
	"""Streamed marker: the model has started emitting a tool call (name known, arguments still
	streaming). Lets the UI show the tool immediately instead of after the full arguments arrive."""

	id: str
	name: str


@dataclass
class ChatResponse:
	content: str | None
	tool_calls: list[ToolCall] = field(default_factory=list)
	finish_reason: str | None = None
	usage: dict[str, int] = field(default_factory=dict)


class Model:
	def __init__(
		self,
		name: str | None = None,
		*,
		model_id: str | None = None,
		api_key: str | None = None,
		base_url: str | None = None,
		params: dict[str, Any] | None = None,
		timeout: int = DEFAULT_TIMEOUT,
	):
		if name is not None:
			if model_id or api_key or base_url or params:
				raise ValueError("Pass either a Flow Model doc name or explicit kwargs, not both.")
			doc = frappe.get_doc("Flow Model", name)
			if not doc.enabled:
				raise ValueError(f"Flow Model {name!r} is disabled")
			model_id = doc.model_id
			api_key = doc.get_password("api_key", raise_exception=False)
			base_url = doc.base_url or None
			params = json.loads(doc.params) if doc.params else {}

		if not model_id:
			raise ValueError("model_id is required")

		# Fall back to the central Flow Provider store for anything not set on the model itself.
		provider_creds = resolve_provider_credentials(model_id)
		api_key = api_key or provider_creds.get("api_key")
		base_url = base_url or provider_creds.get("base_url")
		if provider_creds.get("extra_params"):
			params = {**provider_creds["extra_params"], **(params or {})}

		self.model_id = model_id
		self._api_key = api_key or None
		self.base_url = base_url
		self.params = params or {}
		self.timeout = timeout

	def chat(
		self,
		messages: str | list[dict[str, Any]],
		tools: list[dict[str, Any]] | None = None,
		*,
		stream: bool = False,
	) -> ChatResponse | Generator[str, None, ChatResponse]:
		"""Call the model. When `stream=True`, returns a generator that yields text deltas
		and returns the assembled `ChatResponse` via PEP 380 (`StopIteration.value`)."""
		import litellm

		if isinstance(messages, str):
			messages = [{"role": "user", "content": messages}]

		kwargs: dict[str, Any] = {
			"model": self.model_id,
			"api_key": self._api_key,
			"messages": messages,
			"timeout": self.timeout,
			**self.params,
		}
		if self.base_url:
			kwargs["api_base"] = self.base_url
		if tools:
			kwargs["tools"] = tools

		if stream:
			kwargs["stream"] = True
			kwargs["stream_options"] = {"include_usage": True}
			return _consume_stream(litellm.completion(**kwargs), self.model_id)

		return _normalize(litellm.completion(**kwargs), self.model_id)


def resolve_provider_credentials(model_id: str) -> dict[str, Any]:
	"""Look up central Flow Provider credentials for a model's provider."""
	try:
		import litellm

		provider = litellm.get_llm_provider(model_id)[1]
	except Exception:
		return {}

	if not provider or not frappe.db.exists("Flow Provider", provider):
		return {}

	doc = frappe.get_doc("Flow Provider", provider)
	if not doc.enabled:
		return {}

	return {
		"api_key": doc.get_password("api_key", raise_exception=False) or None,
		"base_url": doc.base_url or None,
		"extra_params": json.loads(doc.extra_params) if doc.extra_params else {},
	}


def _consume_stream(
	chunks: Any, asked_for: str | None = None
) -> Generator[str | ToolCallBegin, None, ChatResponse]:
	"""Yield text deltas (and a ToolCallBegin the moment each tool call's name is known) from a
	litellm stream; return the assembled ChatResponse at the end."""
	content_parts: list[str] = []
	served: str | None = None
	tool_calls_acc: dict[int, dict[str, str]] = {}
	announced: set[int] = set()
	usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
	finish_reason: str | None = None

	for chunk in chunks:
		served = served or getattr(chunk, "model", None)
		choices = getattr(chunk, "choices", None) or []
		if choices:
			choice = choices[0]
			delta = getattr(choice, "delta", None)
			if delta is not None:
				text = _attr(delta, "content")
				if text:
					content_parts.append(text)
					yield text
				for tc_delta in _attr(delta, "tool_calls") or []:
					index = _accumulate_tool_call(tool_calls_acc, tc_delta)
					slot = tool_calls_acc[index]
					if index not in announced and slot["id"] and slot["name"]:
						announced.add(index)
						yield ToolCallBegin(id=slot["id"], name=slot["name"])
			reason = _attr(choice, "finish_reason")
			if reason:
				finish_reason = reason

		usage_obj = getattr(chunk, "usage", None)
		if usage_obj is not None:
			usage = {
				"prompt_tokens": _attr(usage_obj, "prompt_tokens", 0) or 0,
				"completion_tokens": _attr(usage_obj, "completion_tokens", 0) or 0,
				"total_tokens": _attr(usage_obj, "total_tokens", 0) or 0,
			}

	usage.update(_served_mismatch(served, asked_for))

	return ChatResponse(
		content="".join(content_parts) or None,
		tool_calls=_finalize_tool_calls(tool_calls_acc),
		finish_reason=finish_reason,
		usage=usage,
	)


def _accumulate_tool_call(acc: dict[int, dict[str, str]], delta: Any) -> int:
	index = _attr(delta, "index", 0) or 0
	slot = acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
	call_id = _attr(delta, "id")
	if call_id:
		slot["id"] = call_id
	function = _attr(delta, "function")
	if function is not None:
		name = _attr(function, "name")
		if name:
			slot["name"] = name
		args = _attr(function, "arguments")
		if args:
			slot["arguments"] += args
	return index


def _finalize_tool_calls(acc: dict[int, dict[str, str]]) -> list[ToolCall]:
	calls: list[ToolCall] = []
	for index in sorted(acc):
		slot = acc[index]
		if not slot["id"] and not slot["name"]:
			continue
		calls.append(_build_tool_call(slot["id"], slot["name"], slot["arguments"]))
	return calls


def _build_tool_call(call_id: str, name: str, raw_args: str) -> ToolCall:
	"""Parse a tool call's raw arguments. Malformed arguments become a `ToolCall.error` the agent
	feeds back to the model to retry, rather than an exception that fails the whole run."""
	raw_args = raw_args or ""
	if not raw_args:
		return ToolCall(id=call_id, name=name, arguments={})
	try:
		arguments = json.loads(raw_args)
	except (TypeError, ValueError):
		return ToolCall(
			id=call_id,
			name=name,
			arguments={},
			error=f"Invalid JSON in arguments for {name!r}: {raw_args[:200]}. Resend the call with valid JSON.",
		)
	if not isinstance(arguments, dict):
		return ToolCall(
			id=call_id,
			name=name,
			arguments={},
			error=f"Arguments for {name!r} must be a JSON object, got: {raw_args[:200]}.",
		)
	return ToolCall(id=call_id, name=name, arguments=arguments)


def _normalize(response: Any, asked_for: str | None = None) -> ChatResponse:
	choice = response.choices[0]
	message = choice.message

	tool_calls = []
	for raw_call in getattr(message, "tool_calls", None) or []:
		function = getattr(raw_call, "function", None) or {}
		name = _attr(function, "name", "")
		raw_args = _attr(function, "arguments", "") or ""
		tool_calls.append(_build_tool_call(_attr(raw_call, "id", ""), name, raw_args))

	usage_obj = getattr(response, "usage", None)
	usage = {
		"prompt_tokens": _attr(usage_obj, "prompt_tokens", 0) or 0,
		"completion_tokens": _attr(usage_obj, "completion_tokens", 0) or 0,
		"total_tokens": _attr(usage_obj, "total_tokens", 0) or 0,
	}
	usage.update(_served_mismatch(getattr(response, "model", None), asked_for))

	return ChatResponse(
		content=getattr(message, "content", None),
		tool_calls=tool_calls,
		finish_reason=getattr(choice, "finish_reason", None),
		usage=usage,
	)


def _served_mismatch(served: str | None, asked_for: str | None) -> dict[str, int]:
	"""`{"served_model_mismatch": 1}` when the call was answered by something other than what was asked
	for, and `{}` when it was not or when we cannot tell.

	WHY A COUNT AND NOT A NAME. The reply carries the identifier of whatever actually answered, and that
	need not be what was requested: the request keyword dictionary is built as `{..., **self.params}`
	and those params are administrator-settable, so a configured fallback can send a call somewhere else
	entirely. Cost is then worked out against the rate for the thing we asked for while the money was
	spent on the thing that answered — and the record would label that figure with the most authoritative
	source it has. What stops that is knowing it happened. The name itself cannot ride along: the counts
	dictionary holds integers and is summed key by key at two levels, so a string in it would break the
	addition. A count fits, sums, and answers the only question a consumer needs to ask of it.

	WHY THE PROVIDER PREFIX COMES OFF FIRST, and it is the difference between a counter and noise.
	`asked_for` is `Model.model_id`, which the `Flow Model` doctype validates into `provider/model`
	form. The client library strips that prefix before the request leaves, so the identifier on the
	reply is the bare model name and never equals what was asked for. The first version of this
	function compared the two whole strings and therefore counted a mismatch on **100% of calls**:
	every turn unpriceable, and a stored count that was nothing but a duplicate of the model-call
	count. A reviewer caught it by calling the library rather than by reading the function, and none
	of the fixtures could see it because every one was an invented bare name with no prefix on it.

	(That validation is the doctype's, not this class's: a `Model` constructed directly with
	`model_id=` — the code-only Agent path — never passes through it, so a bare name with no slash
	reaches here. `rsplit` returns the whole string in that case and the comparison is still right.
	An earlier draft of this docstring claimed the shape was guaranteed; it is not.)

	WHAT THIS DELIBERATELY DOES NOT SEE, stated because the docstring below motivates the counter
	with exactly this case. A configured fallback changes the PROVIDER, and comparing only the model
	part discards it: a call written as `openai/gpt-4o` and answered from Azure or OpenRouter, at a
	different rate, records nothing here. For pricing the adapter IS part of the identity, so calling
	the prefix "mere routing syntax" would be wrong. The reason it is dropped anyway is that the
	prefix on the REQUEST and the name on the REPLY are not the same kind of thing, so comparing them
	can only ever fire always or never. The provider that actually served is available — the client
	library puts it on the response's private `_hidden_params` under `custom_llm_provider` — and
	reading it would close this: compare it against `asked_for.split("/", 1)[0]` and count a mismatch
	independently of the model name. It is not done here because it couples the engine to a private
	attribute of a third-party library, which is a change that deserves its own spec rather than a
	line smuggled into a bug fix. **OPEN, and narrowed on purpose: this counter answers "a different
	model", not yet "a different provider".**

	WHY THE REST OF THE COMPARISON IS EXACT, deliberately. Past the prefix nothing is normalised: a
	"helpful" version stripping a trailing date or lowercasing would treat two genuinely different
	things — the floating alias and one pinned dated build — as the same, which is the case with the
	largest price difference and therefore exactly the one worth knowing about. So asking for
	`openai/gpt-4o-mini` and being answered by `gpt-4o-mini` counts as no mismatch, while being
	answered by `gpt-4o-mini-2024-07-18` counts as one. That second case is common against real
	providers, and it is meant to be: the consumer's correct response to it is to decline to price,
	not to guess which build's rate applied.

	WHAT IS STILL MISSING, stated here rather than invented: **nothing in this repository reads this
	count yet.** Turning a non-zero count into a refusal to price the turn belongs to the code that
	prices it, and that code lives in another repository and does not exist. This function builds the
	counter and nothing else; a consumer that finds it non-zero must decline to price rather than price
	against a rate that had nothing to do with the spend.
	"""
	if not served or not asked_for:
		return {}
	# `rsplit` and not `split`: a model part may itself hold slashes (`openrouter/meta-llama/llama-3`),
	# and what the library sends on is everything the provider adapter did not consume. The `rstrip`
	# handles the degenerate config the validator happens to permit — a trailing slash leaves the last
	# segment EMPTY, an empty segment matches nothing, and such a model counted on every single call:
	# the always-fires bug again, surviving in a corner of its own fix. `or asked_for` is the floor
	# for a value that is nothing but slashes.
	bare = asked_for.rstrip("/").rsplit("/", 1)[-1] or asked_for
	# Both spellings, so a provider that echoes the prefix back is not counted either — the question
	# is which model answered, and neither spelling changes that answer.
	if served in (asked_for, bare):
		return {}
	return {"served_model_mismatch": 1}


def _attr(obj: Any, key: str, default: Any = None) -> Any:
	if obj is None:
		return default
	if isinstance(obj, dict):
		return obj.get(key, default)
	return getattr(obj, key, default)
