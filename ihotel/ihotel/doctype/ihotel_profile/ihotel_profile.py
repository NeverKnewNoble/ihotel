# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate

from ihotel.ihotel.doctype.charge_type.charge_type import ensure_default_charge_types
from ihotel.ihotel.doctype.night_audit.night_audit import is_audit_date_locked


def _ensure_date_unlocked(d, what):
	"""Throw if a submitted Night Audit exists for the given date."""
	if is_audit_date_locked(d):
		frappe.throw(
			_("Cannot post {0} on {1}: a Night Audit has already been submitted for that day.")
				.format(what, getdate(d))
		)


class iHotelProfile(Document):
	def validate(self):

		self.guard_audited_dates()
		self.recalculate_amounts()
		self.update_status()

	def guard_audited_dates(self):
		"""Block any add/edit/delete of charges or payments on dates already audited.

		Compares against the saved DB state to catch all three cases (insert, update, delete).
		"""
		if self.is_new():
			# A new profile has no audited rows yet
			for c in self.get("charges", []):
				_ensure_date_unlocked(c.charge_date, _("a charge"))
			for p in self.get("payments", []):
				_ensure_date_unlocked(p.date, _("a payment"))
			return

		prev = frappe.get_doc("iHotel Profile", self.name)
		prev_charges = {c.name: c for c in prev.get("charges", [])}
		prev_payments = {p.name: p for p in prev.get("payments", [])}

		# Inserts and edits
		for c in self.get("charges", []):
			old = prev_charges.get(c.name)
			if old is None:
				_ensure_date_unlocked(c.charge_date, _("a charge"))
			elif (str(getdate(old.charge_date)) != str(getdate(c.charge_date))
			      or flt(old.rate) != flt(c.rate)
			      or flt(old.quantity or 1) != flt(c.quantity or 1)
			      or flt(old.amount) != flt(c.amount)):
				# Either the row's old date or its new date being locked is enough to block
				_ensure_date_unlocked(old.charge_date, _("an edit to a charge"))
				_ensure_date_unlocked(c.charge_date, _("an edit to a charge"))

		for p in self.get("payments", []):
			old = prev_payments.get(p.name)
			if old is None:
				_ensure_date_unlocked(p.date, _("a payment"))
			elif (str(getdate(old.date)) != str(getdate(p.date))
			      or flt(old.rate) != flt(p.rate)
			      or (old.payment_method or "") != (p.payment_method or "")):
				_ensure_date_unlocked(old.date, _("an edit to a payment"))
				_ensure_date_unlocked(p.date, _("an edit to a payment"))

		# Deletes
		current_charge_names = {c.name for c in self.get("charges", []) if c.name}
		for old_name, old in prev_charges.items():
			if old_name not in current_charge_names:
				_ensure_date_unlocked(old.charge_date, _("the deletion of a charge"))

		current_payment_names = {p.name for p in self.get("payments", []) if p.name}
		for old_name, old in prev_payments.items():
			if old_name not in current_payment_names:
				_ensure_date_unlocked(old.date, _("the deletion of a payment"))

	def recalculate_amounts(self):
		"""Sum charges and payments separately; derive outstanding balance.

		Payments may be received in any currency; they convert to company
		currency via each row's exchange_rate (default 1 when not set).
		"""
		self.total_amount = round(
			sum(flt(r.amount) for r in self.get("charges", [])), 2
		)
		self.total_payments = round(
			sum(flt(r.rate) * (flt(r.exchange_rate) or 1) for r in self.get("payments", [])),
			2,
		)
		self.outstanding_balance = round(
			self.total_amount - self.total_payments, 2
		)

	def update_status(self):
		"""Auto-manage status based on outstanding balance.

		Open   → Settled  : balance is zero or negative and there are charges.
		Settled → Open    : new charges have made the balance positive again
		                    (e.g. an F&B charge was added after a full deposit).
		Transferred / Closed are never overridden here.
		"""
		if self.status == "Open" and self.outstanding_balance <= 0 and self.total_amount > 0:
			self.status = "Settled"
		elif self.status == "Settled" and self.outstanding_balance > 0:
			self.status = "Open"

	def on_update(self):
		"""Cascade folio-payment sync to ERPXpand GL on every save.

		Delegates to the linked Checked In's _sync_folio_payments_from_profile
		helper, which iterates `payments` and posts a Payment Entry for each
		row missing `payment_entry`. Partial payments post immediately — the
		folio doesn't have to be Settled first. Idempotency (via the
		`payment_entry` link) prevents duplicates on subsequent saves.

		Failures are logged, never raised — a downstream GL hiccup must not
		block front desk from editing the folio.
		"""
		if not self.hotel_stay:
			return
		try:
			if frappe.db.get_single_value("iHotel Settings", "enable_accounting_integration") != 1:
				return
			stay = frappe.get_doc("Checked In", self.hotel_stay)
			stay._sync_folio_payments_from_profile(self)
		except Exception as e:
			frappe.log_error(
				f"iHotel: folio on_update payment sync failed for profile "
				f"{self.name}: {e!s}"
			)

	def on_trash(self):
		"""Break the back-reference in Checked In before Frappe's link-check runs."""
		if self.hotel_stay:
			try:
				frappe.db.set_value("Checked In", self.hotel_stay, "profile", None,
				                    update_modified=False)
			except Exception:
				pass

	def post_charge(self, charge_type, description, rate, quantity=1,
	                reference_doctype=None, reference_name=None, charge_date=None):
		"""Append a charge line to this folio and save.

		charge_date defaults to today when not provided. Pass a specific date
		(e.g. the check-in date or an audit date) to back/forward-date a charge.
		"""
		ensure_default_charge_types()
		_ensure_date_unlocked(charge_date or nowdate(), _("a charge"))
		self.append("charges", {
			"charge_date": charge_date or nowdate(),
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

	# Refuse the transfer up front if any line being moved sits on an audited day
	for c in source.get("charges", []):
		_ensure_date_unlocked(c.charge_date, _("a folio transfer (charge dated)"))
	for p in source.get("payments", []):
		_ensure_date_unlocked(p.date, _("a folio transfer (payment dated)"))

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
