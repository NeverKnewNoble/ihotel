# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import validate_email_address


class Guest(Document):
	def validate(self):
		self.validate_contact_info()

	def after_insert(self):
		self._sync_customer()

	def on_update(self):
		self._sync_customer()

	def _sync_customer(self):
		"""Create or update an ERPXpand Customer linked to this guest.

		Reads the linked customer from the DB (not self) to avoid double-run issues
		when after_insert and on_update fire back-to-back on a new guest.
		"""
		if not self.guest_name:
			return
		try:
			db_customer = frappe.db.get_value("Guest", self.name, "customer")

			if db_customer:
				# Guest already linked — check if name changed (rename scenario)
				current_name = frappe.db.get_value("Customer", db_customer, "customer_name")
				if current_name and current_name != self.guest_name:
					frappe.db.set_value("Customer", db_customer, "customer_name", self.guest_name,
					                    update_modified=False)
				return

			# No link yet — find by name or create
			existing = frappe.db.get_value("Customer", {"customer_name": self.guest_name})
			if existing:
				self.db_set("customer", existing, update_modified=False)
				return

			settings = frappe.get_single("iHotel Settings")
			cust = frappe.get_doc({
				"doctype": "Customer",
				"customer_name": self.guest_name,
				"custom_customer_id": self.guest_name,
				"customer_type": "Individual",
				"customer_group": settings.get("default_customer_group") or "All Customer Groups",
				"territory": settings.get("default_territory") or "All Territories",
				"mobile_no": self.phone,
			})
			cust.insert(ignore_permissions=True)
			self.db_set("customer", cust.name, update_modified=False)
		except Exception as e:
			frappe.log_error(f"iHotel: Could not sync Guest {self.name} to Customer: {str(e)}")
			frappe.msgprint(
				_("Guest saved, but could not sync to ERPXpand Customer. Check the Error Log."),
				indicator="orange",
				alert=True,
			)

	def validate_contact_info(self):
		if self.email:
			if not validate_email_address(self.email):
				frappe.throw(_("Please enter a valid email address"))

		if self.phone:
			phone = self.phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
			if phone.startswith("+"):
				phone = phone[1:]
			if not phone.isdigit() or len(phone) < 7 or len(phone) > 15:
				frappe.throw(_("Please enter a valid phone number (7-15 digits)"))


@frappe.whitelist()
def get_guest_bad_traces(guest_name):
	"""Return all Bad traces for a guest."""
	return frappe.db.get_all(
		"Guest Trace",
		filters={"parent": guest_name, "parenttype": "Guest", "trace_type": "Bad"},
		fields=["category", "date", "description", "recorded_by"],
		order_by="date desc",
	)


@frappe.whitelist()
def get_guest_stats(guest_name):
	"""Return computed stay statistics for a guest."""
	result = frappe.db.sql("""
		SELECT
			COUNT(name)                          AS total_stays,
			IFNULL(SUM(nights), 0)               AS total_nights,
			IFNULL(SUM(total_amount), 0)         AS total_revenue,
			MAX(DATE(actual_check_in))           AS last_stay_date
		FROM `tabChecked In`
		WHERE guest = %s
		  AND status = 'Checked Out'
		  AND docstatus = 1
	""", guest_name, as_dict=True)
	return result[0] if result else {}
