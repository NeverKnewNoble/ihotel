# Copyright (c) 2025, Noble and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, flt, today

from ihotel.ihotel.doctype.night_audit.night_audit import get_stays_in_house_on


# ── Shared helpers for nightly billing model tests ────────────────────────────

def _nb_make_room_type(suffix):
	return frappe.get_doc({
		"doctype": "Room Type",
		"room_type_name": f"RT-NB-{suffix}",
		"rack_rate": 200,
	}).insert(ignore_permissions=True)


def _nb_make_room(suffix, room_type):
	return frappe.get_doc({
		"doctype": "Room",
		"room_number": f"RM-NB-{suffix}",
		"room_type": room_type,
		"status": "Available",
	}).insert(ignore_permissions=True)


def _nb_make_guest(suffix):
	return frappe.get_doc({
		"doctype": "Guest",
		"guest_name": f"NB Guest {suffix}",
	}).insert(ignore_permissions=True)


def _nb_make_stay(suffix, room, room_type, guest, arrive, depart, nightly_rate=200):
	"""Insert and submit a Checked In document for nightly billing tests."""
	stay = frappe.get_doc({
		"doctype": "Checked In",
		"guest": guest,
		"room_type": room_type,
		"room": room,
		"expected_check_in": arrive,
		"expected_check_out": depart,
		"status": "Reserved",
	})
	stay.insert(ignore_permissions=True)
	stay.submit()
	# Force Checked In status and set nightly rate directly (bypassing validate)
	frappe.db.set_value("Checked In", stay.name, {
		"status": "Checked In",
		"actual_check_in": arrive,
		"room_rate": nightly_rate,
	}, update_modified=False)
	stay.reload()
	return stay


def _nb_submit_audit(audit_date):
	"""Create and submit a Night Audit for the given date."""
	na = frappe.new_doc("Night Audit")
	na.audit_date = audit_date
	na.insert(ignore_permissions=True)
	na.submit()
	return na


class TestNightlyBillingModel(FrappeTestCase):
	"""
	Nightly billing model regression tests.

	Validates that:
	- Night Audit posts exactly one Room Charge per stay per audit date.
	- A 3-night stay at 200/night accumulates total charges of 600.
	- Re-running (resubmitting) an audit on the same date never double-posts.
	- Stays with zero room_rate are skipped and logged (not silently posted).
	"""

	def setUp(self):
		self.suffix = frappe.generate_hash(length=8)
		# Spread audit dates far in the past to avoid clashes with other test runs
		base_offset = -(200 + (int(self.suffix, 16) % 400))
		self.night1 = add_days(today(), base_offset)
		self.night2 = add_days(today(), base_offset + 1)
		self.night3 = add_days(today(), base_offset + 2)
		self.arrive = self.night1
		self.depart = add_days(today(), base_offset + 3)

		prev = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		self._prev_allow = prev
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.commit()

		self.rt = _nb_make_room_type(self.suffix)
		self.room = _nb_make_room(self.suffix, self.rt.name)
		self.guest = _nb_make_guest(self.suffix)
		self.stay = _nb_make_stay(
			self.suffix, self.room.name, self.rt.name, self.guest.name,
			self.arrive, self.depart, nightly_rate=200,
		)
		self._audits = []

	def tearDown(self):
		for na in self._audits:
			try:
				na.reload()
				if na.docstatus == 1:
					na.cancel()
				frappe.delete_doc("Night Audit", na.name, ignore_permissions=True, force=True)
			except Exception:
				pass
		try:
			self.stay.reload()
			if self.stay.docstatus == 1:
				self.stay.cancel()
			frappe.delete_doc("Checked In", self.stay.name, ignore_permissions=True, force=True)
		except Exception:
			pass
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

	def _get_room_charge_rows(self):
		"""Return all Room Charge folio rows for this stay's profile."""
		profile_name = frappe.db.get_value("Checked In", self.stay.name, "profile")
		if not profile_name:
			return []
		return frappe.db.get_all(
			"Folio Charge",
			filters={
				"parent": profile_name,
				"charge_type": "Room Charge",
				"reference_name": self.stay.name,
			},
			fields=["charge_date", "rate", "amount"],
		)

	def test_one_room_charge_per_audit_date(self):
		"""Night audit posts exactly one Room Charge row for the stay on the audit date."""
		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 1,
			"Exactly one Room Charge row must exist after the first night audit")
		self.assertEqual(flt(charges[0].rate), 200.0,
			"Posted room charge rate must equal the nightly room_rate (200)")

	def test_three_night_stay_totals_correctly(self):
		"""
		Running night audit for 3 consecutive nights on a 200/night stay
		must produce total room charges of 600 (3 x 200).
		"""
		for date in (self.night1, self.night2, self.night3):
			na = _nb_submit_audit(date)
			self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 3,
			"3 nights must produce exactly 3 Room Charge rows")
		total = sum(flt(c.amount) for c in charges)
		self.assertEqual(total, 600.0,
			"Total room charges for a 3-night stay at 200/night must be 600")

	def test_duplicate_audit_date_does_not_double_post(self):
		"""
		Calling add_payment_entry for a stay on the same audit date twice
		must not create a second folio charge (idempotency / duplicate guard).
		"""
		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		# Manually invoke add_payment_entry again to simulate a re-run attempt
		na.reload()
		profile_name = frappe.db.get_value("Checked In", self.stay.name, "profile")
		profile_doc = frappe.get_doc("iHotel Profile", profile_name)
		stay_doc = frappe.get_doc("Checked In", self.stay.name)
		na.add_payment_entry(profile_doc, stay_doc)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 1,
			"Duplicate add_payment_entry call must not create a second Room Charge row")

	def test_zero_room_rate_stay_is_skipped(self):
		"""
		A stay with room_rate = 0 must not generate a folio Room Charge row.
		Night audit should skip it and log an error instead.
		"""
		frappe.db.set_value("Checked In", self.stay.name, "room_rate", 0, update_modified=False)

		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 0,
			"Night audit must skip Room Charge posting for stays with room_rate = 0")


class TestNightAudit(FrappeTestCase):
	def test_get_stays_in_house_on_includes_checked_out_for_past_audit_date(self):
		"""
		Back-dated occupancy must count guests who were in-house on audit_date
		but have since checked out — not only status 'Checked In'.
		Reserved stays overlapping the date must not be included.
		"""
		suffix = frappe.generate_hash(length=8)
		# Spread audit_date so repeated test runs do not accumulate overlapping stays on the same day.
		audit_date = add_days(today(), -(120 + (int(suffix, 16) % 600)))

		# Checked In rejects past expected_check_in unless this setting is on.
		prev_allow = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.commit()

		try:
			self._run_point_in_time_occupancy_scenario(suffix, audit_date)
		finally:
			frappe.db.set_single_value("iHotel Settings", "allow_past_dates", prev_allow or 0)
			frappe.db.commit()

	def _run_point_in_time_occupancy_scenario(self, suffix, audit_date):
		room_type = frappe.get_doc(
			{
				"doctype": "Room Type",
				"room_type_name": f"RT-NA-{suffix}",
				"rack_rate": 100,
			}
		).insert(ignore_permissions=True)

		def make_room(label):
			return frappe.get_doc(
				{
					"doctype": "Room",
					"room_number": f"{label}-{suffix}",
					"room_type": room_type.name,
					"status": "Available",
				}
			).insert(ignore_permissions=True)

		def make_guest(label):
			return frappe.get_doc(
				{"doctype": "Guest", "guest_name": f"Guest {label} {suffix}"}
			).insert(ignore_permissions=True)

		# Window: arrive before audit_date, depart after audit_date
		arrive = add_to_date(audit_date, days=-1)
		depart_after_audit = add_to_date(audit_date, days=3)

		room_active = make_room("A")
		guest_active = make_guest("A")
		stay_active = frappe.get_doc(
			{
				"doctype": "Checked In",
				"guest": guest_active.name,
				"room_type": room_type.name,
				"room": room_active.name,
				"expected_check_in": arrive,
				"expected_check_out": depart_after_audit,
				"room_rate": 100,
				"status": "Reserved",
			}
		).insert(ignore_permissions=True)
		stay_active.submit()
		stay_active.status = "Checked In"
		stay_active.actual_check_in = arrive
		stay_active.save(ignore_permissions=True)

		room_hist = make_room("B")
		guest_hist = make_guest("B")
		stay_hist = frappe.get_doc(
			{
				"doctype": "Checked In",
				"guest": guest_hist.name,
				"room_type": room_type.name,
				"room": room_hist.name,
				"expected_check_in": arrive,
				"expected_check_out": depart_after_audit,
				"room_rate": 120,
				"status": "Reserved",
			}
		).insert(ignore_permissions=True)
		stay_hist.submit()
		stay_hist.status = "Checked In"
		stay_hist.actual_check_in = arrive
		stay_hist.save(ignore_permissions=True)
		# Avoid validate_status_transition (night-audit coverage for every past night).
		frappe.db.set_value(
			"Checked In",
			stay_hist.name,
			{
				"status": "Checked Out",
				"actual_check_out": add_to_date(audit_date, days=1),
			},
			update_modified=False,
		)

		room_res = make_room("C")
		guest_res = make_guest("C")
		stay_reserved = frappe.get_doc(
			{
				"doctype": "Checked In",
				"guest": guest_res.name,
				"room_type": room_type.name,
				"room": room_res.name,
				"expected_check_in": arrive,
				"expected_check_out": depart_after_audit,
				"room_rate": 90,
				"status": "Reserved",
			}
		).insert(ignore_permissions=True)
		stay_reserved.submit()

		# Submit/validation recalculates room_rate from rate lines; set totals for metrics SQL.
		frappe.db.set_value("Checked In", stay_active.name, "room_rate", 100, update_modified=False)
		frappe.db.set_value("Checked In", stay_hist.name, "room_rate", 120, update_modified=False)

		rows = get_stays_in_house_on(audit_date)
		names = {r.name for r in rows}

		self.assertIn(stay_active.name, names)
		self.assertIn(stay_hist.name, names)
		self.assertNotIn(stay_reserved.name, names)

		our_rev = sum(flt(r.room_rate) for r in rows if r.name in (stay_active.name, stay_hist.name))
		self.assertEqual(our_rev, 220.0)

		na = frappe.new_doc("Night Audit")
		na.audit_date = audit_date
		na.calculate_audit_metrics()
		self.assertGreaterEqual(na.occupied_rooms, 2)
		self.assertGreaterEqual(na.total_revenue, 220.0)

