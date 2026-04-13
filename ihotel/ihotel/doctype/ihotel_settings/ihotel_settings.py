# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class iHotelSettings(Document):
	def validate(self):
		self.validate_accounting()
		self.validate_default_customer_group()

	def on_update(self):
		if self.currency:
			# Update all existing currency defaults (global + any user-specific ones)
			frappe.db.sql(
				"UPDATE `tabDefaultValue` SET defvalue=%s WHERE defkey='currency'",
				self.currency
			)
			# Insert the global row if none existed yet
			if not frappe.db.exists("DefaultValue", {"defkey": "currency", "parent": "__default"}):
				frappe.db.set_default("currency", self.currency)
			# Commit BEFORE clearing cache — prevents race condition where cache
			# repopulates from the DB before our UPDATE is visible to other connections
			frappe.db.commit()
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

	def validate_default_customer_group(self):
		"""Ensure configured customer group is selectable (not a tree/group node)."""
		if self.default_customer_group and frappe.db.get_value("Customer Group", self.default_customer_group, "is_group"):
			frappe.throw(
				_("Default Customer Group must be a non-group (leaf) Customer Group, for example Individual.")
			)
