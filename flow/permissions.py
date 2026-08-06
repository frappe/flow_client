# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""Access control for Flow.

Flow is gated by a single role, `Flow User`. A user either may use the
assistant or may not — there are no sub-feature toggles, because an agent
already acts strictly within the running user's own permissions (see
`flow.utils.safe_exec`, which strips `ignore_permissions` and omits raw SQL
entirely). So the only question worth asking is *who*, and a role answers it
the way any other Frappe feature would.

The gate is deliberately the role alone: a System Manager without `Flow User`
is refused, so an admin can hand out access without handing out their own.
`Administrator` bypasses `frappe.only_for` upstream and cannot be excluded.

Enforcement belongs on the whitelisted API (`flow.api`) — that is the
untrusted boundary. Server-side Python (`flow.lib.session`, triggers) is
trusted and stays ungated, or a trigger firing as a low-privilege `run_as`
user would break.
"""

from __future__ import annotations

import frappe

FLOW_USER_ROLE = "Flow User"


def assert_flow_access() -> None:
	"""Raise unless the current user may use Flow. Call first in every whitelisted endpoint."""
	frappe.only_for(FLOW_USER_ROLE, message=True)


def has_flow_access(user: str | None = None) -> bool:
	"""Whether `user` (default: session user) may use Flow. Used for UI hints, never as the gate."""
	if (user or frappe.session.user) == "Administrator":
		return True
	return FLOW_USER_ROLE in frappe.get_roles(user)


def ensure_flow_role() -> None:
	"""Create the Flow User role if missing. Idempotent — safe on install and every migrate."""
	if frappe.db.exists("Role", FLOW_USER_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": FLOW_USER_ROLE,
			# Flow lives in the desk, so the role must carry desk access to be useful.
			"desk_access": 1,
		}
	).insert(ignore_permissions=True)
