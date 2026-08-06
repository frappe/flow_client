import frappe

from flow.permissions import FLOW_USER_ROLE, ensure_flow_role

"""Grandfather existing users onto the new Flow User role.

Before this patch every logged-in user could drive Flow; the role did not exist
and the doctypes granted access to `All`. Introducing the gate would silently
lock out everyone, including the admins who need to hand access out, so this
preserves the status quo once: every enabled System Manager keeps access, and
the site owner revokes individually afterwards.

Only System Managers are granted — not literally everyone who could reach the
API before — because the pre-gate audience included Website Users, and
reinstating that would defeat the point of the change.

Granting a role saves the User doc, which re-runs *every* installed app's User
validation. On a real site those reject for reasons that have nothing to do with
Flow — a user whose existing role mix another app forbids, say. A backfill must
never abort `bench migrate` over that, so each grant is isolated in its own
savepoint: a rejection rolls back that one user and the sweep continues. Skipped
users are listed at the end and can be granted by hand.

Fresh installs never run this: `install_app` marks all patches complete without
executing them (frappe/installer.py), so a new site starts with nobody
grandfathered in.
"""


def execute():
	ensure_flow_role()

	system_managers = frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	if not system_managers:
		return

	enabled = set(
		frappe.get_all(
			"User",
			filters={"name": ["in", system_managers], "enabled": 1, "user_type": "System User"},
			pluck="name",
		)
	)
	enabled.discard("Administrator")  # bypasses the gate anyway
	if not enabled:
		return

	already = set(
		frappe.get_all(
			"Has Role",
			filters={"role": FLOW_USER_ROLE, "parenttype": "User", "parent": ["in", list(enabled)]},
			pluck="parent",
		)
	)

	granted: list[str] = []
	skipped: list[tuple[str, str]] = []
	for index, user in enumerate(sorted(enabled - already)):
		savepoint = f"flow_grant_role_{index}"
		frappe.db.savepoint(savepoint)
		try:
			# add_roles goes through the User doc so role-change side effects still fire.
			frappe.get_doc("User", user).add_roles(FLOW_USER_ROLE)
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			# The rejecting app queues a dialog; drop it so it cannot surface later.
			frappe.clear_messages()
			skipped.append((user, str(e)[:200]))
		else:
			frappe.db.release_savepoint(savepoint)
			granted.append(user)

	if skipped:
		listed = "\n".join(f"- {user}: {reason}" for user, reason in skipped)
		print(
			f"Flow: granted '{FLOW_USER_ROLE}' to {len(granted)} user(s). "
			f"{len(skipped)} could not be granted and will not have Flow access:\n{listed}\n"
			f"Grant the role manually (User > Roles) if any of them should keep it."
		)
