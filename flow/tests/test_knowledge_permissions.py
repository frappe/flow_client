# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""A knowledge hit whose source record the asking user cannot read never reaches them.

Every test that makes a claim about permissions runs as a named, non-Administrator user and
asserts `frappe.session.user` before searching: `has_permission` allows Administrator
everything, so a check run as Administrator proves nothing at all.

The fixture is `Note`, a core doctype of this bench, whose controller hook is
`bool(doc.public or doc.owner == user)`. A non-public Note owned by one person is therefore
readable by that person and by nobody else, through the same controller-permission path a
folder-by-role rule uses. No restriction is invented inside these tests.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flow.knowledge import store
from flow.knowledge.ingest import ingest_source
from flow.knowledge.retriever import CANDIDATE_CEILING, OVERFETCH, retrieve

DIM = 4

READER = "s18-reader@example.com"
OUTSIDER = "s18-outsider@example.com"

SECRET = "zarquonium"
PUBLIC = "brillig"

# Words that must never appear in anything this path hands to the model or a person.
FORBIDDEN = ("frappe", "flow", "erpnext", "mariadb", "openai", "lancedb", "localhost", "http")


def _embedding_response(vectors):
	return SimpleNamespace(data=[{"embedding": v, "index": i} for i, v in enumerate(vectors)])


def _ensure_user(email: str) -> str:
	"""A desk user with one harmless role.

	The role matters: a user with no role at all is created as a website user, is not given the
	automatic desk role, and so has no doctype-level read on the fixture — which would make
	every test below pass for the wrong reason. `Translator` grants nothing on the fixture, so
	doctype-level read comes from the automatic desk role and the only thing left to decide is
	the record.
	"""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": "Translator"}],
			}
		).insert(ignore_permissions=True)
	else:
		# A row surviving an aborted run (a crash between insert and rollback, or one made by
		# hand) would otherwise be returned exactly as found — without the role the docstring
		# above says is load-bearing. `add_roles` is idempotent, so make it unconditional
		# rather than conditional. (L7, review of run 8.)
		frappe.get_doc("User", email).add_roles("Translator")
	frappe.clear_cache(user=email)
	return email


def _set_settings(**values):
	for fieldname, value in values.items():
		frappe.db.set_single_value("Flow Knowledge Settings", fieldname, value)
	frappe.clear_document_cache("Flow Knowledge Settings", "Flow Knowledge Settings")


def _make_model(title="S18 Embed Model"):
	if frappe.db.exists("Flow Model", title):
		return frappe.get_doc("Flow Model", title)
	return frappe.get_doc(
		{
			"doctype": "Flow Model",
			"title": title,
			"model_id": "openai/text-embedding-3-small",
			"api_key": "sk-test",
			"enabled": 1,
		}
	).insert()


class KnowledgePermissionCase(IntegrationTestCase):
	"""Shared fixture: a knowledge base, notes with known readability, and a search helper."""

	def setUp(self):
		store.drop_table()
		self.model = _make_model()
		_set_settings(
			embedding_model=self.model.name,
			embedding_dimension=DIM,
			chunk_size=2000,
			chunk_overlap=20,
			search_type="Hybrid",
		)
		self.reader = _ensure_user(READER)
		self.outsider = _ensure_user(OUTSIDER)
		# The precondition every negative test below rests on: the outsider can read the
		# fixture's DOCTYPE. Without it a roleless user would make them all pass for the
		# wrong reason. (L7, review of run 8.)
		for user in (self.reader, self.outsider):
			self.assertTrue(frappe.has_permission("Note", "read", user=user))

	def tearDown(self):
		frappe.set_user("Administrator")
		store.drop_table()
		frappe.db.rollback()

	# --- fixture -------------------------------------------------------------

	def _kb(self, title):
		return frappe.get_doc({"doctype": "Flow Knowledge Base", "title": title}).insert()

	def _fake_embed(self, input, **kwargs):
		return _embedding_response([[0.1, 0.2, 0.3, 0.4]] * len(input))

	def _ingest(self, source_name):
		with (
			patch("litellm.embedding", side_effect=self._fake_embed),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
		):
			ingest_source(source_name)

	def _note(self, title, body, *, owner=None, public=0):
		"""A Note, inserted as Administrator, then stamped with its owner.

		The owner is set with db.set_value rather than by inserting as that user, so the
		fixture does not depend on the test users' create permission.
		"""
		note = frappe.get_doc(
			{"doctype": "Note", "title": title, "content": f"<p>{body}</p>", "public": public}
		).insert(ignore_permissions=True)
		if owner:
			frappe.db.set_value("Note", note.name, "owner", owner, update_modified=False)
			frappe.clear_document_cache("Note", note.name)
			note.reload()
		return note

	def _note_source(self, kb, *, title_like, title="Notes"):
		with patch("flow.knowledge.ingest.enqueue_ingestion"):
			source = frappe.get_doc(
				{
					"doctype": "Flow Knowledge Source",
					"knowledge_base": kb,
					"source_type": "DocType",
					"title": title,
					"reference_doctype": "Note",
					"content_fields": "title, content",
					"filters": json.dumps({"title": ["like", title_like]}),
				}
			).insert()
		self._ingest(source.name)
		return source

	def _text_source(self, kb, content, title="Plain Doc"):
		with patch("flow.knowledge.ingest.enqueue_ingestion"):
			source = frappe.get_doc(
				{
					"doctype": "Flow Knowledge Source",
					"knowledge_base": kb,
					"source_type": "Text",
					"title": title,
					"content": content,
				}
			).insert()
		self._ingest(source.name)
		return source

	def _retrieve_as(self, user, query, **kwargs):
		with self.set_user(user):
			self.assertEqual(frappe.session.user, user)  # a check run as Administrator proves nothing
			with patch("litellm.embedding", side_effect=self._fake_embed):
				return retrieve(query, **kwargs)


class TestUnreadableHitsAreDropped(KnowledgePermissionCase):
	def setUp(self):
		super().setUp()
		self.kb = self._kb("S18 Secret KB")
		self.secret = self._note("S18 Secret", f"the {SECRET} process is confidential", owner=self.reader)
		self._note_source(self.kb.name, title_like="S18 Secret%")

	def test_a_user_who_may_not_read_the_record_gets_nothing_at_all(self):
		"""Nothing comes back, and nothing about the record comes back with it."""
		results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		blob = json.dumps(results, default=str)
		for fragment in (SECRET, self.secret.title, self.secret.name, "score", "content", "source"):
			with self.subTest(fragment=fragment):
				self.assertNotIn(fragment, blob)  # reports first: "[]" is not the only way to pass
		self.assertEqual(len(results), 0)
		self.assertEqual(results, [])

	def test_control_the_owner_does_get_the_record(self):
		"""The control. Without it, the test above passes by returning nothing to anybody."""
		results = self._retrieve_as(self.reader, SECRET, kbs=[self.kb.name])

		self.assertEqual(len(results), 1)
		self.assertIn(SECRET, results[0]["content"])
		self.assertEqual(results[0]["reference_doctype"], "Note")
		self.assertEqual(results[0]["reference_name"], self.secret.name)

	def test_a_dropped_hit_produces_no_message_and_does_not_raise(self):
		"""`throw=True` on the permission call would produce both."""
		frappe.local.message_log = []
		results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual(results, [])
		self.assertEqual(frappe.local.message_log, [])

	def test_an_ordinary_refusal_records_nothing(self):
		"""The control for `test_a_check_that_cannot_answer_is_recorded_for_the_operator`.

		Without it, that test would pass on an implementation that logged every denial — which
		is the outage the per-search cap exists to stop, and which would also hand the operator a
		row for every record anybody was ever not allowed to see. A refusal is silent. (M1.)
		"""
		logged = []
		with patch.object(frappe, "log_error", lambda *a, **k: logged.append((a, k))):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual(results, [])
		self.assertEqual(logged, [])

	def test_the_serialized_tool_result_carries_no_trace_of_the_record(self):
		"""A sweep over the serialized result the caller is handed, not over the dict."""
		from flow.lib.agent import _serialize_tool_result

		results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])
		serialized = _serialize_tool_result(results)

		self.assertNotIn(SECRET, serialized)
		self.assertNotIn(self.secret.title, serialized)
		self.assertNotIn(self.secret.name, serialized)

	def test_the_search_knowledge_tool_goes_through_the_filtered_path(self):
		"""The bound tool, not the function underneath it."""
		from flow.tools.builtins import bind_search_knowledge

		tool = bind_search_knowledge([self.kb.name])

		with self.set_user(self.outsider):
			self.assertEqual(frappe.session.user, self.outsider)
			with patch("litellm.embedding", side_effect=self._fake_embed):
				denied = tool(query=SECRET)

		self.assertEqual(denied, [])
		self.assertNotIn(SECRET, json.dumps(denied, default=str))

		with self.set_user(self.reader):
			self.assertEqual(frappe.session.user, self.reader)
			with patch("litellm.embedding", side_effect=self._fake_embed):
				allowed = tool(query=SECRET)

		self.assertEqual(len(allowed), 1)  # control: the tool does reach the record for its owner

	def test_the_permission_check_is_about_the_record_not_the_doctype(self):
		"""Both users have doctype-level read on the fixture; only one owns the record — and
		`_may_read` follows the record, not the type.

		Rewritten for L1 (review of run 8): as written it asserted only on `frappe.has_permission`
		and no mutation of `flow/knowledge/retriever.py` could turn it red — the module could be
		deleted outright and it still passed. The first line stays as the fixture precondition;
		everything after it goes through the code this spec changed.
		"""
		from flow.knowledge import retriever

		self.assertTrue(frappe.has_permission("Note", "read", user=self.outsider))  # precondition
		chunk = {"reference_doctype": "Note", "reference_name": self.secret.name}

		with self.set_user(self.outsider):
			self.assertEqual(frappe.session.user, self.outsider)
			self.assertFalse(retriever._may_read(chunk))
		with self.set_user(self.reader):
			self.assertEqual(frappe.session.user, self.reader)
			self.assertTrue(retriever._may_read(chunk))


class TestChunksWithNoReference(KnowledgePermissionCase):
	def test_a_chunk_with_no_reference_is_returned_exactly_as_before(self):
		"""Backwards compatibility: Text, File and URL sources set no reference."""
		kb = self._kb("S18 Plain KB")
		source = self._text_source(kb.name, f"the {PUBLIC} handbook for everyone. " * 4)

		results = self._retrieve_as(self.outsider, PUBLIC, kbs=[kb.name])

		self.assertTrue(results)
		self.assertTrue(all(PUBLIC in r["content"] for r in results))
		self.assertTrue(all(r["source"] == source.name for r in results))
		self.assertTrue(all(r["reference_doctype"] is None for r in results))
		self.assertTrue(all(r["reference_name"] is None for r in results))
		self.assertEqual(
			set(results[0]),
			{"content", "score", "source", "reference_doctype", "reference_name", "title", "url"},
		)

	def test_a_text_source_hit_is_titled_by_its_source_row_and_has_no_url(self):
		"""Its title is the knowledge source row's, and there is no record to link to."""
		kb = self._kb("S18 Plain KB 2")
		self._text_source(kb.name, f"the {PUBLIC} handbook for everyone. " * 4, title="Staff Handbook")

		results = self._retrieve_as(self.outsider, PUBLIC, kbs=[kb.name])

		self.assertTrue(results)
		self.assertTrue(all(r["title"] == "Staff Handbook" for r in results))
		self.assertTrue(all(r["url"] is None for r in results))


class TestTheCheckCannotSpeak(KnowledgePermissionCase):
	"""What happens when the permission check itself cannot answer.

	Deleting an indexed record is a normal, supported operation: the chunk deliberately does
	not block it, and a scheduled sweep removes the orphan later. So between the delete and
	the sweep the store holds hits whose record is gone, and loading one raises — with a
	message naming the record. A hit the check cannot clear is a hit that is not shown, and
	nothing about it is said out loud.
	"""

	def setUp(self):
		super().setUp()
		self.kb = self._kb("Read Filter Orphan KB")
		self.gone = self._note("Read Filter Orphan gone", f"{SECRET} about to vanish", public=1)
		self.stays = self._note("Read Filter Orphan stays", f"{SECRET} still here", public=1)
		self._note_source(self.kb.name, title_like="Read Filter Orphan%")
		self.ids = self._chunk_ids([self.gone.name, self.stays.name])
		self.assertEqual(len(self.ids), 2)

	def _chunk_ids(self, note_names):
		rows = frappe.get_all(
			"Flow Knowledge Chunk",
			filters={"reference_doctype": "Note", "reference_name": ["in", note_names]},
			fields=["name", "reference_name"],
		)
		by_note = {row["reference_name"]: int(row["name"]) for row in rows}
		return [by_note[name] for name in note_names if name in by_note]

	def _orphan(self):
		"""Delete the row underneath the chunk, the way the sweep's 24-hour window leaves it."""
		frappe.db.delete("Note", {"name": self.gone.name})
		frappe.clear_document_cache("Note", self.gone.name)

	def _fixed_order(self, ordered_ids):
		def fake_search(vector, *, text=None, kbs=None, limit=5, **kwargs):
			return [{"id": i, "kb": "kb", "source": "src", "score": 1.0} for i in ordered_ids[:limit]]

		return fake_search

	def test_a_hit_whose_record_is_gone_is_dropped_and_says_nothing(self):
		self._orphan()
		frappe.local.message_log = []

		results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual([r["reference_name"] for r in results], [self.stays.name])
		self.assertEqual(frappe.local.message_log, [])
		blob = json.dumps(results, default=str)
		self.assertNotIn(self.gone.name, blob)
		self.assertNotIn("Read Filter Orphan gone", blob)

	def test_a_readable_hit_ranked_below_the_orphan_still_comes_back(self):
		"""The orphan must not take the rest of the search down with it."""
		self._orphan()

		with patch("flow.knowledge.store.search", side_effect=self._fixed_order(self.ids)):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual([r["reference_name"] for r in results], [self.stays.name])

	def test_a_check_that_raises_for_any_reason_drops_the_hit_silently(self):
		"""A restriction hook of somebody else's can raise or speak. Neither reaches the asker."""

		def angry(doctype, ptype="read", doc=None, **kwargs):
			frappe.msgprint(f"denied loudly for {doc}")
			raise RuntimeError(f"hook exploded on {doc}")

		frappe.local.message_log = []
		with patch.object(frappe, "has_permission", angry):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual(results, [])
		self.assertEqual(frappe.local.message_log, [])

	def test_a_check_that_cannot_answer_is_recorded_for_the_operator(self):
		"""A refusal is silent. A crash is not. The asker gets nothing either way. (M1.)

		A lock-wait timeout mid-loop empties the whole search, and before this the operator had
		no record of it anywhere: the asker is told "nothing matched" and it does not reproduce
		on demand. The row carries no content, title or excerpt — only that the gate stopped
		answering, and how many hits that cost.

		`len(logged) == 1` is the discriminating assertion: this fixture has TWO candidates and
		both raise, so an implementation that logs per candidate scores 2.
		"""

		def broken(*args, **kwargs):
			raise frappe.db.InternalError("lock wait timeout exceeded")

		logged = []
		frappe.local.message_log = []
		with (
			patch.object(frappe, "has_permission", broken),
			patch.object(frappe, "log_error", lambda *a, **k: logged.append(k)),
		):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual(results, [])  # still fail-closed
		self.assertEqual(frappe.local.message_log, [])  # still silent to the asker
		self.assertEqual(len(logged), 1)  # once per search, not once per candidate

		written = f"{logged[0].get('title', '')}\n{logged[0].get('message', '')}"
		for fragment in (SECRET, self.gone.title, self.stays.title, self.gone.name, self.stays.name):
			with self.subTest(fragment=fragment):
				self.assertNotIn(fragment, written)  # no content, no title, no excerpt, no name

	def test_a_hit_whose_record_is_gone_records_nothing_either(self):
		"""The second control: a deleted record is an EXPECTED refusal, not a crash.

		The sweep's 24-hour window is a normal state of this store. Logging it would put a row in
		front of the operator every day for something working as designed, and would bury the one
		that matters. (M1.)
		"""
		self._orphan()

		logged = []
		with patch.object(frappe, "log_error", lambda *a, **k: logged.append(k)):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name])

		self.assertEqual([r["reference_name"] for r in results], [self.stays.name])
		self.assertEqual(logged, [])

	def test_a_chunk_that_names_a_doctype_but_no_record_is_dropped_not_kept(self):
		"""Half a reference is not "no record behind it" — it is a chunk to distrust."""
		from flow.knowledge import retriever

		self.assertTrue(retriever._may_read({"reference_doctype": None, "reference_name": None}))
		self.assertFalse(retriever._may_read({"reference_doctype": "Note", "reference_name": None}))
		self.assertFalse(retriever._may_read({"reference_doctype": None, "reference_name": "x"}))


class TestOverFetchAndCeiling(KnowledgePermissionCase):
	"""The store's ranking is not the thing under test, so it is replaced by a fixed order.

	Every chunk id in the fixed order is a real MariaDB row with a real reference, so
	hydration and the permission check are the production ones. The spy honours the `limit`
	it is given, which is what makes the over-fetch a real measurement rather than a comment.
	"""

	def setUp(self):
		super().setUp()
		self.kb = self._kb("S18 Mixed KB")
		self.hidden = [
			self._note(f"S18 Mixed hidden {i}", f"{SECRET} restricted {i}", owner=self.reader)
			for i in range(6)
		]
		self.open = [self._note(f"S18 Mixed open {i}", f"{SECRET} shared {i}", public=1) for i in range(6)]
		self._note_source(self.kb.name, title_like="S18 Mixed%")
		self.hidden_ids = self._chunk_ids([n.name for n in self.hidden])
		self.open_ids = self._chunk_ids([n.name for n in self.open])
		self.assertEqual(len(self.hidden_ids), 6)
		self.assertEqual(len(self.open_ids), 6)

	def _chunk_ids(self, note_names):
		"""The chunk ids for these notes, in the order the notes were given.

		The query's own order is not the notes' order, and these tests are about what the
		filter does to a given order, so the mapping is made explicit.
		"""
		rows = frappe.get_all(
			"Flow Knowledge Chunk",
			filters={"reference_doctype": "Note", "reference_name": ["in", note_names]},
			fields=["name", "reference_name"],
		)
		by_note = {row["reference_name"]: int(row["name"]) for row in rows}
		return [by_note[name] for name in note_names if name in by_note]

	def _ordered_search(self, ordered_ids):
		"""A store stand-in that returns `ordered_ids`, truncated to the limit it is asked for."""
		calls = []

		def fake_search(vector, *, text=None, kbs=None, limit=5, **kwargs):
			calls.append(limit)
			return [{"id": i, "kb": "kb", "source": "src", "score": 1.0} for i in ordered_ids[:limit]]

		return fake_search, calls

	def test_unreadable_hits_ranked_first_do_not_cost_the_reader_their_results(self):
		"""With no over-fetch the store returns only the rows this user may not read."""
		fake_search, calls = self._ordered_search(self.hidden_ids + self.open_ids)

		with patch("flow.knowledge.store.search", side_effect=fake_search):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name], limit=5)

		self.assertEqual(calls, [5 * OVERFETCH])
		self.assertEqual(len(results), 5)
		self.assertEqual([r["reference_name"] for r in results], [n.name for n in self.open[:5]])

	def test_the_ceiling_is_the_stores_own_clamp(self):
		"""The ceiling is written as a literal because the store is imported lazily. If the
		store's clamp ever moves, this is what says so."""
		self.assertEqual(CANDIDATE_CEILING, store.MAX_SEARCH_LIMIT)

	def test_the_store_is_never_asked_for_more_than_the_ceiling(self):
		"""The ceiling is the store's own clamp, so it is not an invented number."""
		fake_search, calls = self._ordered_search(self.hidden_ids)

		with patch("flow.knowledge.store.search", side_effect=fake_search):
			self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name], limit=CANDIDATE_CEILING)

		self.assertEqual(calls, [CANDIDATE_CEILING])
		# A precondition on the constant, NOT a measurement of the clamp: with OVERFETCH <= 1
		# the line above would hold whatever `retrieve` did with the ceiling. The clamp is
		# measured by the assertion above it and by nothing else. (L2, review of run 8: this
		# line previously read `assertLess(CANDIDATE_CEILING, CANDIDATE_CEILING * OVERFETCH)`
		# with the comment "the clamp did work", which is true for any OVERFETCH >= 2.)
		self.assertGreater(OVERFETCH, 1)

	def test_more_unreadable_candidates_than_the_ceiling_ends_the_search(self):
		"""It stops at the ceiling and returns what it has.

		The candidate list is longer than the ceiling, and every candidate inside the
		ceiling is unreadable. The readable rows sit beyond it and are never reached — the
		search does not page deeper to find them.
		"""
		beyond = [self.hidden_ids[0]] * CANDIDATE_CEILING + self.open_ids
		fake_search, calls = self._ordered_search(beyond)
		checked = []
		real = frappe.has_permission

		def counting_has_permission(*args, **kwargs):
			checked.append(args[:3])
			return real(*args, **kwargs)

		with (
			patch("flow.knowledge.store.search", side_effect=fake_search),
			patch.object(frappe, "has_permission", counting_has_permission),
		):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name], limit=50)

		self.assertEqual(results, [])
		self.assertEqual(calls, [CANDIDATE_CEILING])
		self.assertEqual(len(checked), CANDIDATE_CEILING)

	def test_the_readable_and_unreadable_rows_keep_their_relative_order(self):
		"""A filter that also reorders would be a different change."""
		interleaved = []
		for hidden, open_ in zip(self.hidden_ids, self.open_ids, strict=True):
			interleaved.extend([hidden, open_])
		fake_search, _ = self._ordered_search(interleaved)

		with patch("flow.knowledge.store.search", side_effect=fake_search):
			results = self._retrieve_as(self.outsider, SECRET, kbs=[self.kb.name], limit=6)

		self.assertEqual([r["reference_name"] for r in results], [n.name for n in self.open])


class TestCitations(KnowledgePermissionCase):
	def setUp(self):
		super().setUp()
		self.kb = self._kb("S18 Cited KB")
		self.open = self._note("S18 Cited open", f"{PUBLIC} anyone may read this", public=1)
		self.hidden = self._note("S18 Cited hidden", f"{PUBLIC} nobody else may read this", owner=self.reader)
		self._note_source(self.kb.name, title_like="S18 Cited%")

	def test_every_doctype_hit_carries_the_records_own_title(self):
		"""The record names itself, not the opaque knowledge source row."""
		results = self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name])

		self.assertTrue(results)
		self.assertTrue(all(r["title"] for r in results))
		self.assertTrue(all(r["title"] == "S18 Cited open" for r in results))

	def test_every_doctype_hit_carries_a_relative_desk_path(self):
		"""A path, not an address: no scheme and no host."""
		results = self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name])

		self.assertTrue(results)
		for row in results:
			with self.subTest(name=row["reference_name"]):
				self.assertEqual(row["url"], f"/desk/note/{row['reference_name']}")
				self.assertTrue(row["url"].startswith("/"))
				self.assertNotIn("://", row["url"])

	def test_an_unreadable_hit_contributes_no_title(self):
		"""The titles are built after the permission check, so a dropped record's title is
		never even asked for."""
		from flow.knowledge import retriever

		asked = []
		real = retriever._titles_for

		def recording_titles_for(chunks):
			asked.extend(c.get("reference_name") for c in chunks)
			return real(chunks)

		with patch.object(retriever, "_titles_for", recording_titles_for):
			results = self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name])

		self.assertTrue(results)
		self.assertNotIn(self.hidden.name, asked)
		self.assertIn(self.open.name, asked)
		blob = json.dumps(results, default=str)
		self.assertNotIn("S18 Cited hidden", blob)

	def test_a_name_cannot_change_the_shape_of_the_path(self):
		"""Every fixture name here is hex, so the encoding needs its own test."""
		from flow.knowledge import retriever

		self.assertEqual(
			retriever._url_of({"reference_doctype": "Note", "reference_name": "a/b#c d"}),
			"/desk/note/a%2Fb%23c%20d",
		)
		self.assertIsNone(retriever._url_of({"reference_doctype": None, "reference_name": "x"}))

	def test_a_record_with_no_title_field_is_named_by_its_own_name(self):
		"""`get_title_field` falls back to `name`, and that branch is on the same path.

		Rewritten for L3 (review of run 8). As written this reached the fallback on neither half:
		the first asked `DocField` — which has no title field — for the row `"nope"`, which does
		not exist, so `{}` came back whatever `field` was; the second used `Note`, whose
		`title_field` IS `title`, so it exercised the ordinary branch. A real row of a doctype
		with no title field is what makes the fallback observable, and it is what catches a
		change that stops de-duplicating `["name", "name"]`.
		"""
		from flow.knowledge import retriever

		self.assertIsNone(frappe.get_meta("DocField").title_field)  # precondition, not the claim
		row = frappe.get_all("DocField", limit=1, pluck="name")[0]
		self.assertEqual(
			retriever._titles_for([{"reference_doctype": "DocField", "reference_name": row}]),
			{("DocField", row): row},  # named by its own name, and the dedupe held
		)

		titles = retriever._titles_for([{"reference_doctype": "DocField", "reference_name": "nope"}])
		self.assertEqual(titles, {})  # no such row, and no raise

		note = self._note("Read Filter Titled", f"{PUBLIC} titled", public=1)
		self.assertEqual(
			retriever._titles_for([{"reference_doctype": "Note", "reference_name": note.name}]),
			{("Note", note.name): "Read Filter Titled"},
		)

	def test_no_result_field_names_the_platform_a_vendor_or_the_host(self):
		"""With a positive control, so a zero-hit sweep is a finding rather than a shrug."""
		results = self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name])
		blob = json.dumps(results, default=str).lower()

		self.assertTrue(blob.strip())
		for word in FORBIDDEN:
			with self.subTest(word=word):
				self.assertNotIn(word, blob)

		# Positive control IN THE IDENTICAL FORM: the same sweep, over the same real results,
		# with one forbidden word planted into them. (L4, review of run 8: the control was a
		# fresh literal, which proved `assertIn` works rather than that this sweep detects.)
		planted = json.dumps([*results, {"title": "Flow"}], default=str).lower()
		self.assertIn("flow", planted)


class TestExistingGatesAreUntouched(KnowledgePermissionCase):
	"""The new filter is a third gate, never a replacement for the two that exist."""

	def setUp(self):
		super().setUp()
		self.kb = self._kb("S18 Gate KB")
		self._note("S18 Gate open", f"{PUBLIC} readable by all", public=1)
		self._note_source(self.kb.name, title_like="S18 Gate%")

	def test_an_empty_knowledge_base_scope_still_throws(self):
		with self.set_user(self.outsider):
			with self.assertRaises(frappe.ValidationError):
				retrieve(PUBLIC, kbs=[])

	def test_a_disabled_knowledge_base_is_still_skipped(self):
		self.assertTrue(self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name]))

		frappe.db.set_value("Flow Knowledge Base", self.kb.name, "enabled", 0)
		self.assertEqual(self._retrieve_as(self.outsider, PUBLIC, kbs=[self.kb.name]), [])
