# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S25 — a paused run has two doors, and until this file they let in two different identities.

A person asks for something. The turn pauses on an approval. Somebody — not necessarily the same
person — answers it. **Whose permissions do the remaining tool calls run with?**

There are exactly two ways into that pause in this engine (`grep -rn "resume(" flow/ --include=*.py`
outside the tests: `flow/api/api.py:61` and `flow/flow/doctype/flow_session/flow_session.py`):

  1. **the whitelisted door** — `flow.api.api.resume_run`, which the Desk chat panel calls;
  2. **the in-process door** — `load_session(...).resume(...)`, which another application's
     background worker calls after it has decided for itself who to be.

Both end in `FlowSession.resume`, and until this file **neither of them said anything at all about
identity**: the continuation ran as whatever `frappe.session.user` happened to be. On door 1 that
is the ANSWERER. So an answerer with wider reach than the requester ran the rest of the requester's
turn with the answerer's permissions — every tool call the model made after the approved one, plus
the prompt rebuild, which reads the acting user's display name, time zone and personal memories.

Nothing here is measured from a field. A fixture tool records `frappe.session.user` **and what that
identity could actually read**, through `frappe.get_list`, which is the call that applies
permissions (`frappe.get_all` does not, and a test written on it would pass for both answers).

The boundary is `Flow Tool`: its doctype JSON grants read to `System Manager` and to nobody else,
so a plain desk user is refused and a System Manager is not. **The positive control is required**,
and it is `test_the_boundary_is_real_*`: an empty list is equally consistent with there being no
`Flow Tool` row on the bench at all, in which case nothing was ever tested.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flow.lib.model import ChatResponse, Model, ToolCall

REQUESTER = "s25-requester@example.com"
APPROVER = "s25-approver@example.com"
WIDE_REQUESTER = "s25-wide-requester@example.com"

# What the fixture tools below saw when they ran. Module-level because a `Flow Tool` of type
# `Imported` is reached by dotted path, not by closure.
WITNESS: list[dict[str, Any]] = []


def record_who_is_acting(label: str = "x") -> str:
	"""Record something. Needs approval."""
	seen: dict[str, Any] = {"label": label, "user": frappe.session.user}
	try:
		# `get_list`, never `get_all`: only this one applies the permission rules, and a test
		# written on `get_all` would record the same number for both identities and pass
		# whichever way the engine answered.
		seen["readable"] = frappe.get_list("Flow Tool", pluck="name", limit_page_length=0)
	except frappe.PermissionError:
		seen["readable"] = None
	WITNESS.append(seen)
	return "recorded"


def write_a_gated_record(title: str = "S25 Written") -> str:
	"""Write something. Needs approval."""
	doc = frappe.get_doc(
		{
			"doctype": "Flow Tool",
			"title": title,
			"slug": f"s25_written_{frappe.generate_hash(length=6)}",
			"type": "Imported",
			"description": "Written by the continuation.",
			"import_path": "flow.tools.builtins.find_doctypes",
		}
	).insert()
	WITNESS.append({"label": "wrote", "user": frappe.session.user, "wrote": doc.name})
	return doc.name


def _ensure_user(email: str, *roles: str) -> str:
	"""A desk user with the roles named, and no others.

	`Translator` grants nothing on `Flow Tool`; it is there so the user is created as a DESK user
	and picks up the automatic desk role. A roleless user is a website user, which is refused for
	reasons that have nothing to do with what this file measures.
	"""
	wanted = ("Translator", *roles)
	for role in wanted:
		# The bench does not ship every role a test wants to tell two identities apart with.
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": role} for role in wanted],
			}
		).insert(ignore_permissions=True)
	else:
		# A row surviving an aborted run would otherwise be returned exactly as found, without
		# the roles this file's whole boundary rests on.
		doc = frappe.get_doc("User", email)
		doc.add_roles(*wanted)
	frappe.clear_cache(user=email)
	return email


def _pause(call_id: str, slug: str, arguments: dict[str, Any] | None = None) -> ChatResponse:
	return ChatResponse(
		content=None,
		tool_calls=[ToolCall(id=call_id, name=slug, arguments=arguments or {"label": "first"})],
		finish_reason="tool_calls",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


def _final(text: str = "done") -> ChatResponse:
	return ChatResponse(
		content=text,
		finish_reason="stop",
		usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
	)


def _scripted_stream(response: ChatResponse):
	if response.content:
		yield response.content
	return response


def _chat(response: ChatResponse, calls: list[int] | None = None):
	"""A model double that answers BOTH shapes, because the streamed doors need the streamed one.

	`return_value=<ChatResponse>` is not a model double for a streamed run: `_loop_stream` calls
	`next()` on what `chat` returns, so a bare response raises `'ChatResponse' object is not an
	iterator`, the run is marked Failed and nothing is persisted. The first version of this file
	did exactly that, and its streamed sub-tests still passed — they asserted on what the tool
	recorded, which happens before the model is consulted again. A test that is green with the
	half after its assertion broken is the same kind of hole this file exists to close, so it is
	written down rather than quietly fixed.
	"""

	def chat(self, messages, tools=None, *, stream=False):
		if calls is not None:
			calls.append(len(messages))
		return _scripted_stream(response) if stream else response

	return chat


class TwoDoorsCase(IntegrationTestCase):
	"""A gated tool, an agent that owns it, and the two ways to answer its question.

	Every test below runs its body against BOTH doors, in the same test. A check that holds on one
	door and is never run against the other is precisely the hole this file exists for: run 3 and
	run 4 of the dispatching application both recorded "the task runs as the requester" while
	driving every proof through the door where that sentence was false.
	"""

	DOORS = ("whitelisted", "in-process", "whitelisted-stream", "in-process-stream")

	def setUp(self):
		WITNESS.clear()
		frappe.set_user("Administrator")
		self.requester = _ensure_user(REQUESTER)
		self.approver = _ensure_user(APPROVER, "System Manager")
		self.wide_requester = _ensure_user(WIDE_REQUESTER, "System Manager")
		self.model_doc = frappe.get_doc(
			{
				"doctype": "Flow Model",
				"title": "S25 Model",
				"model_id": "openai/gpt-4o-mini",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.witness_tool = self._tool("record_who_is_acting", "S25 Witness")
		self.write_tool = self._tool("write_a_gated_record", "S25 Writer")
		self.agent_doc = frappe.get_doc(
			{
				"doctype": "Flow Agent",
				"title": "S25 Agent",
				"model": self.model_doc.name,
				"instructions": "Be terse.",
				"enabled": 1,
				"tools": [{"tool": self.witness_tool.name}, {"tool": self.write_tool.name}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		WITNESS.clear()

	def _tool(self, func: str, title: str):
		return frappe.get_doc(
			{
				"doctype": "Flow Tool",
				"title": title,
				"slug": f"{func}_{frappe.generate_hash(length=6)}",
				"type": "Imported",
				"description": "A gated fixture tool.",
				"import_path": f"flow.tests.test_s25_two_doors_one_identity.{func}",
				"requires_confirmation": 1,
			}
		).insert(ignore_permissions=True)

	# --- the fixture ---------------------------------------------------------

	def _paused_run(self, as_user: str, slug: str, arguments: dict[str, Any] | None = None):
		"""Start a turn as `as_user` that pauses on `slug`'s approval question. Returns the run."""
		from flow.api.api import start_run

		WITNESS.clear()
		frappe.set_user(as_user)
		with patch.object(Model, "chat", new=_chat(_pause("c1", slug, arguments))):
			started = start_run("please do it", agent=self.agent_doc.name)
		self.assertEqual(started["status"], "Paused", started)
		self.assertEqual(WITNESS, [])  # the question was asked before anything ran
		return frappe.get_doc("Flow Run", started["name"])

	def _answer(self, door: str, run, answers: dict[str, Any], as_user: str):
		"""Answer the pause through `door`, acting as `as_user`. One behaviour, four ways in."""
		from flow.api.api import resume_run
		from flow.lib.session import load_session

		# Only when it differs. Setting it unconditionally would clear the very `sid`, `session.data`
		# and `form_dict` that `TestTheCallersOwnRequestComesBack` plants to watch them come back.
		if frappe.session.user != as_user:
			frappe.set_user(as_user)
		self._warm_the_answerers_caches(as_user)
		if door == "whitelisted":
			return resume_run(run.name, answers)
		if door == "in-process":
			return load_session(run.session).resume(answers)
		if door == "whitelisted-stream":
			response = resume_run(run.name, answers, stream=True)
			# A streamed response is lazy: nothing has run until the body is consumed.
			return b"".join(response.iter_encoded())
		if door == "in-process-stream":
			return list(load_session(run.session).resume(answers, stream=True))
		raise AssertionError(f"unknown door {door!r}")

	def _warm_the_answerers_caches(self, as_user: str) -> None:
		"""Make the answerer's permission caches HOT before the resume, as a real request does.

		A REPORTED NEGATIVE, because the opposite was expected. Probe P3 replaced
		`frappe.set_user(user)` in `_acting_as` with a bare `frappe.local.session.user = user` —
		the identity as a field, with the answerer's permission caches left standing — and this
		file stayed GREEN, with the caches cold AND with them warmed here. It is an EQUIVALENT
		mutation on the permission path, not a surviving one: every cache the check consults is
		keyed by the user (`frappe/permissions.py` `get_role_permissions` keys on
		`(doctype, user, is_owner)`, and `get_roles` takes the user as an argument), so changing
		the name is enough to change the answer.

		`set_user` is kept anyway, and this is the honest reason: it is also the only thing that
		drops `local.cache` and `local.user_perms`, which are NOT keyed by user, and a fix that
		relied on the keying above would be relying on somebody else's cache design.

		The warming stays because it is what a real request looks like by the time it reaches a
		resume, and a fixture whose caches are all cold is a fixture that cannot see a cache bug.
		"""
		frappe.get_roles()
		with contextlib.suppress(frappe.PermissionError):
			frappe.get_list("Flow Tool", pluck="name", limit_page_length=1)

	def _approve_through(self, door: str, *, requester: str, approver: str, slug: str | None = None):
		"""The whole shape: a requester's turn pauses, `approver` approves it through `door`."""
		WITNESS.clear()
		run = self._paused_run(requester, slug or self.witness_tool.slug)
		with patch.object(Model, "chat", new=_chat(_final())):
			self._answer(door, run, {"c1": "Approve"}, approver)
		return run

	def _only_witness(self, door: str) -> dict[str, Any]:
		self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")
		return WITNESS[0]


class TestWhoTheContinuationRunsAs(TwoDoorsCase):
	"""THE DECISION, ENFORCED: the work runs as the REQUESTER, and identically on both doors.

	The approver is AUTHORISING, not PERFORMING. See the run log for the argument; the short form
	is that the opposite rule lets a requester gain reach by asking somebody wider to press a
	button, with nothing on the card saying so, while this rule's worst case is a refusal after an
	approval — visible, safe, and nothing done.
	"""

	def test_the_continuation_runs_as_the_requester_on_both_doors(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				self._approve_through(door, requester=self.requester, approver=self.approver)
				seen = self._only_witness(door)
				self.assertEqual(
					seen["user"],
					self.requester,
					f"door={door}: the approved work ran as {seen['user']!r}, "
					f"not as the person who asked for it",
				)

	def test_an_approver_with_wider_permissions_does_not_widen_the_requesters_reach(self):
		"""THE ESCALATION TEST, AND IT IS THE POINT OF THE RUN.

		Asserted from what the work could actually READ, not from `frappe.session.user`: a fix
		that set the name and left the permission cache alone would pass the test above and fail
		this one.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				self._approve_through(door, requester=self.requester, approver=self.approver)
				seen = self._only_witness(door)
				self.assertIsNone(
					seen["readable"],
					f"door={door}: the requester's turn read {seen['readable']!r} rows of a "
					f"doctype the requester may not read — the approver's reach was applied",
				)

	def test_the_boundary_is_real_the_wider_identity_does_read_through_the_same_fixture(self):
		"""The positive control, and without it the test above is worth nothing.

		An empty read is equally consistent with there being no row to read at all. The same
		fixture, the same door, the same tool — with a REQUESTER who holds the wider role — must
		come back non-empty.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				self._approve_through(door, requester=self.wide_requester, approver=self.approver)
				seen = self._only_witness(door)
				self.assertEqual(seen["user"], self.wide_requester)
				self.assertTrue(
					seen["readable"],
					f"door={door}: the wider identity read nothing either, so the boundary the "
					f"other tests rest on was never exercised",
				)

	def test_the_prompt_the_model_is_given_is_rebuilt_as_the_requester_too(self):
		"""Not only the tools. `FlowSession._build_prompt_messages` reads the acting user for the
		display name, the time zone and the personal memory block; rebuilt under the answerer it
		put the ANSWERER's name into the requester's conversation.
		"""
		from flow.api.api import resume_run

		run = self._paused_run(self.requester, self.witness_tool.slug)
		seen_as: list[str] = []

		original = type(frappe.get_doc("Flow Session", run.session))._build_prompt_messages

		def spy(self_session):
			seen_as.append(frappe.session.user)
			return original(self_session)

		frappe.set_user(self.approver)
		with (
			patch.object(type(frappe.get_doc("Flow Session", run.session)), "_build_prompt_messages", spy),
			patch.object(Model, "chat", new=_chat(_final())),
		):
			resume_run(run.name, {"c1": "Approve"})

		self.assertEqual(seen_as, [self.requester], f"the prompt was rebuilt as {seen_as!r}")


class TestTheOtherAnswers(TwoDoorsCase):
	"""Deny, and answer twice. Both on both doors."""

	def test_a_denial_creates_nothing_on_both_doors(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				before = frappe.db.count("Flow Tool")
				run = self._paused_run(self.wide_requester, self.write_tool.slug, {"title": "S25 Denied"})
				asked_again: list[int] = []
				with patch.object(Model, "chat", new=_chat(_final(), asked_again)):
					self._answer(door, run, {"c1": "Deny"}, self.approver)
				self.assertEqual(WITNESS, [], f"door={door}: a denial ran the tool")
				self.assertEqual(frappe.db.count("Flow Tool"), before, f"door={door}")
				# And it STOPS. Without this the test passes with `_has_denial` returning False
				# (probe P9, green): the tool still does not run, because `_resolve_confirmation`
				# refuses it call by call -- but the turn carries on and the model gets another go
				# at the thing it was just refused. "Creates nothing" was never the whole rule.
				self.assertEqual(
					asked_again, [], f"door={door}: a denial went back to the model {asked_again}"
				)
				self.assertEqual(frappe.get_doc("Flow Run", run.name).status, "Completed", door)

	def test_the_same_write_through_the_same_door_DOES_run_on_approve(self):
		"""The positive control for the denial test: the tool is reachable and does write."""
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				before = frappe.db.count("Flow Tool")
				run = self._paused_run(self.wide_requester, self.write_tool.slug, {"title": "S25 Approved"})
				asked_again: list[int] = []
				with patch.object(Model, "chat", new=_chat(_final(), asked_again)):
					self._answer(door, run, {"c1": "Approve"}, self.approver)
				# The control on the denial test's silence: an APPROVAL does go back to the model.
				self.assertEqual(len(asked_again), 1, f"door={door}: {asked_again}")
				self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")
				self.assertEqual(WITNESS[0]["user"], self.wide_requester, f"door={door}")
				self.assertEqual(frappe.db.count("Flow Tool"), before + 1, f"door={door}")

	def test_a_second_answer_to_an_answered_pause_is_refused_on_both_doors(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				run = self._approve_through(door, requester=self.requester, approver=self.approver)
				self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "Approve"}, self.approver)
				self.assertEqual(len(WITNESS), 1, f"door={door}: the second answer ran it again")


class TestTheRequesterMayLackThePermission(TwoDoorsCase):
	"""The cost of the decision, stated out loud and tested.

	A requester who cannot do the thing gets a refusal AFTER the approval. That is the failure this
	run chose, over the alternative of letting the approval carry the approver's reach. What it may
	NOT be is a traceback, a 500, or a run left `Running` forever.
	"""

	def test_the_refusal_is_a_sentence_and_nothing_is_written_on_both_doors(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				before = frappe.db.count("Flow Tool")
				run = self._paused_run(self.requester, self.write_tool.slug, {"title": "S25 Refused"})
				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, self.approver)

				self.assertEqual(frappe.db.count("Flow Tool"), before, f"door={door}: it wrote")
				self.assertEqual(WITNESS, [], f"door={door}: the tool body completed")

				finished = frappe.get_doc("Flow Run", run.name)
				rows = frappe.get_doc("Flow Session", run.session).messages
				where = (
					f"door={door} status={finished.status!r} error={finished.error!r} "
					f"roles={[r.role for r in rows]}"
				)
				self.assertIn(finished.status, ("Completed", "Failed"), where)

				told = [row for row in rows if row.role == "tool"]
				self.assertTrue(told, f"{where}: nothing was recorded for the approved call")
				payload = json.loads(told[-1].content)
				self.assertIn("error", payload, f"{where}: {payload}")
				said = payload["error"]
				self.assertTrue(said.strip(), f"{where}: the refusal is empty: {payload}")
				# A sentence, and one that says the two things a person and a model both need:
				# it did not happen, and it must not be reported as though it did.
				self.assertIn("not carried out", said, where)
				self.assertIn("not allowed", said, where)
				self.assertIn("Do not report it as done", said, where)
				# CLAUDE.md rule 3: the model may not be told what it is running on.
				for word in ("Frappe", "Flow", "ERPNext", "MariaDB", "DocType", "doctype"):
					self.assertNotIn(word, said, f"{where}: the refusal names the platform")

	def test_an_empty_failure_from_anything_else_is_not_called_a_permission_refusal(self):
		"""The control on the sentence above: `_failure_sentence` must not label every silent
		exception a permission problem, because that would be a guess printed as a fact."""
		from flow.lib.agent import _failure_sentence

		self.assertIn("not allowed", _failure_sentence(frappe.PermissionError()))
		self.assertNotIn("not allowed", _failure_sentence(KeyError()))
		self.assertIn("reported no reason", _failure_sentence(KeyError()))
		# And a failure that DOES speak is still passed through verbatim.
		self.assertEqual(_failure_sentence(ValueError("amount must be positive")), "amount must be positive")


class TestItFailsClosed(TwoDoorsCase):
	"""If the requester cannot be acted as, the resume STOPS.

	The tempting fallback — carry on as whoever is answering — is the defect itself, so it is
	tested that it does not happen rather than left to be obvious.
	"""

	def test_a_run_whose_owner_is_disabled_cannot_be_continued_on_either_door(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run(self.requester, self.witness_tool.slug)
				frappe.set_user("Administrator")
				frappe.db.set_value("User", self.requester, "enabled", 0)
				frappe.clear_cache(user=self.requester)
				try:
					with patch.object(Model, "chat", new=_chat(_final())):
						with self.assertRaises(frappe.ValidationError):
							self._answer(door, run, {"c1": "Approve"}, self.approver)
					self.assertEqual(WITNESS, [], f"door={door}: it ran anyway")
				finally:
					frappe.set_user("Administrator")
					frappe.db.set_value("User", self.requester, "enabled", 1)
					frappe.clear_cache(user=self.requester)

	def test_a_run_whose_owner_is_gone_cannot_be_continued_on_either_door(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run(self.requester, self.witness_tool.slug)
				frappe.set_user("Administrator")
				frappe.db.set_value("Flow Run", run.name, "owner", "s25-nobody@example.com")
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "Approve"}, self.approver)
				self.assertEqual(WITNESS, [], f"door={door}: it ran anyway")

	def test_the_same_run_with_its_owner_intact_DOES_continue(self):
		"""The positive control: the two tests above must fail for the reason they name, and not
		because the fixture stopped being resumable."""
		for door in self.DOORS:
			with self.subTest(door=door):
				self._approve_through(door, requester=self.requester, approver=self.approver)
				self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")


class TestTheCallersOwnRequestComesBack(TwoDoorsCase):
	"""`frappe.set_user` clears four things belonging to the REQUEST, not to the acting user.

	Measured from `frappe/__init__.py` (v16.31.0): it overwrites `session.sid` with the user id and
	empties `session.data` and `local.form_dict`. A resume that left those cleared would hand a
	whitelisted call back to the framework with its own arguments gone.
	"""

	def test_the_answerers_session_and_form_are_exactly_as_they_were(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				run = self._paused_run(self.requester, self.witness_tool.slug)
				frappe.set_user(self.approver)
				frappe.local.session.sid = "s25-a-real-session-id"
				frappe.local.session.data = frappe._dict(marker="kept")
				frappe.local.form_dict = frappe._dict(cmd="flow.api.api.resume_run")

				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, self.approver)

				self.assertEqual(frappe.session.user, self.approver, f"door={door}")
				self.assertEqual(frappe.session.sid, "s25-a-real-session-id", f"door={door}")
				self.assertEqual(frappe.session.data.get("marker"), "kept", f"door={door}")
				self.assertEqual(frappe.local.form_dict.get("cmd"), "flow.api.api.resume_run", f"door={door}")

	def test_the_answerer_does_not_carry_the_requesters_permissions_out_of_the_resume(self):
		"""The other half, and the one that matters: `set_user` raises caches, and putting the
		name back without dropping them would leave the ANSWERER reading as the REQUESTER."""
		for door in self.DOORS:
			with self.subTest(door=door):
				run = self._paused_run(self.requester, self.witness_tool.slug)
				frappe.set_user(self.approver)
				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, self.approver)
				self.assertTrue(
					frappe.get_list("Flow Tool", pluck="name", limit_page_length=0),
					f"door={door}: the answerer lost their own reach after the resume",
				)


class TestTheANSWERERDoesNotGainReachEITHER(TwoDoorsCase):
	"""THE REVIEWER'S HIGH 1, AND IT WAS A REGRESSION THIS RUN INTRODUCED.

	T1b argued one direction only — an answerer must not lend permissions to a requester — and the
	fix for it lends in the other: the remainder of the turn runs as `run.owner`, whoever that is.

	`flow/triggers/triggers.py:75` runs a trigger as its configured `run_as`, so a trigger's
	`Flow Run.owner` is a service account, possibly `Administrator`. Such a run pauses whenever
	`auto_approve` is off. `assert_run_owner` admits a non-owner through `Flow Run` `write`, which
	only `System Manager` holds. So before this run's change a System Manager answering that pause
	ran the remainder as THEMSELVES and was refused; after it they ran it as the service account —
	including up to `max_iterations` further model calls nobody was shown. **The answerer gained
	reach by pressing a button**, which is the same sentence the run was commissioned to make false.

	So the rule is not "perform as the requester" on its own. It is: **an answerer may authorise
	only into reach they already have, and the work then runs within the requester's.** The
	effective authority is the intersection. The guard is fail-closed and role-level, and says so:
	roles are not the whole of Frappe's permission model (user permissions and document sharing sit
	underneath), so this refuses a superset of what it must and never a subset.
	"""

	def setUp(self):
		super().setUp()
		# A requester holding a role the answerer does not. `Blogger` is arbitrary and grants
		# nothing here; what matters is that the approver has never been given it.
		self.narrow_approver = _ensure_user("s25-narrow-approver@example.com", "System Manager")
		self.wider_requester = _ensure_user("s25-wider-requester@example.com", "Blogger")

	def test_a_requester_wider_than_the_answerer_is_refused_on_every_door(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run(self.wider_requester, self.witness_tool.slug)
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "Approve"}, self.narrow_approver)
				self.assertEqual(WITNESS, [], f"door={door}: it ran anyway")

	def test_the_same_run_answered_by_someone_who_HOLDS_that_role_does_continue(self):
		"""The positive control, and it is what stops the guard above being 'refuse everything'."""
		holder = _ensure_user("s25-role-holder@example.com", "System Manager", "Blogger")
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run(self.wider_requester, self.witness_tool.slug)
				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, holder)
				self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")
				self.assertEqual(WITNESS[0]["user"], self.wider_requester, f"door={door}")

	def test_answering_your_own_question_is_never_refused(self):
		"""The commonest case of all, and the guard must not touch it."""
		for door in self.DOORS:
			with self.subTest(door=door):
				self._approve_through(door, requester=self.wider_requester, approver=self.wider_requester)
				self.assertEqual(len(WITNESS), 1, f"door={door} witness={WITNESS}")


class TestTheStreamDoesNotLeaveTheIdentityInstalled(TwoDoorsCase):
	"""THE REVIEWER'S HIGH 2.

	A generator suspended at a `yield` does not unwind its `with`, and `frappe.session.user` is
	process-global. `_resumed_as` originally wrapped the WHOLE `yield from`, so from the first
	advance until the generator was exhausted every frame that ran BETWEEN events — the persistence
	loop, the SSE serialiser, the WSGI writer — ran as the requester. On a client disconnect
	`GeneratorExit` is raised at the `yield` inside `stream_with_persistence`, whose `finally`
	(`mark_failed`, the flag reset) therefore ran as the requester too; and a consumer that
	abandons the generator without closing it never restores the identity at all.
	"""

	def test_the_callers_identity_is_back_between_every_event(self):
		from flow.lib.session import load_session

		run = self._paused_run(self.requester, self.witness_tool.slug)
		frappe.set_user(self.approver)
		seen: list[str] = []
		with patch.object(Model, "chat", new=_chat(_final())):
			for _event in load_session(run.session).resume({"c1": "Approve"}, stream=True):
				seen.append(frappe.session.user)
		self.assertEqual(WITNESS[0]["user"], self.requester)
		self.assertEqual(
			set(seen), {self.approver}, f"the identity was left installed between events: {seen}"
		)

	def test_abandoning_the_stream_puts_the_callers_identity_back(self):
		"""The disconnect. `close()` is what a WSGI server does to an abandoned response."""
		from flow.lib.session import load_session

		run = self._paused_run(self.requester, self.witness_tool.slug)
		frappe.set_user(self.approver)
		with patch.object(Model, "chat", new=_chat(_final())):
			events = load_session(run.session).resume({"c1": "Approve"}, stream=True)
			next(events)
			next(events)
			events.close()
		self.assertEqual(frappe.session.user, self.approver, "the requester was left installed")


class TestTheGuardItselfFailsClosed(TwoDoorsCase):
	"""THE SECOND REVIEWER'S FINDINGS AGAINST MY OWN GUARD.

	1. **`Administrator` is not a role set.** `frappe.permissions.get_roles` special-cases it as
	   "every `Role` row on the site", so the role arithmetic refused an Administrator-owned run
	   only by ACCIDENT — and the accident is removable by the very actor the guard defends
	   against: a System Manager holds `User` write and may assign themselves every role, which is
	   permitted and no escalation in itself. Administrator's real reach is not made of roles at
	   all (`frappe/permissions.py`: `if user == "Administrator": return True`, a bypass no role
	   can grant). So it is decided BEFORE the arithmetic and never by it.
	2. **The arithmetic failed OPEN on an empty acting user.** `frappe.get_roles` DISCARDS its
	   argument when `local.session.user` is falsy and returns `["Guest"]` for both sides, so the
	   difference was empty and the guard passed silently — in a function whose sibling is
	   documented as fail-closed.
	"""

	def test_administrator_is_refused_even_when_the_role_difference_is_empty(self):
		"""Mocked deliberately, and this is the point: the rule must hold INDEPENDENTLY of what
		the arithmetic says, because the arithmetic is what the attacker can arrange."""
		from flow.flow.doctype.flow_session.flow_session import _the_answerer_may_not_gain_reach

		frappe.set_user(self.approver)
		with patch.object(frappe, "get_roles", return_value=["System Manager"]):
			# The control: with this mock the difference IS empty, so only an explicit rule refuses.
			self.assertEqual(
				set(frappe.get_roles("Administrator")) - set(frappe.get_roles(self.approver)), set()
			)
			with self.assertRaises(frappe.ValidationError):
				_the_answerer_may_not_gain_reach("Administrator")

	def test_administrator_answering_their_own_run_is_not_refused(self):
		from flow.flow.doctype.flow_session.flow_session import _the_answerer_may_not_gain_reach

		frappe.set_user("Administrator")
		_the_answerer_may_not_gain_reach("Administrator")  # must not raise

	def test_an_empty_acting_user_is_refused_rather_than_waved_through(self):
		from flow.flow.doctype.flow_session.flow_session import _the_answerer_may_not_gain_reach

		frappe.local.session.user = ""
		try:
			with self.assertRaises(frappe.ValidationError):
				_the_answerer_may_not_gain_reach(self.requester)
		finally:
			frappe.set_user("Administrator")
