# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flow.lib import page_context


class TestDocumentPageContext(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_includes_current_form_values(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "saved value"}).insert()
		values = todo.as_dict()
		values["description"] = "unsaved value visible on the form"

		with patch.object(page_context, "_get_inbound_links", return_value=[]):
			context = page_context.build_page_context(
				{
					"type": "document",
					"doctype": "ToDo",
					"name": todo.name,
					"values": values,
					"is_dirty": True,
				}
			)

		self.assertEqual(context["contents"]["description"], "unsaved value visible on the form")
		self.assertTrue(context["is_dirty"])

	def test_excludes_fields_outside_read_permlevels(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "restricted value"}).insert()

		with (
			patch.object(page_context, "_get_inbound_links", return_value=[]),
			patch.object(page_context, "_permitted_fieldnames", return_value={"name", "docstatus"}),
		):
			context = page_context.build_page_context(
				{
					"type": "document",
					"doctype": "ToDo",
					"name": todo.name,
					"values": todo.as_dict(),
				}
			)

		self.assertNotIn("description", context["contents"])
		self.assertEqual(context["contents"]["name"], todo.name)

	def test_requires_document_read_permission(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			page_context.build_page_context(
				{
					"type": "document",
					"doctype": "User",
					"name": "Administrator",
				}
			)

	def test_existing_document_cannot_spoof_is_new(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			page_context.build_page_context(
				{
					"type": "document",
					"doctype": "User",
					"name": "Administrator",
					"is_new": True,
					"values": {"name": "Administrator", "first_name": "forged"},
				}
			)

	def test_resume_revalidates_document_permission(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			page_context.revalidate_page_context(
				{
					"type": "document",
					"doctype": "User",
					"name": "Administrator",
					"contents": {"name": "Administrator"},
				}
			)


class TestListPageContext(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_reads_visible_rows_in_browser_order_with_hard_limit(self):
		todos = [
			frappe.get_doc({"doctype": "ToDo", "description": f"page row {index}"}).insert()
			for index in range(page_context.PAGE_CONTEXT_LIST_LIMIT + 2)
		]
		names = [todo.name for todo in reversed(todos)]

		with patch.object(page_context, "_get_inbound_links", return_value=[]):
			context = page_context.build_page_context(
				{
					"type": "list",
					"doctype": "ToDo",
					"names": names,
					"fields": ["name", "description"],
					"filters": [["ToDo", "description", "like", "%page row%"]],
				}
			)

		self.assertEqual(len(context["contents"]), page_context.PAGE_CONTEXT_LIST_LIMIT)
		self.assertEqual(
			[row["name"] for row in context["contents"]],
			names[: page_context.PAGE_CONTEXT_LIST_LIMIT],
		)
		self.assertTrue(context["contents_truncated"])

	def test_rejects_filters_for_unreadable_fields(self):
		with (
			patch.object(page_context, "_get_inbound_links", return_value=[]),
			patch.object(page_context, "_permitted_fieldnames", return_value={"name"}),
			self.assertRaisesRegex(frappe.ValidationError, "Invalid page context"),
		):
			page_context.build_page_context(
				{
					"type": "list",
					"doctype": "ToDo",
					"filters": [["ToDo", "description", "=", "secret"]],
				}
			)

	def test_named_row_context_accepts_display_only_custom_operator(self):
		with patch.object(page_context, "_get_inbound_links", return_value=[]):
			context = page_context.build_page_context(
				{
					"type": "list",
					"doctype": "ToDo",
					"names": [],
					"filters": [["ToDo", "description", "custom operator", "value"]],
				}
			)

		self.assertEqual(context["filters"][0][2], "custom operator")

	def test_complete_context_is_bounded_including_filters(self):
		filters = [
			["ToDo", "description", "custom operator", ["😀" * 4_000] * 10]
			for _ in range(page_context.PAGE_CONTEXT_MAX_FILTERS)
		]
		with patch.object(page_context, "_get_inbound_links", return_value=[]):
			context = page_context.build_page_context(
				{
					"type": "list",
					"doctype": "ToDo",
					"names": [],
					"filters": filters,
				}
			)

		serialized = json.dumps(context, ensure_ascii=True, default=str, separators=(",", ":"))
		self.assertLessEqual(len(serialized), page_context.PAGE_CONTEXT_MAX_CONTENT_CHARS)


class TestPageRelationships(IntegrationTestCase):
	def test_uses_only_link_fields_for_direct_inbound_relations(self):
		references = {
			"User": [
				{"doctype": "Project", "fieldname": "owner_user"},
				{"doctype": "Project", "fieldname": "owner_user"},
				{
					"doctype": "Comment",
					"fieldname": "reference_name",
					"doctype_fieldname": "reference_doctype",
				},
				{"doctype": "Project", "fieldname": "members", "is_child": True},
			]
		}
		meta = SimpleNamespace(
			istable=0,
			get_field=lambda fieldname: SimpleNamespace(fieldtype="Link", options="User")
			if fieldname == "owner_user"
			else None,
		)

		with (
			patch.object(
				page_context,
				"get_references_across_doctypes_by_link_field",
				return_value=references,
			) as link_references,
			patch(
				"frappe.desk.form.linked_with.get_references_across_doctypes",
				side_effect=TypeError("'NoneType' object is not iterable"),
			) as broad_references,
			patch.object(page_context.frappe, "get_meta", return_value=meta) as get_meta,
			patch.object(page_context.frappe, "has_permission", return_value=True) as has_permission,
			patch.object(
				page_context, "_permitted_fieldnames", return_value={"owner_user"}
			) as permitted_fields,
		):
			result = page_context._get_inbound_links("User")

		self.assertEqual(result, [{"doctype": "Project", "match_field": "owner_user"}])
		link_references.assert_called_once_with(to_doctypes=["User"])
		broad_references.assert_not_called()
		self.assertEqual(get_meta.call_count, 1)
		self.assertEqual(has_permission.call_count, 1)
		self.assertEqual(permitted_fields.call_count, 1)


class TestContextBounding(IntegrationTestCase):
	def test_oversized_document_keeps_structured_contents_for_resume(self):
		context = page_context._finalize_context(
			{
				"type": "document",
				"doctype": "ToDo",
				"name": "TODO-1",
				"contents": {"name": "TODO-1", "description": "x" * 100_000},
				"relationships": [],
			}
		)

		self.assertIsInstance(context["contents"], dict)
		self.assertEqual(context["contents"]["name"], "TODO-1")
		self.assertLessEqual(len(page_context._json_compact(context)), 50_000)
		with patch.object(page_context, "_build_document_context", return_value=context) as builder:
			page_context.revalidate_page_context(context)
		self.assertIsInstance(builder.call_args.args[0]["values"], dict)
		self.assertTrue(builder.call_args.args[0]["values"])

	def test_oversized_list_keeps_structured_rows_for_resume(self):
		context = page_context._finalize_context(
			{
				"type": "list",
				"doctype": "ToDo",
				"contents": [{"name": f"TODO-{index}", "description": "x" * 10_000} for index in range(20)],
				"filters": [],
				"relationships": [],
			}
		)

		self.assertIsInstance(context["contents"], list)
		self.assertTrue(context["contents"])
		self.assertLessEqual(len(page_context._json_compact(context)), 50_000)
		with patch.object(page_context, "_build_list_context", return_value=context) as builder:
			page_context.revalidate_page_context(context)
		self.assertTrue(builder.call_args.args[0]["names"])
		self.assertTrue(builder.call_args.args[0]["fields"])


class TestRoutePageContext(IntegrationTestCase):
	def test_visible_page_text_is_bounded(self):
		context = page_context.build_page_context(
			{
				"type": "route",
				"route": ["query-report", "Sales Analytics"],
				"page_text": "x" * (page_context.PAGE_CONTEXT_MAX_CONTENT_CHARS + 100),
			}
		)

		serialized = json.dumps(context, ensure_ascii=True, default=str, separators=(",", ":"))
		self.assertLessEqual(len(serialized), page_context.PAGE_CONTEXT_MAX_CONTENT_CHARS)
		self.assertTrue(context["contents_truncated"])

	def test_rejects_unknown_context_type(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Invalid page context"):
			page_context.build_page_context({"type": "unknown"})
