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

	def on_trash(self):
		"""Break the back-reference in Checked In before Frappe's link-check runs."""
		if self.hotel_stay:
			try:
				frappe.db.set_value("Checked In", self.hotel_stay, "profile", None,
				                    update_modified=False)
			except Exception:
				pass

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


@frappe.whitelist()
def transfer_folio(source_profile_name, target_profile_name):
	"""
	Transfer all charges and payments from source folio to target folio.
	Source folio is marked Transferred. Target folio absorbs all line items.
	"""
	from frappe import _

	if source_profile_name == target_profile_name:
		frappe.throw(_("Cannot transfer a folio to itself."))

	source = frappe.get_doc("iHotel Profile", source_profile_name)
	target = frappe.get_doc("iHotel Profile", target_profile_name)

	if source.status != "Open":
		frappe.throw(_("Only Open folios can be transferred."))
	if target.status not in ("Open",):
		frappe.throw(_("Target folio must be Open."))

	source_label = _("Room {0}").format(source.room or source_profile_name)

	# Copy charges
	for charge in source.get("charges", []):
		target.append("charges", {
			"charge_date": charge.charge_date,
			"charge_type": charge.charge_type,
			"description": _("{0} [Transferred from {1}]").format(
				charge.description or "", source_label
			),
			"quantity": charge.quantity,
			"rate": charge.rate,
			"amount": charge.amount,
			"reference_doctype": charge.reference_doctype,
			"reference_name": charge.reference_name,
		})

	# Copy payments
	for payment in source.get("payments", []):
		target.append("payments", {
			"date": payment.date,
			"payment_method": payment.payment_method,
			"rate": payment.rate,
			"detail": _("{0} [Transferred from {1}]").format(
				payment.detail or "", source_label
			),
			"payment_status": payment.payment_status,
		})

	target.save(ignore_permissions=True)

	# Mark source as Transferred
	source.status = "Transferred"
	source.notes = (_("Transferred to {0} ({1}) on {2}.").format(
		target_profile_name, target.room or "", nowdate()
	))
	source.save(ignore_permissions=True)

	# Log on source
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "iHotel Profile",
		"reference_name": source_profile_name,
		"content": _("All charges and payments transferred to folio {0} (Room {1}).").format(
			target_profile_name, target.room or ""
		),
	}).insert(ignore_permissions=True)

	# Log on target
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "iHotel Profile",
		"reference_name": target_profile_name,
		"content": _("Charges and payments received from folio {0} ({1}).").format(
			source_profile_name, source_label
		),
	}).insert(ignore_permissions=True)

	return True
