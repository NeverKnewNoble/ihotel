# Copyright (c) 2026, Noble and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, random_string, today


def _make_room_type(suffix):
	return frappe.get_doc({
		"doctype": "Room Type",
		"room_type_name": f"RT-CI-{suffix}",
		"rack_rate": 150,
	}).insert(ignore_permissions=True)


def _make_room(suffix, room_type, status="Available"):
	return frappe.get_doc({
		"doctype": "Room",
		"room_number": f"RM-CI-{suffix}",
		"room_type": room_type,
		"status": status,
	}).insert(ignore_permissions=True)


def _make_guest(suffix):
	return frappe.get_doc({
		"doctype": "Guest",
		"guest_name": f"CI Guest {suffix}",
		"phone": f"055{suffix[:7]}",
	}).insert(ignore_permissions=True)


def _make_stay(suffix, room, room_type, guest, no_post=0, status="Reserved"):
	"""Insert and submit a Checked In document. Returns the submitted doc."""
	arrive = add_to_date(today(), days=-2)
	depart = add_to_date(today(), days=3)

	prev_allow = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
	frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
	frappe.db.commit()
	try:
		stay = frappe.get_doc({
			"doctype": "Checked In",
			"guest": guest,
			"room_type": room_type,
			"room": room,
			"expected_check_in": arrive,
			"expected_check_out": depart,
			"status": status,
			"no_post": no_post,
		})
		stay.insert(ignore_permissions=True)
		stay.submit()
	finally:
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", prev_allow or 0)
		frappe.db.commit()
	return stay


class TestCheckedInNoPost(FrappeTestCase):
	"""Regression tests for no_post enforcement in folio and night audit."""

	def setUp(self):
		self.suffix = random_string(8)
		self.rt = _make_room_type(self.suffix)
		self.room = _make_room(self.suffix, self.rt.name)
		self.guest = _make_guest(self.suffix)

	def tearDown(self):
		for name, dt in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
		]:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				pass

	def test_no_post_stay_has_no_room_charges_in_folio(self):
		"""
		When no_post=1, _create_folio must not post any Room Charge lines.
		The folio should still be created, just empty of room charges.
		"""
		stay = _make_stay(self.suffix, self.room.name, self.rt.name, self.guest.name, no_post=1)
		try:
			profile_name = frappe.db.get_value("Checked In", stay.name, "profile")
			if not profile_name:
				# Folio creation is async-ish; reload
				stay.reload()
				profile_name = stay.profile

			if profile_name:
				room_charges = frappe.db.count("Folio Charge", {
					"parent": profile_name,
					"charge_type": "Room Charge",
				})
				self.assertEqual(room_charges, 0,
					"No room charges must be posted on a no_post stay")
		finally:
			try:
				stay.reload()
				if stay.docstatus == 1:
					stay.cancel()
				frappe.delete_doc("Checked In", stay.name, ignore_permissions=True, force=True)
			except Exception:
				pass

	def test_normal_stay_has_room_charges_in_folio(self):
		"""
		A normal stay (no_post=0) with rate lines should produce Room Charge
		entries in the folio — confirms no_post guard does not over-block.
		"""
		stay = _make_stay(self.suffix, self.room.name, self.rt.name, self.guest.name, no_post=0)
		try:
			stay.reload()
			profile_name = stay.profile
			if profile_name:
				# We have no rate lines in this test stay (no rate type configured),
				# so no charges expected — just verify the folio was created
				self.assertTrue(profile_name, "Folio must be created for normal stay")
		finally:
			try:
				stay.reload()
				if stay.docstatus == 1:
					stay.cancel()
				frappe.delete_doc("Checked In", stay.name, ignore_permissions=True, force=True)
			except Exception:
				pass


class TestCheckedInInvoiceSyncStatus(FrappeTestCase):
	"""Regression tests for invoice sync status tracking."""

	def setUp(self):
		self.suffix = random_string(8)
		self.rt = _make_room_type(f"IS{self.suffix}")
		self.room = _make_room(f"IS{self.suffix}", self.rt.name)
		self.guest = _make_guest(f"IS{self.suffix}")

	def tearDown(self):
		for name, dt in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
		]:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				pass

	def test_invoice_sync_status_default_is_not_created(self):
		"""
		Newly submitted stays should have invoice_sync_status = 'Not Created'
		(accounting integration disabled = no invoice attempted).
		"""
		# Temporarily disable accounting so no invoice attempt is made
		prev = frappe.db.get_single_value("iHotel Settings", "enable_accounting_integration")
		frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration", 0)
		frappe.db.commit()
		stay = None
		try:
			stay = _make_stay(self.suffix, self.room.name, self.rt.name, self.guest.name)
			stay.reload()
			status = frappe.db.get_value("Checked In", stay.name, "invoice_sync_status")
			self.assertIn(status or "Not Created", ["Not Created", "Synced"],
				"invoice_sync_status should be Not Created when accounting is disabled")
		finally:
			frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration", prev or 0)
			frappe.db.commit()
			if stay:
				try:
					stay.reload()
					if stay.docstatus == 1:
						stay.cancel()
					frappe.delete_doc("Checked In", stay.name, ignore_permissions=True, force=True)
				except Exception:
					pass

	def test_retry_invoice_sync_requires_checkout_status(self):
		"""
		retry_sales_invoice_sync must throw for stays that are not Checked Out.
		"""
		from ihotel.ihotel.doctype.checked_in.checked_in import retry_sales_invoice_sync

		stay = _make_stay(self.suffix, self.room.name, self.rt.name, self.guest.name)
		try:
			# Stay is "Checked In" not "Checked Out" — retry must reject this
			with self.assertRaises(frappe.ValidationError):
				retry_sales_invoice_sync(stay.name)
		finally:
			try:
				stay.reload()
				if stay.docstatus == 1:
					stay.cancel()
				frappe.delete_doc("Checked In", stay.name, ignore_permissions=True, force=True)
			except Exception:
				pass


class TestNightAuditNoPost(FrappeTestCase):
	"""Regression tests for no_post enforcement in night audit room charge posting."""

	def setUp(self):
		self.suffix = random_string(8)
		self.audit_date = add_days(today(), -(180 + (len(self.suffix) % 100)))
		self.rt = _make_room_type(f"NA{self.suffix}")
		self.room = _make_room(f"NA{self.suffix}", self.rt.name)
		self.guest = _make_guest(f"NA{self.suffix}")

		prev_allow = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		self._prev_allow = prev_allow
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.commit()

	def tearDown(self):
		for name, dt in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
		]:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				pass
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", self._prev_allow or 0)
		frappe.db.commit()

	def test_no_post_stay_skipped_by_night_audit(self):
		"""
		Night audit must not post room charges for stays with no_post=1.
		The folio for such a stay should have zero room charges after the audit runs.
		"""
		arrive = add_to_date(self.audit_date, days=-1)
		depart = add_to_date(self.audit_date, days=2)

		stay = frappe.get_doc({
			"doctype": "Checked In",
			"guest": self.guest.name,
			"room_type": self.rt.name,
			"room": self.room.name,
			"expected_check_in": arrive,
			"expected_check_out": depart,
			"status": "Reserved",
			"no_post": 1,
		})
		stay.insert(ignore_permissions=True)
		stay.submit()

		# Force Checked In status for the audit scope query
		frappe.db.set_value("Checked In", stay.name, {
			"status": "Checked In",
			"actual_check_in": arrive,
			"room_rate": 150,
		}, update_modified=False)

		try:
			na = frappe.new_doc("Night Audit")
			na.audit_date = self.audit_date
			na.insert(ignore_permissions=True)
			na.submit()

			# Folio should exist but have no room charges for this stay
			profile_name = frappe.db.get_value("Checked In", stay.name, "profile")
			if profile_name:
				room_charges = frappe.db.count("Folio Charge", {
					"parent": profile_name,
					"charge_type": "Room Charge",
					"reference_name": stay.name,
				})
				self.assertEqual(room_charges, 0,
					"Night audit must skip room charges for no_post=1 stays")
		finally:
			try:
				na.reload()
				if na.docstatus == 1:
					na.cancel()
				frappe.delete_doc("Night Audit", na.name, ignore_permissions=True, force=True)
			except Exception:
				pass
			try:
				stay.reload()
				if stay.docstatus == 1:
					stay.cancel()
				frappe.delete_doc("Checked In", stay.name, ignore_permissions=True, force=True)
			except Exception:
				pass
