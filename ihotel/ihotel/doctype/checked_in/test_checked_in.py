# Copyright (c) 2025, Noble and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime


class TestCheckedIn(FrappeTestCase):
	def test_room_status_tracks_stay_lifecycle(self):
		"""Room becomes occupied after check-in and reverts to available on checkout."""
		suffix = frappe.generate_hash(length=8)

		room_type = frappe.get_doc({
			"doctype": "Room Type",
			"room_type_name": f"RT-{suffix}",
			"rack_rate": 150
		}).insert(ignore_permissions=True)

		room = frappe.get_doc({
			"doctype": "Room",
			"room_number": f"Room-{suffix}",
			"room_type": room_type.name,
			"status": "Available"
		}).insert(ignore_permissions=True)

		guest = frappe.get_doc({
			"doctype": "Guest",
			"guest_name": f"Guest {suffix}"
		}).insert(ignore_permissions=True)

		stay = frappe.get_doc({
			"doctype": "Checked In",
			"guest": guest.name,
			"room_type": room_type.name,
			"room": room.name,
			"expected_check_in": now_datetime(),
			"expected_check_out": add_to_date(now_datetime(), days=1),
			"room_rate": 150,
			"status": "Reserved"
		}).insert(ignore_permissions=True)

		stay.submit()

		# Simulate check-in by updating the status to Checked In
		stay.status = "Checked In"
		stay.actual_check_in = now_datetime()
		stay.save(ignore_permissions=True)

		room.reload()
		self.assertEqual(room.status, "Occupied")

		# Now simulate checkout and ensure the room frees up
		stay.status = "Checked Out"
		stay.actual_check_out = add_to_date(stay.actual_check_in, days=1)
		stay.save(ignore_permissions=True)

		room.reload()
		self.assertEqual(room.status, "Available")
