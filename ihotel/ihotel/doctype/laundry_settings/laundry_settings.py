# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LaundrySettings(Document):
	pass


@frappe.whitelist()
def load_items_from_erpxpand(item_group):
	"""Fetch all active ERPXpand Items under the given Item Group and create Laundry Items."""
	frappe.only_for(["System Manager", "Laundry Manager"])
	if not item_group:
		frappe.throw(_("Item Group is required."))

	items = frappe.get_all(
		"Item",
		filters={"item_group": item_group, "disabled": 0},
		fields=["item_code", "item_name", "standard_rate"],
	)

	added = 0
	skipped = 0
	for item in items:
		if frappe.db.exists("Laundry Item", {"item_code": item.item_code}):
			skipped += 1
			continue
		if frappe.db.exists("Laundry Item", item.item_name):
			skipped += 1
			continue
		li = frappe.get_doc({
			"doctype": "Laundry Item",
			"item_code": item.item_code,
			"item_name": item.item_name,
			"item_group": item_group,
			"guest_price": item.standard_rate or 0,
			"outsider_price": item.standard_rate or 0,
			"is_active": 1,
		})
		li.insert(ignore_permissions=True)
		added += 1

	return {"added": added, "skipped": skipped}
