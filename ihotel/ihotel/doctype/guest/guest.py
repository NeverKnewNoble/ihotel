# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import validate_email_address


def _resolve_default_customer_group(settings):
	"""Return a safe non-group customer group for auto-created customers."""
	group = settings.get("default_customer_group") or "Individual"
	if frappe.db.get_value("Customer Group", group, "is_group"):
		fallback = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		return fallback or group
	return group


def _guest_has_field(fieldname):
	"""Guard db_set calls for sites that haven't migrated Guest columns yet."""
	return frappe.get_meta("Guest").has_field(fieldname)


class Guest(Document):
	def validate(self):
		self.validate_contact_info()
		self._warn_incomplete_profile()
		self._warn_potential_duplicates()

	def after_insert(self):
		self._sync_customer()

	def on_update(self):
		self._sync_customer()

	def _warn_incomplete_profile(self):
		"""Soft-warn when key identity/contact fields are missing.

		Does not block save — informs staff so they can complete the profile
		during the interaction rather than having data gaps discovered later.
		"""
		missing = []
		if not self.phone and not self.email:
			missing.append(_("At least one contact method (phone or email) is recommended."))
		if not self.id_type or not self.id_number:
			missing.append(_("Guest ID type and number are recommended for compliance and check-in."))
		if missing:
			frappe.msgprint(
				_("Guest profile is incomplete — please fill in when possible:<br><ul>{0}</ul>").format(
					"".join(f"<li>{m}</li>" for m in missing)
				),
				title=_("Incomplete Guest Profile"),
				indicator="orange",
			)

	def _warn_potential_duplicates(self):
		"""Soft-warn if another Guest record shares the same phone or email.

		Helps front desk catch accidental duplicates before saving. Does not block save
		because legitimate guests may share a phone (family bookings) or a phone
		may be reused on prepaid numbers.
		"""
		if not (self.phone or self.email):
			return

		conditions = []
		values = {}
		if self.phone:
			conditions.append("phone = %(phone)s")
			values["phone"] = self.phone
		if self.email:
			conditions.append("email = %(email)s")
			values["email"] = self.email

		# Exclude self when editing an existing record
		exclude_clause = "AND name != %(name)s" if not self.is_new() else ""
		if not self.is_new():
			values["name"] = self.name

		where = " OR ".join(conditions)
		matches = frappe.db.sql(
			f"SELECT name, guest_name FROM `tabGuest` WHERE ({where}) {exclude_clause} LIMIT 3",
			values, as_dict=True
		)
		if matches:
			names_list = ", ".join(
				f"{m.guest_name} ({m.name})" for m in matches
			)
			frappe.msgprint(
				_("Possible duplicate guest(s) found with the same phone or email: {0}. "
				  "Please confirm this is a new profile.").format(names_list),
				title=_("Possible Duplicate Guest"),
				indicator="orange",
			)

	def _sync_customer(self):
		"""Create or update an ERPXpand Customer linked to this guest.

		Reads the linked customer from the DB (not self) to avoid double-run issues
		when after_insert and on_update fire back-to-back on a new guest.
		Records sync outcome in sync_status/sync_error so staff can see and retry failures.
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
				# Mark synced only if status wasn't already Synced (avoids redundant writes)
				if _guest_has_field("sync_status"):
					if frappe.db.get_value("Guest", self.name, "sync_status") != "Synced":
						self.db_set("sync_status", "Synced", update_modified=False)
				return

			# No link yet — find by name or create
			existing = frappe.db.get_value("Customer", {"customer_name": self.guest_name})
			if existing:
				self.db_set("customer", existing, update_modified=False)
				if _guest_has_field("sync_status"):
					self.db_set("sync_status", "Synced", update_modified=False)
				return

			# Some sites enforce Customer.mobile_no as mandatory (HR/Employee customizations).
			# Skip auto-customer creation when guest mobile is empty to avoid blocking guest saves.
			if not self.phone:
				return

			settings = frappe.get_single("iHotel Settings")
			customer_payload = {
				"doctype": "Customer",
				"customer_name": self.guest_name,
				"custom_customer_id": self.guest_name,
				"customer_type": "Individual",
				"customer_group": _resolve_default_customer_group(settings),
				"territory": settings.get("default_territory") or "All Territories",
			}
			if self.phone:
				# Set both keys for compatibility with custom hooks across sites/apps.
				mobile = str(self.phone)
				customer_payload["mobile_no"] = mobile
				customer_payload["mobile_number"] = mobile

			cust = frappe.get_doc(customer_payload)
			cust.insert(ignore_permissions=True)
			self.db_set("customer", cust.name, update_modified=False)
			if _guest_has_field("sync_status"):
				self.db_set("sync_status", "Synced", update_modified=False)
			if _guest_has_field("sync_error"):
				self.db_set("sync_error", "", update_modified=False)
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(f"iHotel: Could not sync Guest {self.name} to Customer: {error_msg}")
			# Persist failure so staff can see it on the form and use the Retry button
			if _guest_has_field("sync_status"):
				self.db_set("sync_status", "Failed", update_modified=False)
			if _guest_has_field("sync_error"):
				self.db_set("sync_error", error_msg[:500], update_modified=False)
			frappe.msgprint(
				_("Guest saved, but could not sync to ERPXpand Customer. Use Retry Sync on the form or check the Error Log."),
				indicator="orange",
				alert=True,
			)

	def validate_contact_info(self):
		if self.email:
			if not validate_email_address(self.email):
				frappe.throw(_("Please enter a valid email address"))

		if self.phone:
			# Accept common phone formatting while still enforcing a clean numeric core.
			phone = (
				str(self.phone)
				.strip()
				.replace(" ", "")
				.replace("-", "")
				.replace("(", "")
				.replace(")", "")
			)
			if phone.startswith("+"):
				phone = phone[1:]
			if not phone.isdigit() or len(phone) < 7 or len(phone) > 15:
				frappe.throw(_("Please enter a valid phone number (7-15 digits)"))


@frappe.whitelist()
def get_duplicate_candidates(phone=None, email=None, exclude_name=None):
	"""Return up to 5 existing Guest records sharing the provided phone or email.
	Used by the Guest form to show a live duplicate warning while the user types.
	"""
	if not phone and not email:
		return []
	conditions = []
	values = {}
	if phone:
		conditions.append("phone = %(phone)s")
		values["phone"] = phone
	if email:
		conditions.append("email = %(email)s")
		values["email"] = email
	exclude_clause = "AND name != %(exclude)s" if exclude_name else ""
	if exclude_name:
		values["exclude"] = exclude_name
	where = " OR ".join(conditions)
	return frappe.db.sql(
		f"SELECT name, guest_name, phone, email FROM `tabGuest` WHERE ({where}) {exclude_clause} LIMIT 5",
		values, as_dict=True
	)


@frappe.whitelist()
def retry_customer_sync(guest_name):
	"""Re-run the ERPXpand Customer sync for a guest that previously failed."""
	frappe.has_permission("Guest", "write", guest_name, throw=True)
	doc = frappe.get_doc("Guest", guest_name)
	doc._sync_customer()
	status = frappe.db.get_value("Guest", guest_name, "sync_status")
	if status == "Synced":
		frappe.msgprint(_("Customer sync successful."), indicator="green", alert=True)
	else:
		frappe.msgprint(_("Customer sync failed again. Check the Error Log for details."),
			indicator="red", alert=True)
	return status


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
