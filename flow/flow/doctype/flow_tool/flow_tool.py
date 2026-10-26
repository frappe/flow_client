# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import ast
import re

import frappe
from frappe import _
from frappe.model.document import Document

from flow.utils.system_generated import block_delete, block_rename, validate_immutable

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Shown when someone tries to save one of the shipped tools that change data with its approval
# turned off. It says what the approval is FOR, not only that it is required: a message that merely
# forbids teaches people to look for the way around it. Kept here for the test that reads it; the
# throw inlines the same literal, because the translation extractor only sees literals.
GATE_REQUIRED_MESSAGE = (
	"{0} changes data ({1}), so it always asks the person before it runs. That cannot be turned off "
	"here. If a particular run should not ask, that is a decision about the run, not about the tool."
)
# An approval question is one or two sentences. Anything longer is not being read.
CONFIRM_TEMPLATE_LIMIT = 1000
IMPORT_PATH_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")
MAIN_FUNCTION_NAME = "main"


class FlowTool(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		code: DF.Code | None
		confirm_template: DF.SmallText | None
		description: DF.LongText
		enabled: DF.Check
		import_path: DF.Data | None
		is_system_generated: DF.Check
		requires_confirmation: DF.Check
		slug: DF.Data
		summary: DF.SmallText | None
		title: DF.Data
		type: DF.Literal["Imported", "Script"]
	# end: auto-generated types

	def validate(self):
		self._normalize()
		self._validate_slug()
		self._validate_type_fields()
		self._validate_confirm_template()
		self._validate_confirmation_not_removed()
		if self.type == "Script":
			self._validate_code()
		validate_immutable(self, ("type", "import_path", "slug"))

	def _validate_confirm_template(self):
		"""Refuse an approval question nobody will read, at the moment it is written.

		There is no syntax to check: the question is plain text and `{argument_name}` is replaced
		by that argument, so nothing in it can be malformed. Length is the one thing that can go
		wrong here, and left to the moment of approval the only sign would be the raw arguments
		appearing where a sentence was meant to be, with nobody knowing why.
		"""
		# Stored as it is measured: otherwise 999 characters and 5000 spaces passes a 1000 cap.
		self.confirm_template = (self.confirm_template or "").strip() or None
		template = self.confirm_template or ""
		if len(template) > CONFIRM_TEMPLATE_LIMIT:
			frappe.throw(
				_("Keep the approval question under {0} characters.").format(CONFIRM_TEMPLATE_LIMIT),
				title=_("Approval Question Too Long"),
			)

	def _validate_confirmation_not_removed(self):
		"""A shipped tool that changes data always asks first, and no record may say otherwise.

		For every tool resolved from its record, the runtime reads the record — so one unchecked
		box meant the model deleted records with nothing asked from the very next turn, and worse,
		an ungated call beside a gated one runs DURING the turn that pauses, while the person is
		reading a question about something else. A migrate's sync rewrites the flag from the code;
		between two migrates nothing did. (The memory tool is the exception: it is bound in code by
		the agent's own tool resolution and is gated there, not here.)

		Unlike `validate_immutable`, this does NOT step aside for `ignore_permissions`. An approval
		on a tool that changes data is not an app-configurable value and there is no legitimate
		caller that turns one off. The sync a migrate runs is unaffected: it writes the approval ON,
		and it writes through `db.set_value`, which does not come through here at all — so a caller
		that can run code can still reach the column directly.

		This guards the record. It is not the only guard: an imported tool that declares its own
		approval keeps it whatever a record says (see `resolver._build_tool`), which is what stops
		a second record importing the same function under a name this list has never heard of.

		One-directional on purpose: turning an approval ON is never refused.
		"""
		from flow.tools.builtins import WRITE_CAPABLE

		what = WRITE_CAPABLE.get(self.slug)
		if what and not self.requires_confirmation:
			frappe.throw(
				# The literal is inlined here rather than passed as a name: the translation
				# extractor only sees string literals, so `_(CONSTANT)` is never translated.
				_(
					"{0} changes data ({1}), so it always asks the person before it runs. That "
					"cannot be turned off here. If a particular run should not ask, that is a "
					"decision about the run, not about the tool."
				).format(self.slug, what),
				title=_("Approval Required"),
			)

	def on_trash(self):
		block_delete(self, always=True)

	def before_rename(self, old: str, _new: str, _merge: bool = False) -> None:
		block_rename(self, old)

	def to_tool(self):
		"""Resolve this row into a runtime Tool the Agent can call."""
		from flow.lib.resolver import resolve_tool

		return resolve_tool(self)

	def _normalize(self):
		for field in ("title", "slug", "import_path"):
			value = self.get(field)
			if isinstance(value, str):
				self.set(field, value.strip())

	def _validate_slug(self):
		if not SLUG_PATTERN.match(self.slug or ""):
			frappe.throw(
				_(
					"Slug must be snake_case: start with a lowercase letter, then lowercase letters, digits or underscores."
				),
				title=_("Invalid Slug"),
			)

	def _validate_type_fields(self):
		if self.type == "Imported":
			if not self.import_path:
				frappe.throw(_("Import Path is required for Imported tools."), title=_("Missing Import Path"))
			if not IMPORT_PATH_PATTERN.match(self.import_path):
				frappe.throw(
					_(
						"Import Path must be a dotted Python path (e.g. <code>flow.tools.builtins.search</code>)."
					),
					title=_("Invalid Import Path"),
				)
			if self.code:
				frappe.throw(_("Imported tools must not define inline code."), title=_("Unexpected Code"))
		elif self.type == "Script":
			if not self.code:
				frappe.throw(_("Code is required for Script tools."), title=_("Missing Code"))
			if self.import_path:
				frappe.throw(
					_("Script tools must not specify an Import Path."),
					title=_("Unexpected Import Path"),
				)
		else:
			frappe.throw(_("Type must be Imported or Script."), title=_("Invalid Type"))

	def _validate_code(self):
		try:
			tree = ast.parse(self.code, filename=f"<ai_tool:{self.slug}>")
		except SyntaxError as e:
			frappe.throw(
				_("Code has invalid Python syntax: {0}").format(str(e)),
				title=_("Invalid Code"),
			)

		main_function: ast.FunctionDef | None = None
		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and node.name == MAIN_FUNCTION_NAME:
				main_function = node
				break

		if main_function is None:
			frappe.throw(
				_("Code must define a top-level <code>main</code> function."),
				title=_("Missing main()"),
			)

		fn_args = main_function.args
		if fn_args.vararg is not None or fn_args.kwarg is not None:
			frappe.throw(
				_("<code>main</code> must not accept <code>*args</code> or <code>**kwargs</code>."),
				title=_("Invalid Signature"),
			)

		for node in ast.walk(tree):
			if (
				isinstance(node, ast.Call)
				and isinstance(node.func, ast.Name)
				and node.func.id == MAIN_FUNCTION_NAME
			):
				frappe.throw(
					_("Code must not call <code>main()</code> directly (line {0}).").format(node.lineno),
					title=_("Invalid Code"),
				)
