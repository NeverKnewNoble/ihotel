# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, flt


class RateType(Document):
	def validate(self):
		self.calculate_effective_tax_rate()

	def calculate_effective_tax_rate(self):
		"""
		Simulate ERPXpand-style cascading tax calculation on a base of 100
		to derive the effective combined tax rate as a percentage.

		Charge types:
		  On Net Total          — rate% of 100 (base)
		  On Previous Row Amount — rate% of the tax amount from row N
		  On Previous Row Total  — rate% of the running total after row N
		  Actual                 — flat amount added directly
		"""
		today = getdate(nowdate())
		base = 100.0
		running_total = base
		row_amounts = []   # tax amount for each row (0-indexed)
		row_totals = []    # running total after each row (0-indexed)

		for row in (self.tax_schedule or []):
			# Date range filter — blank = no restriction
			if row.from_date and getdate(row.from_date) > today:
				row_amounts.append(0.0)
				row_totals.append(running_total)
				continue
			if row.to_date and getdate(row.to_date) < today:
				row_amounts.append(0.0)
				row_totals.append(running_total)
				continue

			rate = flt(row.rate)
			charge_type = row.charge_type or "On Net Total"
			tax_amount = 0.0

			if charge_type == "On Net Total":
				tax_amount = (rate / 100.0) * base

			elif charge_type == "On Previous Row Amount":
				ref_idx = self._resolve_row_id(row.row_id, len(row_amounts))
				if ref_idx is not None and ref_idx < len(row_amounts):
					tax_amount = (rate / 100.0) * row_amounts[ref_idx]

			elif charge_type == "On Previous Row Total":
				ref_idx = self._resolve_row_id(row.row_id, len(row_amounts))
				if ref_idx is not None and ref_idx < len(row_totals):
					tax_amount = (rate / 100.0) * row_totals[ref_idx]

			elif charge_type == "Actual":
				tax_amount = rate  # flat amount; already currency not %

			running_total += tax_amount
			row_amounts.append(tax_amount)
			row_totals.append(running_total)

		# Effective rate = total tax added as % of base
		self.effective_tax_rate = round(running_total - base, 4)

	def _resolve_row_id(self, row_id, current_count):
		"""
		Convert a 1-based row_id string to a 0-based index.
		Falls back to the last row if blank or invalid.
		"""
		try:
			idx = int(row_id) - 1
			if 0 <= idx < current_count:
				return idx
		except (TypeError, ValueError):
			pass
		# Default: reference the immediately preceding row
		if current_count > 0:
			return current_count - 1
		return None


@frappe.whitelist()
def get_erp_tax_accounts():
	"""Return all ERPXpand accounts of type Tax for populating the tax schedule table."""
	accounts = frappe.get_all(
		"Account",
		filters={"account_type": "Tax", "is_group": 0, "disabled": 0},
		fields=["name", "account_name", "tax_rate"],
		order_by="account_name asc",
	)
	return accounts
