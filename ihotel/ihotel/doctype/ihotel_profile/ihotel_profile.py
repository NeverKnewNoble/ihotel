# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class iHotelProfile(Document):
	def validate(self):
		self.recalculate_amounts()
		self.update_status()

	def recalculate_amounts(self):
		"""Sum charges and payments separately; derive outstanding balance."""
		self.total_amount = round(
			sum(flt(r.amount) for r in self.get("charges", [])), 2
		)
		self.total_payments = round(
			sum(flt(r.rate) for r in self.get("payments", [])), 2
		)
		self.outstanding_balance = round(
			self.total_amount - self.total_payments, 2
		)

	def update_status(self):
		"""Auto-set status to Settled when fully paid."""
		if self.status == "Open" and self.outstanding_balance <= 0 and self.total_amount > 0:
			self.status = "Settled"

	def post_charge(self, charge_type, description, rate, quantity=1,
	                reference_doctype=None, reference_name=None):
		"""Append a charge line to this folio and save."""
		self.append("charges", {
			"charge_date": nowdate(),
			"charge_type": charge_type,
			"description": description,
			"quantity": quantity,
			"rate": flt(rate),
			"amount": round(flt(rate) * flt(quantity), 2),
			"reference_doctype": reference_doctype or "",
			"reference_name": reference_name or "",
		})
		self.save(ignore_permissions=True)
