# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

# Folio lines and night-audit logic link to these Charge Type document names.
DEFAULT_FOLIO_CHARGE_TYPES = ("Room Charge", "Additional Service")


def _fallback_hotel_account_for_new_charge_type():
	"""First leaf Revenue account, else any leaf account — needed to satisfy Charge Type.child table."""
	rows = frappe.get_all(
		"Hotel Account",
		filters={"is_group": 0, "account_type": "Revenue"},
		fields=["name"],
		order_by="creation asc",
		limit_page_length=1,
	)
	if rows:
		return rows[0].name
	rows = frappe.get_all(
		"Hotel Account",
		filters={"is_group": 0},
		fields=["name"],
		order_by="creation asc",
		limit_page_length=1,
	)
	return rows[0].name if rows else None


def ensure_default_charge_types():
	"""
	Create standard Charge Type masters if missing.

	Folio Charge.charge_type is a Link; posting room/add-on charges uses names
	Room Charge and Additional Service. Without those documents, submit fails with
	“Could not find Row #N: Charge Type: …”.
	"""
	if not frappe.db.exists("DocType", "Charge Type"):
		return

	account = _fallback_hotel_account_for_new_charge_type()
	if not account:
		frappe.throw(
			_(
				"Add at least one Hotel Account (a leaf Revenue account is best) before posting "
				"folio charges. Charge Types need one account mapping row."
			)
		)

	for charge_name in DEFAULT_FOLIO_CHARGE_TYPES:
		if frappe.db.exists("Charge Type", charge_name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Charge Type",
				"charge_name": charge_name,
				"accounts": [{"account": account}],
			}
		)
		doc.insert(ignore_permissions=True)


def resolve_hotel_account_for_charge_type(charge_type, company=None, department=None):
	"""
	Return mapped Hotel Account for a Charge Type.
	Priority: exact company+department, then company-only, then global+department, then global default.
	"""
	if not charge_type:
		return None

	company = company or frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")

	rows = frappe.get_all(
		"Charge Type Account",
		filters={"parent": charge_type, "parenttype": "Charge Type"},
		fields=["company", "department", "account"],
		order_by="idx asc",
	)
	if not rows:
		return None

	def is_blank(value):
		return not value

	for row in rows:
		if row.company == company and row.department == department:
			return row.account
	for row in rows:
		if row.company == company and is_blank(row.department):
			return row.account
	for row in rows:
		if is_blank(row.company) and row.department == department:
			return row.account
	for row in rows:
		if is_blank(row.company) and is_blank(row.department):
			return row.account

	return rows[0].account


class ChargeType(Document):
	def validate(self):
		self.validate_unique_company_department()

	def validate_unique_company_department(self):
		seen = set()
		for row in self.get("accounts", []):
			key = (row.company or "", row.department or "")
			if key in seen:
				frappe.throw(
					_("Duplicate account mapping for Company {0} and Department {1}.").format(
						row.company or _("(Any)"),
						row.department or _("(Any)"),
					)
				)
			seen.add(key)
