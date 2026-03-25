# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class iHotelSettings(Document):
	def validate(self):
		self.validate_accounting()

	def on_update(self):
		if self.currency:
			# Update every currency default row (global + user-specific) so no
			# user-level GHS entry can silently override the global USD setting
			frappe.db.sql(
				"UPDATE `tabDefaultValue` SET defvalue=%s WHERE defkey='currency'",
				self.currency
			)
			# Insert global row if none existed yet
			if not frappe.db.exists("DefaultValue", {"defkey": "currency", "parent": "__default"}):
				frappe.db.set_default("currency", self.currency)
			frappe.clear_cache()

	def validate_accounting(self):
		"""If accounting integration is on, require Company + both items."""
		if not self.get("enable_accounting_integration"):
			return
		if not self.company:
			frappe.throw(_("Please set a Company before enabling accounting integration."))
		if not self.room_charge_item:
			frappe.throw(_("Please set a Room Charge Item before enabling accounting integration."))
		if not self.extra_charge_item:
			frappe.throw(_("Please set an Extra Charges Item before enabling accounting integration."))
