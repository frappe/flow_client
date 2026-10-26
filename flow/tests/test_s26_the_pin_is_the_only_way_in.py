# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""S26 — the three holes S25 left open, and the invariant that ties the card to the body.

S25 pinned the continuation of a paused run to the REQUESTER. Three things it did not do, all
recorded as OPEN in run 17's report and all closed here:

  1. **The runtime was assembled OUTSIDE the pin.** `flow.lib.session.load_session` resolves the
     `Flow Agent`, its model and its tool set as the ANSWERER, before `FlowSession.resume` is
     entered — so the pin governed the tool bodies but not the inventory they were drawn from,
     and `FlowAgent.assemble` runs a real `frappe.has_permission("Flow Model", "read", ...)`
     under whoever happened to be calling. A pin with a second way in is a convention.
  2. **A denial was gated as though it writes.** The reach guard refuses an answerer who does not
     hold what the requester holds — correct for an approval, wrong for a DENIAL, which executes
     nothing at all (`Agent._resolve_confirmation` returns a rejection string, every approved
     sibling is withheld, and `_stopped_result` ends the turn with zero further model calls). A
     service-account run that nobody is permitted to approve therefore had no way out of `Paused`
     through the card at all.
  3. **`resume_run`'s `run_name` was discarded.** `FlowSession.resume` re-queried for the NEWEST
     `Paused` run of the session, so the run that was authorised (`assert_run_owner(run_name)`)
     and the run that was acted on could be two different rows.

And the invariant, which is the reason all three matter together — stated once in the engine at
`FlowSession.resume` and measured here:

    **The identity the approval card was rendered for and the identity the continuation executes
    as are the same identity.**

QBENCH-12 demonstrated the opposite pairing live: a card rendered as the asker, a body run as the
approver. `922bae2` made the body the requester's, which is what makes the pairing coherent rather
than merely confusing — but "coherent by construction" is only worth what a test that would notice
the construction changing is worth.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import frappe

from flow.lib.agent import Agent
from flow.lib.model import Model
from flow.tests.test_s25_two_doors_one_identity import (
	WITNESS,
	TwoDoorsCase,
	_chat,
	_final,
)

APP_ROOT = Path(__file__).resolve().parents[2]


class PinCase(TwoDoorsCase):
	"""S25's fixture, plus a service-account requester whose reach nobody here can borrow."""

	def _paused_run_owned_by_the_system(self, slug: str, arguments: dict[str, Any] | None = None):
		"""A run owned by `Administrator`, which is the shape a trigger's `run_as` produces.

		`_the_answerer_may_not_gain_reach` refuses any other answerer for it BEFORE the role
		arithmetic — deliberately, because Administrator's reach is not made of roles. So this is
		the run that nobody but the system may APPROVE, and the question this class asks is what
		happens when the answer is no.
		"""
		return self._paused_run("Administrator", slug, arguments)


class TestTheRuntimeIsAssembledInsideThePin(PinCase):
	"""HOLE 1. The tools the continuation may reach are resolved as the requester, or the pin is
	a convention.

	Measured by OBJECT IDENTITY, not by a name: the runtime `Agent.resume` is called on has to be
	one that was built while `frappe.session.user` was the requester. Asserting only that "an
	assemble happened as the requester" would pass on an engine that assembled a second runtime as
	the requester, threw it away, and continued on the answerer's.
	"""

	def _resume_recording_which_runtime_ran(self, door: str, requester: str, approver: str):
		from flow.flow.doctype.flow_agent.flow_agent import FlowAgent

		built: dict[int, str] = {}
		ran: list[int] = []
		original_assemble = FlowAgent.assemble
		original_resume = Agent.resume

		def spy_assemble(self_agent, **kwargs):
			runtime = original_assemble(self_agent, **kwargs)
			built[id(runtime)] = frappe.session.user
			return runtime

		def spy_resume(self_runtime, *args, **kwargs):
			ran.append(id(self_runtime))
			return original_resume(self_runtime, *args, **kwargs)

		run = self._paused_run(requester, self.witness_tool.slug)
		with (
			patch.object(FlowAgent, "assemble", spy_assemble),
			patch.object(Agent, "resume", spy_resume),
			patch.object(Model, "chat", new=_chat(_final())),
		):
			self._answer(door, run, {"c1": "Approve"}, approver)
		return built, ran

	def test_the_runtime_that_continued_the_turn_was_built_as_the_requester(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				built, ran = self._resume_recording_which_runtime_ran(door, self.requester, self.approver)
				self.assertEqual(len(ran), 1, f"door={door}: runtimes resumed {ran}")
				self.assertIn(ran[0], built, f"door={door}: the runtime that ran was never assembled")
				self.assertEqual(
					built[ran[0]],
					self.requester,
					f"door={door}: the continuation ran on a runtime assembled as "
					f"{built[ran[0]]!r} — the tool inventory and the model check are the "
					f"answerer's, not the requester's",
				)

	def test_the_boundary_is_real_the_spy_sees_the_answerer_build_one_too(self):
		"""The positive control on the test above. If `assemble` were never called under the
		answerer at all, the assertion would hold on an engine that assembles nothing anywhere and
		the test would be measuring the absence of a call rather than the identity of one.
		"""
		built, _ran = self._resume_recording_which_runtime_ran("whitelisted", self.requester, self.approver)
		self.assertIn(
			self.approver,
			built.values(),
			f"the answerer built no runtime at all, so this file is not watching a door: {built}",
		)

	def test_there_is_exactly_one_assembly_path_into_a_resume(self):
		"""Fails if a second assembly path is reintroduced.

		Two greps, because the hole has two halves. `FlowAgent.assemble` is the only thing that
		turns a stored agent into a runtime, and it is reached from exactly two places, both in
		`flow/lib/session.py`. Binding a runtime ONTO a session is the other half — that is what
		decides which runtime a resume will actually use — and there are exactly three: a new
		session, a loaded one, and the re-resolution inside the pin. A fourth of either is how hole
		1 comes back: some caller building a runtime under its own identity and handing it to a
		resume.
		"""
		# Paths only, never line numbers -- a comment two functions up must not redden this --
		# but DUPLICATES ARE KEPT, so a second site in a file that already has one is a change.
		assembled = self._non_test_hits(r"\.assemble\(")
		self.assertEqual(
			assembled,
			["flow/lib/session.py", "flow/lib/session.py"],
			"a stored agent is assembled somewhere new",
		)
		bound = self._non_test_hits(r"_runtime(, [a-z_.]+)? =")
		self.assertEqual(
			bound,
			[
				"flow/flow/doctype/flow_session/flow_session.py",
				"flow/lib/session.py",
				"flow/lib/session.py",
			],
			"a runtime is bound onto a session somewhere new",
		)

	def test_the_greps_above_are_real_searches(self):
		"""The positive control. A "zero hits" search is only a finding when a positive control in
		the identical form hits, and both assertions above are satisfied by a grep that has stopped
		finding anything at all.
		"""
		self.assertTrue(self._non_test_hits(r"def assemble\("), "the grep form finds no definition")
		self.assertTrue(self._non_test_hits(r"self\._runtime\."), "the grep form finds no use")

	def _non_test_hits(self, pattern: str) -> list[str]:
		found = subprocess.run(
			["grep", "-rnE", pattern, "--include=*.py", "flow/"],
			cwd=APP_ROOT,
			capture_output=True,
			text=True,
		).stdout.splitlines()
		return sorted(
			line.split(":")[0]
			for line in found
			if "/tests/" not in line and not line.split(":")[0].rsplit("/", 1)[-1].startswith("test_")
		)


class TestADenialIsNotGatedAsThoughItWrites(PinCase):
	"""HOLE 2. A denial creates nothing, so it is not an escalation and must not be refused as one.

	The run used here is owned by `Administrator` — a trigger's `run_as` shape — and
	`_the_answerer_may_not_gain_reach` refuses every other answerer for it, before the role
	arithmetic and on purpose. Approving it must stay refused. DENYING it must not be, or the run
	sits in `Paused` with no way out through the card that raised it.
	"""

	def test_a_service_account_run_can_be_denied_and_reaches_a_terminal_state(self):
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				before = frappe.db.count("Flow Tool")
				run = self._paused_run_owned_by_the_system(self.write_tool.slug, {"title": "S26 Denied"})
				asked_again: list[int] = []
				with patch.object(Model, "chat", new=_chat(_final(), asked_again)):
					self._answer(door, run, {"c1": "Deny"}, self.approver)
				after = frappe.get_doc("Flow Run", run.name)
				self.assertNotEqual(after.status, "Paused", f"door={door}: the denial left it stranded")
				self.assertEqual(after.status, "Completed", f"door={door}: status {after.status}")
				self.assertEqual(WITNESS, [], f"door={door}: a denial ran the tool")
				self.assertEqual(frappe.db.count("Flow Tool"), before, f"door={door}: a denial wrote")
				self.assertEqual(asked_again, [], f"door={door}: a denial went back to the model")

	def test_the_control_run_does_create_something_through_the_same_door(self):
		"""The positive control. Without it "created nothing" is equally consistent with a fixture
		whose tool never writes, and the denial test above would pass against a broken engine.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				before = frappe.db.count("Flow Tool")
				run = self._paused_run(self.wide_requester, self.write_tool.slug, {"title": "S26 Written"})
				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, self.approver)
				self.assertEqual(
					frappe.db.count("Flow Tool"),
					before + 1,
					f"door={door}: the control created nothing either, so the denial test is empty",
				)

	def test_approving_the_same_service_account_run_is_still_refused(self):
		"""The guard is narrowed to denials and to nothing else. An APPROVAL of an
		Administrator-owned run stays refused on every door — that is the escalation S25 closed.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run_owned_by_the_system(self.write_tool.slug, {"title": "S26 Refused"})
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "Approve"}, self.approver)
				self.assertEqual(WITNESS, [], f"door={door}: the refused approval ran anyway")
				self.assertEqual(frappe.get_doc("Flow Run", run.name).status, "Paused", f"door={door}")

	def test_free_text_is_not_a_denial_and_is_still_refused(self):
		"""A redirect is not a denial. It resolves the call with feedback and the loop CARRIES ON
		for up to `max_iterations` further model calls, every one of them as the requester — which
		is exactly the reach the guard exists to refuse. Only `Deny`, which stops the turn dead,
		is let through.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				run = self._paused_run_owned_by_the_system(self.write_tool.slug, {"title": "S26 Redirect"})
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "do it differently"}, self.approver)
				self.assertEqual(WITNESS, [], f"door={door}")

	def test_a_junk_deny_key_does_not_carry_free_text_past_the_guard(self):
		"""THE REVIEWER'S HIGH, AGAINST THIS RUN'S OWN EXEMPTION.

		`answers` is attacker-shaped: `_parse_answers` validates its SHAPE and never checks its keys
		against the pending calls, and `_has_denial` is `any(v == "Deny")`. So a key that names
		nothing — `{"c1": "<text>", "zz": "Deny"}` — satisfied the exemption while `c1` still
		resolved down the FREE-TEXT branch of `_resolve_confirmation`, which returns the answerer's
		sentence inside a tool result carrying `"instruction": "... adjust your approach, and try
		again"`. Nothing executes — `_stopped_result` ends the turn — but `apply_result` PERSISTS
		that message into the requester's transcript, where it is replayed to the model on every
		later turn of their conversation, and every tool the model then calls runs as them.

		So the exemption is narrowed to what it always claimed to be: an answer set that is nothing
		but refusals carries no text, and only that is let past. The STORAGE assertion is the
		load-bearing one — the throw alone would be satisfied by an engine that refused and wrote
		anyway.
		"""
		for door in self.DOORS:
			with self.subTest(door=door):
				run = self._paused_run_owned_by_the_system(self.write_tool.slug, {"title": "S26 Mixed"})
				with patch.object(Model, "chat", new=_chat(_final())):
					with self.assertRaises(frappe.ValidationError):
						self._answer(door, run, {"c1": "SMUGGLED", "zz": "Deny"}, self.approver)
				rows = frappe.get_doc("Flow Session", run.session).messages
				self.assertNotIn(
					"SMUGGLED",
					" ".join(r.content or "" for r in rows),
					f"door={door}: the answerer's text was written into the requester's transcript",
				)

	def test_a_denial_is_still_performed_as_the_requester(self):
		"""Letting a denial past the reach guard does not let it past the PIN. The transcript the
		denial is written into is the requester's, and it is built as them.
		"""
		# The SERVICE-ACCOUNT run, so the denial genuinely crosses the exemption. With an ordinary
		# requester the role difference is empty, the guard never fires, and this test stayed green
		# with the exemption deleted -- a mutation that survived, found by the reviewer.
		run = self._paused_run_owned_by_the_system(self.write_tool.slug, {"title": "S26 Denied Pin"})
		seen_as: list[str] = []
		session_cls = type(frappe.get_doc("Flow Session", run.session))
		original = session_cls._build_prompt_messages

		def spy(self_session):
			seen_as.append(frappe.session.user)
			return original(self_session)

		frappe.set_user(self.approver)
		with (
			patch.object(session_cls, "_build_prompt_messages", spy),
			patch.object(Model, "chat", new=_chat(_final())),
		):
			from flow.api.api import resume_run

			resume_run(run.name, {"c1": "Deny"})
		self.assertEqual(seen_as, ["Administrator"], f"the denial was performed as {seen_as!r}")


class TestAnAnswerCannotCrossApplyToAnotherRun(PinCase):
	"""HOLE 3. `resume_run(run_name=X)` authorised X and acted on whatever was newest.

	`assert_run_owner` and the `status != "Paused"` check are both evaluated against the run the
	CALLER named; `FlowSession.resume` then threw the name away and re-queried for the newest
	`Paused` run of that session. Two `Paused` runs in one session is what makes the two differ,
	and the engine's own guard against that state — `_assert_not_blocked` — is a read-then-act
	with a gap between the read and the `create_run`, so two concurrent turns reach it.

	The state is built here by suppressing that check, which is what losing the race does.
	"""

	def _a_second_paused_run_in_the_same_session(self, session: str):
		"""A second `Paused` run attached to `session`, newer than whatever is there."""
		other = self._paused_run(self.requester, self.witness_tool.slug)
		frappe.db.set_value("Flow Run", other.name, "session", session)
		return frappe.get_doc("Flow Run", other.name)

	def test_answering_one_run_does_not_act_on_another(self):
		from flow.api.api import resume_run

		first = self._paused_run(self.requester, self.write_tool.slug, {"title": "S26 Cross"})
		second = self._a_second_paused_run_in_the_same_session(first.session)
		WITNESS.clear()
		before = frappe.db.count("Flow Tool")

		frappe.set_user(self.requester)
		with patch.object(Model, "chat", new=_chat(_final())):
			with self.assertRaises(frappe.ValidationError):
				resume_run(first.name, {"c1": "Approve"})

		self.assertEqual(
			frappe.get_doc("Flow Run", first.name).status,
			"Paused",
			"the run that was named was resumed under a refusal",
		)
		self.assertEqual(
			frappe.get_doc("Flow Run", second.name).status,
			"Paused",
			"the answer landed on a run the caller never named",
		)
		self.assertEqual(WITNESS, [], "a tool ran on an answer that could not be placed")
		self.assertEqual(frappe.db.count("Flow Tool"), before, "the cross-applied answer wrote")

	def test_the_control_a_single_paused_run_still_resumes_normally(self):
		"""The positive control: the refusal above is about the AMBIGUITY, not about `run_name`
		having become impossible to satisfy.
		"""
		from flow.api.api import resume_run

		run = self._paused_run(self.requester, self.witness_tool.slug)
		frappe.set_user(self.approver)
		with patch.object(Model, "chat", new=_chat(_final())):
			resume_run(run.name, {"c1": "Approve"})
		self.assertEqual(frappe.get_doc("Flow Run", run.name).status, "Completed")
		self.assertEqual(len(WITNESS), 1, WITNESS)


class TestTheCardAndTheBodyAreOneIdentity(PinCase):
	"""THE INVARIANT, AND QBENCH-12'S SHAPE IS ITS NEGATION.

	The approval card is rendered when the run PAUSES, inside the requester's own turn, from the
	tool call and the tool's own metadata. The body runs when the run RESUMES. Those are two
	different requests, seconds or days apart, and until `922bae2` they were two different
	identities: the card was rendered as the asker and the body ran as the approver.

	There is no field to compare, and inventing one would be a tautology — `_the_requester`
	returns `run.owner`, so an assertion that the pin equals `run.owner` asserts that a function
	returns what it returns. What is worth measuring is the CONSTRUCTION: the user who was acting
	when the question was built, captured as it was built, against the user who is acting when the
	body runs. This test fails the moment those two stop being the same person, whichever end
	moves.
	"""

	def test_the_identity_the_card_was_rendered_for_is_the_identity_the_body_runs_as(self):
		from flow.lib import agent as agent_module

		for door in self.DOORS:
			with self.subTest(door=door):
				WITNESS.clear()
				rendered_as: list[str] = []
				original = agent_module._confirmation_question

				def spy(call, tool):
					rendered_as.append(frappe.session.user)
					return original(call, tool)

				with patch.object(agent_module, "_confirmation_question", spy):
					run = self._paused_run(self.requester, self.witness_tool.slug)
				self.assertEqual(len(rendered_as), 1, f"door={door}: no card was rendered")

				with patch.object(Model, "chat", new=_chat(_final())):
					self._answer(door, run, {"c1": "Approve"}, self.approver)
				ran_as = self._only_witness(door)["user"]

				self.assertEqual(
					rendered_as[0],
					ran_as,
					f"door={door}: the card was rendered for {rendered_as[0]!r} and the body ran "
					f"as {ran_as!r} — two halves of one approval disagreeing about whose hands "
					f"are involved",
				)

	def test_the_boundary_is_real_the_answerer_is_a_third_identity(self):
		"""Without this the invariant above is satisfied by a bench where everyone is the same
		user, and the test would hold on the engine QBENCH-12 filmed.
		"""
		self.assertNotEqual(self.approver, self.requester)
		run = self._approve_through("whitelisted", requester=self.requester, approver=self.approver)
		self.assertEqual(frappe.get_doc("Flow Run", run.name).owner, self.requester)
