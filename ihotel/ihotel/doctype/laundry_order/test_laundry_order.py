# Copyright (c) 2026, Noble and Contributors
# See license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate


class _FakeSalesInvoice:
	"""Minimal stand-in for frappe.new_doc("Sales Invoice") used in tests.

	Captures item/tax rows and fields set on the invoice, without talking to
	the database. Lets us assert on the shape of what Laundry Order's
	_create_sales_invoice would POST, independent of company/accounts
	configuration on the test site.
	"""

	def __init__(self):
		self.customer = None
		self.posting_date = None
		self.taxes_and_charges = None
		self.items = []
		self.taxes = []
		self.name = "SINV-TEST"
		self._set_taxes_called = False

	def append(self, table, row):
		getattr(self, table).append(row)

	def set_taxes(self):
		self._set_taxes_called = True
		# Simulate ERPNext's template expansion: add one tax row if a template is set.
		if self.taxes_and_charges:
			self.taxes.append({
				"charge_type": "On Net Total",
				"account_head": "VAT - TEST",
				"rate": 15.0,
				"description": "VAT (from template)",
			})

	def insert(self, **_kwargs):
		return self

	def submit(self):
		return self


def _make_laundry_order(total=250):
	"""Return an in-memory Laundry Order with the minimum fields for SI build."""
	order = frappe.get_doc({
		"doctype": "Laundry Order",
		"customer": "",
		"total_amount": total,
		"order_date": nowdate(),
	})
	order.name = f"LO-TEST-{frappe.generate_hash(length=6)}"
	return order


class TestLaundryOrderSalesInvoice(FrappeTestCase):
	"""Unit tests for Laundry Order._create_sales_invoice tax-template hook.

	We mock frappe.new_doc("Sales Invoice") + the db_set used at the end so the
	tests don't depend on the site's Company/Accounts/Customer configuration.
	The behaviour under test is only: is the `taxes_and_charges` template
	applied (and `set_taxes` called) when Laundry Settings specifies one?
	"""

	def setUp(self):
		self.settings = frappe.get_single("Laundry Settings")
		self._prev_income = self.settings.get("default_income_account")
		self._prev_template = self.settings.get("default_taxes_and_charges")

		# Use any existing Account as a placeholder income account so the
		# early-exit guard in _create_sales_invoice doesn't trigger.
		dummy_income = frappe.db.get_value("Account", {"is_group": 0}, "name")
		if not dummy_income:
			self.skipTest("No Account records on this site for laundry SI test.")
		frappe.db.set_single_value("Laundry Settings", "default_income_account", dummy_income)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.set_single_value("Laundry Settings", "default_income_account",
		                           self._prev_income or None)
		frappe.db.set_single_value("Laundry Settings", "default_taxes_and_charges",
		                           self._prev_template or None)
		frappe.db.commit()

	def _run_with_fake_si(self, order, template):
		"""Invoke order._create_sales_invoice with frappe.new_doc patched to
		return our fake SI, and return that fake for assertions."""
		frappe.db.set_single_value("Laundry Settings", "default_taxes_and_charges", template)
		frappe.db.commit()
		fake = _FakeSalesInvoice()
		with patch("frappe.new_doc", return_value=fake), \
		     patch.object(order, "db_set"):
			order._create_sales_invoice()
		return fake

	def test_no_template_creates_tax_free_si(self):
		"""When default_taxes_and_charges is blank, no tax rows are added and
		set_taxes() is not called."""
		order = _make_laundry_order(total=250)
		fake = self._run_with_fake_si(order, template=None)

		self.assertEqual(len(fake.items), 1)
		self.assertAlmostEqual(flt(fake.items[0]["rate"]), 250.0, places=2)
		self.assertEqual(len(fake.taxes), 0, "No taxes when no template set.")
		self.assertFalse(fake._set_taxes_called,
			"set_taxes must NOT be called when no template is set.")
		self.assertIsNone(fake.taxes_and_charges)

	def test_with_template_populates_taxes(self):
		"""When a template is set, taxes_and_charges is assigned and set_taxes
		is invoked so ERPNext populates the taxes table."""
		order = _make_laundry_order(total=250)
		fake = self._run_with_fake_si(order, template="Dummy Template - TEST")

		self.assertEqual(fake.taxes_and_charges, "Dummy Template - TEST",
			"Invoice must reference the configured template.")
		self.assertTrue(fake._set_taxes_called,
			"set_taxes must be called so ERPNext materialises the template taxes.")
		self.assertGreater(len(fake.taxes), 0,
			"At least one tax row must be present after set_taxes.")
