# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, date_diff, cint, nowdate
import random
import string


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

		if self.is_new() and self.check_in_date:
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
			"pending": ["confirmed", "cancelled"],
			"confirmed": ["cancelled"],
			"cancelled": [],
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
		"""Require card details when payment method is Credit Card."""
		if self.payment_method in ("Visa", "Mastercard", "Amex", "Credit Card"):
			if not self.credit_card_type:
				frappe.throw(_("Please specify the Credit Card Type for payment method {0}.").format(
					self.payment_method))

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
def convert_to_hotel_stay(reservation_name):
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

	hotel_stay = frappe.get_doc({
		"doctype": "Checked In",
		"guest": guest,
		"room": reservation.room,
		"room_type": reservation.room_type,
		"expected_check_in": check_in_dt,
		"expected_check_out": check_out_dt,
		"room_rate": reservation.rent,
		"rate_type": reservation.rate_type,
		"business_source": reservation.business_source_category,
		"status": "Reserved",
		"deposit_amount": reservation.deposit or 0,
		"deposit_received": reservation.deposit_received or 0,
	})
	hotel_stay.insert(ignore_permissions=True)

	# Link back to the guest profile
	if guest:
		reservation.db_set("guest", guest)

	reservation.db_set("hotel_stay", hotel_stay.name)
	reservation.db_set("status", "confirmed")

	frappe.msgprint(
		_("Checked In {0} created successfully").format(
			frappe.utils.get_link_to_form("Checked In", hotel_stay.name)
		),
		indicator="green",
		alert=True,
	)

	return hotel_stay.name
