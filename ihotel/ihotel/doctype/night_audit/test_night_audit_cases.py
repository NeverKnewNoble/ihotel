# Copyright (c) 2025, Noble and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, flt, today

from ihotel.ihotel.doctype.night_audit.night_audit import get_stays_in_house_on


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

