# Copyright (c) 2026, Noble and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, random_string, today


def _make_test_room_type(suffix):
	return frappe.get_doc({
		"doctype": "Room Type",
		"room_type_name": f"RT-RES-{suffix}",
		"rack_rate": 200,
	}).insert(ignore_permissions=True)


def _make_test_room(suffix, room_type):
	return frappe.get_doc({
		"doctype": "Room",
		"room_number": f"RM-RES-{suffix}",
		"room_type": room_type,
		"status": "Available",
	}).insert(ignore_permissions=True)


def _make_test_guest(suffix):
	return frappe.get_doc({
		"doctype": "Guest",
		"guest_name": f"Res Guest {suffix}",
		"phone": f"050{suffix[:7]}",
	}).insert(ignore_permissions=True)


def _make_base_reservation(suffix, room, room_type, guest):
	"""Return a minimal valid Reservation document (not yet saved)."""
	return frappe.get_doc({
		"doctype": "Reservation",
		"guest": guest,
		"room": room,
		"room_type": room_type,
		"check_in_date": add_days(today(), 10),
		"check_out_date": add_days(today(), 12),
		"adults": 1,
	})


class TestReservationPaymentValidation(FrappeTestCase):
	"""Regression tests for payment validation and no_post propagation."""

	def setUp(self):
		self.suffix = random_string(8)
		# Ensure past dates allowed so rooms don't cause date errors in test setup
		self._prev_allow_past = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		self._prev_strict = frappe.db.get_single_value("iHotel Settings", "strict_payment_validation")
		frappe.db.set_single_value("iHotel Settings", "strict_payment_validation", 0)
		frappe.db.commit()

		self.rt = _make_test_room_type(self.suffix)
		self.room = _make_test_room(self.suffix, self.rt.name)
		self.guest = _make_test_guest(self.suffix)

	def tearDown(self):
		for doc_name, doctype in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
		]:
			try:
				frappe.delete_doc(doctype, doc_name, ignore_permissions=True, force=True)
			except Exception:
				pass
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", self._prev_allow_past or 0)
		frappe.db.set_single_value("iHotel Settings", "strict_payment_validation", self._prev_strict or 0)
		frappe.db.commit()

	# ── Soft-warning mode (default) ───────────────────────────────────────────

	def test_credit_card_missing_last4_warns_not_blocks(self):
		"""
		In soft-warning mode, a Credit Card reservation without last4 should
		save successfully (not raise ValidationError).
		"""
		res = _make_base_reservation(self.suffix, self.room.name, self.rt.name, self.guest.name)
		res.payment_method = "Credit Card"
		res.credit_card_type = "Visa"
		# Intentionally leave credit_card_last4 and card_expiry empty

		try:
			res.insert(ignore_permissions=True)
		except frappe.ValidationError as e:
			if "Card Type" in str(e):
				raise  # Hard-block for missing card_type is expected — re-raise
			self.fail(f"Missing card last4 in soft mode should warn, not block: {e}")
		finally:
			if res.name:
				frappe.delete_doc("Reservation", res.name, ignore_permissions=True, force=True)

	def test_direct_bill_without_company_guarantee_hard_blocks(self):
		"""
		Direct Bill payment without Company guarantee type must always be a hard block,
		regardless of the strict_payment_validation toggle.
		"""
		res = _make_base_reservation(self.suffix, self.room.name, self.rt.name, self.guest.name)
		res.payment_method = "Direct Bill"
		res.guarantee_type = "Individual"  # Wrong — should be Company

		with self.assertRaises(frappe.ValidationError):
			res.insert(ignore_permissions=True)

	def test_strict_mode_blocks_on_missing_card_details(self):
		"""
		When strict_payment_validation=1, missing card last4 must raise ValidationError.
		"""
		frappe.db.set_single_value("iHotel Settings", "strict_payment_validation", 1)
		frappe.db.commit()

		res = _make_base_reservation(self.suffix, self.room.name, self.rt.name, self.guest.name)
		res.payment_method = "Credit Card"
		res.credit_card_type = "Visa"
		# Missing credit_card_last4 and card_expiry

		try:
			with self.assertRaises(frappe.ValidationError):
				res.insert(ignore_permissions=True)
		finally:
			frappe.db.set_single_value("iHotel Settings", "strict_payment_validation", 0)
			frappe.db.commit()

	def test_valid_card_expiry_format_accepted(self):
		"""
		A correctly formatted and non-expired card expiry (e.g. 12/30) should
		not produce a card-expiry warning in the payment warnings list.
		"""
		from ihotel.ihotel.doctype.reservation.reservation import _is_valid_card_expiry

		self.assertTrue(_is_valid_card_expiry("12/30"))
		self.assertFalse(_is_valid_card_expiry("13/30"))  # Invalid month
		self.assertFalse(_is_valid_card_expiry("AB/YY"))  # Non-numeric
		self.assertFalse(_is_valid_card_expiry("01/20"))  # In the past

	# ── no_post propagation ───────────────────────────────────────────────────

	def test_no_post_propagated_to_hotel_stay(self):
		"""
		When a Reservation has no_post=1, the converted Checked In record
		must also carry no_post=1 so night audit and folio posting respect it.
		"""
		from ihotel.ihotel.doctype.reservation.reservation import convert_to_hotel_stay

		res = _make_base_reservation(self.suffix, self.room.name, self.rt.name, self.guest.name)
		res.no_post = 1
		res.insert(ignore_permissions=True)

		stay_name = None
		try:
			stay_name = convert_to_hotel_stay(res.name)
			no_post_on_stay = frappe.db.get_value("Checked In", stay_name, "no_post")
			self.assertEqual(int(no_post_on_stay or 0), 1,
				"no_post flag must be propagated from Reservation to Checked In")
		finally:
			if stay_name:
				try:
					stay = frappe.get_doc("Checked In", stay_name)
					if stay.docstatus == 1:
						stay.cancel()
					frappe.delete_doc("Checked In", stay_name, ignore_permissions=True, force=True)
				except Exception:
					pass
			frappe.delete_doc("Reservation", res.name, ignore_permissions=True, force=True)
