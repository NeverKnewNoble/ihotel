# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, date_diff, cint, nowdate
import random
import string


def _is_valid_card_expiry(expiry):
	"""Return True if expiry matches MM/YY format and is not obviously in the past."""
	import re
	if not re.match(r"^\d{2}/\d{2}$", str(expiry or "")):
		return False
	try:
		month, year = int(expiry[:2]), int(expiry[3:])
		if not (1 <= month <= 12):
			return False
		from frappe.utils import getdate
		from datetime import date
		today = date.today()
		full_year = 2000 + year
		# Allow cards that expire this month
		return (full_year, month) >= (today.year, today.month)
	except Exception:
		return False


def _resolve_default_customer_group(settings):
	"""Return a safe non-group customer group for auto-created customers."""
	group = settings.get("default_customer_group") or "Individual"
	if frappe.db.get_value("Customer Group", group, "is_group"):
		fallback = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		return fallback or group
	return group


class Reservation(Document):
	def validate(self):
		self.validate_restricted_guest()
		self.validate_dates()
		self.calculate_days()
		self.calculate_totals()
		self.validate_room_availability()
		self.validate_guest_capacity()
		self.validate_status_transition()
		self.validate_payment_method()
		self.sync_guest_details()

	def validate_restricted_guest(self):
		"""Warn (but don't hard-block) if the linked guest profile is restricted."""
		if not self.guest:
			return
		restricted, note = frappe.db.get_value(
			"Guest", self.guest, ["restricted", "restriction_note"]
		) or (0, "")
		if restricted:
			msg = _("Guest {0} is marked as Restricted.").format(self.guest)
			if note:
				msg += " {0}: {1}".format(_("Reason"), note)
			frappe.throw(msg, title=_("Restricted Guest"))

	def validate_dates(self):
		if self.check_in_date and self.check_out_date:
			if getdate(self.check_in_date) >= getdate(self.check_out_date):
				frappe.throw(_("Check-in date must be before check-out date"))

		if self.is_new() and self.check_in_date and not self.flags.get("from_booking_com") and not self.flags.get("from_ota_sync"):
			if getdate(self.check_in_date) < getdate(nowdate()):
				allow_past = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
				if not allow_past:
					frappe.throw(_("Check-in date cannot be in the past"))

	def calculate_days(self):
		if self.check_in_date and self.check_out_date:
			self.days = date_diff(self.check_out_date, self.check_in_date)

	def calculate_totals(self):
		from frappe.utils import flt

		rate_lines_total   = round(sum(flt(r.amount) for r in (self.rate_lines or [])), 2)
		self.total_charges = rate_lines_total
		self.tax           = self._compute_tax(rate_lines_total)
		self.total_rental  = round(rate_lines_total + self.tax, 2)
		# Keep rent in sync (nightly rate) for convert_to_hotel_stay
		self.rent = round(rate_lines_total / (self.days or 1), 2)

	def _compute_tax(self, net_total):
		"""Compute tax from the first rate_line's Rate Type tax_schedule."""
		from frappe.utils import flt, cint
		rate_type_name = next(
			(r.rate_type for r in (self.rate_lines or []) if r.rate_type), None
		)
		if not rate_type_name:
			return 0.0
		try:
			rt = frappe.get_cached_doc("Rate Type", rate_type_name)
		except Exception:
			return 0.0
		amounts = []
		for row in (rt.tax_schedule or []):
			ct   = row.charge_type or "On Net Total"
			rate = flt(row.rate)
			amt  = 0.0
			if ct == "On Net Total":
				amt = net_total * rate / 100
			elif ct == "Actual":
				amt = rate
			elif ct == "On Previous Row Amount":
				idx = cint(row.row_id or 1) - 1
				amt = (amounts[idx] if idx < len(amounts) else 0) * rate / 100
			elif ct == "On Previous Row Total":
				idx = cint(row.row_id or 1) - 1
				amt = (net_total + sum(amounts[:idx + 1])) * rate / 100
			amounts.append(round(amt, 2))
		return round(sum(amounts), 2)

	def validate_room_availability(self):
		if not self.room or self.status == "cancelled":
			return

		# Block rooms that are permanently out of service
		room_status = frappe.db.get_value("Room", self.room, "status")
		if room_status in ("Out of Order", "Out of Service"):
			frappe.throw(
				_("Room {0} is {1} and cannot be reserved.").format(self.room, room_status)
			)

		overlapping = frappe.db.sql("""
			SELECT name FROM `tabReservation`
			WHERE room = %s
			AND status != 'cancelled'
			AND name != %s
			AND (
				(check_in_date < %s AND check_out_date > %s)
				OR (check_in_date < %s AND check_out_date > %s)
				OR (check_in_date >= %s AND check_out_date <= %s)
			)
		""", (
			self.room, self.name or "",
			self.check_out_date, self.check_in_date,
			self.check_out_date, self.check_in_date,
			self.check_in_date, self.check_out_date,
		), as_dict=True)

		if overlapping:
			frappe.throw(
				_("Room {0} is not available for the selected dates. Overlapping reservation: {1}").format(
					self.room, overlapping[0].name
				)
			)

	def validate_guest_capacity(self):
		total_guests = (self.adults or 0) + (self.children or 0)
		if total_guests and self.room_type:
			max_capacity = frappe.db.get_value("Room Type", self.room_type, "maximum_capacity")
			if max_capacity and total_guests > cint(max_capacity):
				frappe.throw(
					_("Number of guests ({0}) exceeds maximum capacity ({1}) for room type {2}").format(
						total_guests, max_capacity, self.room_type
					)
				)

	def validate_status_transition(self):
		if self.is_new():
			return

		old_status = frappe.db.get_value("Reservation", self.name, "status")
		if not old_status or old_status == self.status:
			return

		valid_transitions = {
			"pending":    ["confirmed", "cancelled"],
			"confirmed":  ["cancelled", "checked_in"],
			"checked_in": ["cancelled"],
			"cancelled":  [],
		}

		allowed = valid_transitions.get(old_status, [])
		if self.status not in allowed:
			frappe.throw(
				_("Cannot change status from {0} to {1}. Allowed: {2}").format(
					old_status, self.status, ", ".join(allowed) or "None"
				)
			)

		# Auto-generate cancellation number when cancelling
		if self.status == "cancelled" and not self.cancellation_number:
			self.cancellation_number = "CXL-" + "".join(
				random.choices(string.ascii_uppercase + string.digits, k=8)
			)
			self.calculate_cancellation_fee()

	def calculate_cancellation_fee(self):
		"""Calculate cancellation penalty based on the Rate Type's cancellation policy."""
		if not self.rate_type:
			self.cancellation_fee = 0
			return

		try:
			rt = frappe.get_cached_doc("Rate Type", self.rate_type)
		except Exception:
			self.cancellation_fee = 0
			return

		fee_type = rt.cancellation_fee_type or "None"

		if fee_type == "None":
			self.cancellation_fee = 0
		elif fee_type == "First Night":
			self.cancellation_fee = self.rent or 0
		elif fee_type == "Fixed Amount":
			self.cancellation_fee = rt.cancellation_fee_value or 0
		elif fee_type == "Percentage of Stay":
			pct = (rt.cancellation_fee_value or 0) / 100.0
			self.cancellation_fee = round((self.total_charges or 0) * pct, 2)
		else:
			self.cancellation_fee = 0

	def validate_payment_method(self):
		"""Validate payment method details.

		Hard-blocks: structurally impossible combinations (e.g. Direct Bill without Company guarantee).
		Soft-warnings: missing-but-recoverable details (card last4, expiry, cheque fields).
		Warnings use msgprint so staff are informed without being blocked mid-shift.
		"""
		pm = self.payment_method or ""
		warnings = []

		if pm in ("Visa", "Mastercard", "Amex", "Credit Card"):
			if not self.credit_card_type:
				frappe.throw(_("Please specify the Credit Card Type for payment method {0}.").format(pm))
			# Soft-warn on incomplete card capture
			if not self.credit_card_last4:
				warnings.append(_("Card last 4 digits are missing — recommended for reconciliation."))
			elif not str(self.credit_card_last4).isdigit() or len(str(self.credit_card_last4)) != 4:
				warnings.append(_("Card last 4 digits should be exactly 4 numeric digits."))
			if not self.card_expiry:
				warnings.append(_("Card expiry (MM/YY) is missing — recommended for chargeback protection."))
			elif not _is_valid_card_expiry(self.card_expiry):
				warnings.append(_("Card expiry format should be MM/YY (e.g. 08/27)."))

		elif pm == "Cheque":
			if not self.cheque_number:
				warnings.append(_("Cheque number is missing."))
			if not self.date_of_the_cheque:
				warnings.append(_("Cheque date is missing."))
			if not self.bank_name:
				warnings.append(_("Bank name is missing."))
			if not self.cheque_amount or float(self.cheque_amount or 0) <= 0:
				warnings.append(_("Cheque amount should be greater than zero."))

		elif pm == "Direct Bill":
			# Hard-block: Direct Bill requires Company guarantee
			if self.guarantee_type != "Company":
				frappe.throw(_("Direct Bill payment requires Guarantee Type to be set to Company."))
			# Soft-warn if no customer linked
			if not self.customer_id:
				warnings.append(_("Direct Bill selected but no Customer ID is linked — required for city-ledger billing."))

		if warnings:
			# When strict mode is enabled in iHotel Settings, block on incomplete payment details.
			# Default is soft-warning to avoid disrupting fast check-in flows.
			strict = frappe.db.get_single_value("iHotel Settings", "strict_payment_validation")
			msg = _("Payment details incomplete — please review before confirming:<br><ul>{0}</ul>").format(
				"".join(f"<li>{w}</li>" for w in warnings)
			)
			if strict:
				frappe.throw(msg, title=_("Payment Details Required"))
			else:
				frappe.msgprint(msg, title=_("Payment Details Warning"), indicator="orange")

	def sync_guest_details(self):
		"""If a Guest profile is selected, auto-fill contact fields."""
		if self.guest and not self.full_name:
			guest = frappe.get_cached_doc("Guest", self.guest)
			self.full_name = guest.guest_name
			if not self.email_address:
				self.email_address = guest.email
			if not self.phone_number:
				self.phone_number = guest.phone
			if not self.date_of_birth:
				self.date_of_birth = guest.date_of_birth


@frappe.whitelist()
def create_proforma_invoice(reservation_name):
	"""Create a draft Sales Invoice (proforma) for the reservation.
	Requires write access to the Reservation. Permission-bypass inserts are logged with actor.
	"""
	frappe.has_permission("Reservation", "write", reservation_name, throw=True)
	res = frappe.get_doc("Reservation", reservation_name)

	if res.proforma_invoice:
		frappe.throw(_("A proforma invoice already exists for this reservation: {0}").format(
			res.proforma_invoice
		))

	if res.status == "cancelled":
		frappe.throw(_("Cannot create a proforma invoice for a cancelled reservation."))

	settings = frappe.get_cached_doc("iHotel Settings")

	company = settings.company
	if not company:
		frappe.throw(_("Please set Company in iHotel Settings → Accounting before creating a proforma invoice."))

	room_charge_item = settings.room_charge_item
	if not room_charge_item:
		frappe.throw(_("Please set Room Charge Item in iHotel Settings → Accounting before creating a proforma invoice."))

	# Resolve or create the customer
	customer = res.customer_id
	if not customer:
		guest_name = res.full_name or (
			frappe.db.get_value("Guest", res.guest, "guest_name") if res.guest else None
		)
		if not guest_name:
			frappe.throw(_("Please set a Guest Profile or Full Name on the reservation before creating a proforma invoice."))

		customer = frappe.db.get_value("Customer", {"customer_name": guest_name})
		if not customer:
			guest_phone = frappe.db.get_value("Guest", res.guest, "phone") if res.guest else None
			cust = frappe.get_doc({
				"doctype": "Customer",
				"customer_name": guest_name,
				"customer_type": "Individual",
				"customer_group": _resolve_default_customer_group(settings),
				"territory": settings.default_territory or "All Territories",
				"mobile_no": guest_phone,
			})
			cust.insert(ignore_permissions=True)
			customer = cust.name

	income_account = settings.room_revenue_account or None

	# Build invoice items from rate_lines
	items = []
	for line in (res.rate_lines or []):
		item_row = {
			"item_code": room_charge_item,
			"item_name": line.description or line.rate_type or "Room Charge",
			"description": "{0} | Room: {1} | {2} to {3}".format(
				line.description or line.rate_type or "Room Charge",
				res.room or res.room_type or "-",
				res.check_in_date or "-",
				res.check_out_date or "-",
			),
			"qty": 1,
			"rate": line.amount or 0,
		}
		if income_account:
			item_row["income_account"] = income_account
		items.append(item_row)

	if not items:
		# Fallback: single line for total charges
		item_row = {
			"item_code": room_charge_item,
			"item_name": "Room Charge",
			"description": "Room Charge | {0} | {1} to {2}".format(
				res.room_type or res.room or "-",
				res.check_in_date or "-",
				res.check_out_date or "-",
			),
			"qty": 1,
			"rate": res.total_charges or 0,
		}
		if income_account:
			item_row["income_account"] = income_account
		items.append(item_row)

	# Tax as a separate line if applicable
	if (res.tax or 0) > 0:
		tax_row = {
			"item_code": room_charge_item,
			"item_name": "Tax",
			"description": "Tax on room charges",
			"qty": 1,
			"rate": res.tax,
		}
		if income_account:
			tax_row["income_account"] = income_account
		items.append(tax_row)

	sinv = frappe.get_doc({
		"doctype": "Sales Invoice",
		"customer": customer,
		"company": company,
		"posting_date": frappe.utils.today(),
		"due_date": str(res.check_in_date) if res.check_in_date else frappe.utils.today(),
		"remarks": _("Proforma Invoice for Reservation {0}").format(reservation_name),
		"is_return": 0,
		"disable_rounded_total": 1,
		"items": items,
	})
	sinv.flags.ignore_permissions = True
	sinv.insert()

	res.db_set("proforma_invoice", sinv.name)

	frappe.msgprint(
		_("Proforma Invoice {0} created successfully.").format(
			frappe.utils.get_link_to_form("Sales Invoice", sinv.name)
		),
		indicator="green",
		alert=True,
	)

	return sinv.name


@frappe.whitelist()
def convert_to_hotel_stay(reservation_name):
	frappe.has_permission("Reservation", "write", reservation_name, throw=True)
	reservation = frappe.get_doc("Reservation", reservation_name)

	if reservation.status == "cancelled":
		frappe.throw(_("Cannot convert a cancelled reservation"))

	if reservation.hotel_stay:
		frappe.throw(_("This reservation has already been converted to Checked In: {0}").format(
			reservation.hotel_stay
		))

	# Use linked Guest profile or look up / create from full_name
	guest = reservation.guest
	if not guest and reservation.full_name:
		guest = frappe.db.get_value("Guest", {"guest_name": reservation.full_name})
		if not guest:
			guest_doc = frappe.get_doc({
				"doctype": "Guest",
				"guest_name": reservation.full_name,
				"email": reservation.email_address,
				"phone": reservation.phone_number,
			})
			guest_doc.insert(ignore_permissions=True)
			guest = guest_doc.name

	# Build check-in/out datetimes
	check_in_dt = None
	check_out_dt = None
	if reservation.check_in_date:
		check_in_time = str(reservation.check_in_time or "14:00:00")
		check_in_dt = f"{reservation.check_in_date} {check_in_time}"
	if reservation.check_out_date:
		check_out_time = str(reservation.check_out_time or "11:00:00")
		check_out_dt = f"{reservation.check_out_date} {check_out_time}"

	# Map reservation payment method → folio payment method + detail
	pm      = reservation.payment_method or ""
	cc_type = reservation.credit_card_type or ""

	if pm == "Credit Card":
		method_map = {
			"Visa":             "Visa",
			"Mastercard":       "Mastercard",
			"American Express": "Amex",
		}
		deposit_method = method_map.get(cc_type, "Visa")
		detail_parts   = [cc_type or "Credit Card"]
		if reservation.credit_card_last4:
			detail_parts.append(f"ending {reservation.credit_card_last4}")
		if reservation.card_expiry:
			detail_parts.append(f"exp {reservation.card_expiry}")
		payment_detail = " ".join(detail_parts)

	elif pm == "Cash":
		deposit_method = "Cash"
		payment_detail = "Cash"

	elif pm == "Cheque":
		deposit_method = "Cheque"
		parts = []
		if reservation.cheque_number:
			parts.append(f"Cheque #{reservation.cheque_number}")
		if reservation.bank_name:
			parts.append(f"Bank: {reservation.bank_name}")
		if reservation.bank_account_no:
			parts.append(f"Acct: {reservation.bank_account_no}")
		payment_detail = " | ".join(parts) if parts else "Cheque"

	elif pm == "Direct Bill":
		deposit_method = "City Ledger"
		payment_detail = f"Direct Bill — {reservation.customer_id or ''}"

	else:
		deposit_method = None
		payment_detail = ""

	# Copy all rate lines so totals, tax, and folio charges are computed correctly
	rate_lines = [
		{
			"rate_type":    rl.rate_type,
			"room_type":    rl.room_type,
			"rate_column":  rl.rate_column,
			"description":  rl.description,
			"rate":         rl.rate,
			"discount1":    rl.discount1 or 0,
			"discount2":    rl.discount2 or 0,
			"discount3":    rl.discount3 or 0,
			"amount":       rl.amount,
		}
		for rl in (reservation.rate_lines or [])
	]

	hotel_stay = frappe.get_doc({
		"doctype":              "Checked In",
		"guest":                guest,
		"room":                 reservation.room,
		"room_type":            reservation.room_type,
		"expected_check_in":    check_in_dt,
		"expected_check_out":   check_out_dt,
		"color":                reservation.color,
		"adults":               reservation.adults or 1,
		"children":             reservation.children or 0,
		"business_source":      reservation.business_source_category,
		"turndown_requested":   reservation.turndown_requested or 0,
		"status":               "Reserved",
		"deposit_amount":       reservation.deposit or 0,
		"deposit_method":       deposit_method or "",
		"payment_detail":       payment_detail,
		"rate_lines":           rate_lines,
		# Propagate no_post so night audit and folio respect the billing block
		"no_post":              reservation.no_post or 0,
	})
	hotel_stay.insert(ignore_permissions=True)

	# Submit the stay. On submit failure, cancel and delete the draft to avoid orphan records.
	try:
		hotel_stay.submit()
	except Exception as submit_err:
		try:
			frappe.delete_doc("Checked In", hotel_stay.name, ignore_permissions=True, force=True)
		except Exception:
			pass
		frappe.throw(
			_("Failed to activate check-in record. Rolled back. Error: {0}").format(str(submit_err))
		)

	# Link back to the guest profile and mark reservation as checked in
	if guest:
		reservation.db_set("guest", guest)

	reservation.db_set("hotel_stay", hotel_stay.name)
	reservation.db_set("status", "checked_in")

	frappe.msgprint(
		_("Guest checked in successfully. Stay record: {0}").format(
			frappe.utils.get_link_to_form("Checked In", hotel_stay.name)
		),
		indicator="green",
		alert=True,
	)

	return hotel_stay.name
