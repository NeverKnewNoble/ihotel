# Copyright (c) 2026, Noble and Contributors
# See license.txt

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from ihotel.ihotel.page.trial_balance.trial_balance import (
	_csv_safe_cell,
	export_trial_balance,
	get_trial_balance_data,
)


def _erpnext_company_ready():
	if "erpnext" not in frappe.get_installed_apps():
		return False
	return bool(frappe.db.get_value("Company", {}, "name"))


class TestTrialBalanceCsvSafeCell(FrappeTestCase):
	"""Pure unit tests for the CSV injection / escape helper. No DB needed."""

	def test_none_returns_empty_quoted_cell(self):
		self.assertEqual(_csv_safe_cell(None), '""')

	def test_plain_string_is_quoted(self):
		self.assertEqual(_csv_safe_cell("VAT"), '"VAT"')

	def test_embedded_double_quote_escaped(self):
		self.assertEqual(_csv_safe_cell('He said "hi"'), '"He said ""hi"""')

	def test_formula_leading_chars_prefixed_with_apostrophe(self):
		for dangerous in ("=", "+", "-", "@", "\t", "\r"):
			cell = _csv_safe_cell(f"{dangerous}SUM(A1:A10)")
			self.assertTrue(cell.startswith('"\''),
				f"Cell starting with {dangerous!r} should be prefixed with apostrophe; got {cell}")


class TestTrialBalanceValidation(FrappeTestCase):
	"""Input validation tests that don't require a populated ERP."""

	def test_missing_company_throws(self):
		"""get_trial_balance_data must refuse to run without a company filter."""
		with self.assertRaises(frappe.ValidationError):
			get_trial_balance_data(json.dumps({"from_date": today(), "to_date": today()}))

	def test_empty_filters_throws(self):
		with self.assertRaises(frappe.ValidationError):
			get_trial_balance_data(None)


@unittest.skipUnless(_erpnext_company_ready(), "ERPNext + Company required for integration tests")
class TestTrialBalanceOverGLEntry(FrappeTestCase):
	"""Integration tests that assert we read from tabGL Entry and not folio charges."""

	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.from_date = today()
		self.to_date = today()

	def test_returns_company_scoped_response(self):
		"""Basic smoke: response shape is right and balances are consistent."""
		data = get_trial_balance_data(json.dumps({
			"company": self.company,
			"from_date": self.from_date,
			"to_date": self.to_date,
		}))
		self.assertEqual(data["company"], self.company)
		self.assertIn("trial_balance", data)
		self.assertIn("total_debit", data)
		self.assertIn("total_credit", data)
		# For a single company the totals must match when no JEs fall in range.
		# When there are postings, they must still match by definition of GL.
		self.assertAlmostEqual(flt(data["total_debit"]),
		                       flt(data["total_credit"]), places=2,
			msg="Trial balance debits and credits must match for any single company.")

	def test_rows_come_from_gl_entry_not_folio(self):
		"""Every account in the response must be a real tabAccount row for the company.

		This is the key regression guard: the old implementation read from
		tabHotel Account + tabFolio Charge, so it would return non-existent-on-GL
		account names. We now must only ever return tabAccount names.
		"""
		data = get_trial_balance_data(json.dumps({
			"company": self.company,
			"from_date": self.from_date,
			"to_date": self.to_date,
		}))
		for row in data["trial_balance"]:
			self.assertTrue(
				frappe.db.exists("Account", {"name": row["account"], "company": self.company}),
				f"Row {row['account']} is not a real tabAccount for company {self.company}.",
			)

	def test_export_csv_injection_safe(self):
		"""Exported CSV quotes every field and neutralises formula prefixes."""
		csv_body = export_trial_balance(json.dumps({
			"company": self.company,
			"from_date": self.from_date,
			"to_date": self.to_date,
		}))
		# Every non-empty row must start and end with a double quote.
		for line in csv_body.splitlines():
			if not line:
				continue
			self.assertTrue(line.startswith('"') and line.endswith('"'),
				f"CSV row not properly quoted: {line!r}")
