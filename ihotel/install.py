import frappe


REQUIRED_ROLES = [
	"Night Auditor",
]


def after_install():
	"""Idempotent post-install / post-migrate setup for iHotel."""
	ensure_required_roles()


def ensure_required_roles():
	"""Create any iHotel-specific roles that don't already exist."""
	for role_name in REQUIRED_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}).insert(ignore_permissions=True)
