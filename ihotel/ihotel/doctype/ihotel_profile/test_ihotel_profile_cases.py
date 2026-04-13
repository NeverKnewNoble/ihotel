# Copyright (c) 2025, Noble and Contributors
# See license.txt

# import frappe
import frappe
from frappe.tests.utils import FrappeTestCase


class TestiHotelProfile(FrappeTestCase):
	def test_financial_totals_split_paid_and_pending(self):
		profile = frappe.new_doc("iHotel Profile")
		profile.append(
			"payments",
			{
				"detail": "Night 1",
				"rate": 150,
				"payment_status": "Pending payment",
			},
		)
		profile.append(
			"payments",
			{"detail": "Night 2", "rate": 200, "payment_status": "Paid"},
		)
		profile.append(
			"payments",
			{
				"detail": "Mini Bar",
				"rate": 50,
				"payment_status": "Pending payment",
			},
		)

		profile.update_financial_summary()

		self.assertEqual(profile.total_amount, 400)
		self.assertEqual(profile.total_payments, 200)
		self.assertEqual(profile.outstanding_balance, 200)
