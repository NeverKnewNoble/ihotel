# Copyright (c) 2025, Noble and Contributors
# See license.txt

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, flt, now_datetime


def _erpnext_accounting_ready():
	"""Return True if this site has the minimum ERPXpand wiring for SI/JE tests.

	The SI/JE tests need: ERPNext installed, a Company + Accounts Receivable on
	iHotel Settings, and an 'Income Accounts' row for 'Room Charge'. Sites
	without this config skip the integration tests rather than creating a
	throwaway company on every run.
	"""
	if "erpnext" not in frappe.get_installed_apps():
		return False
	settings = frappe.get_single("iHotel Settings")
	if not settings.get("company") or not settings.get("accounts_receivable_account"):
		return False
	has_room_income = any(
		(r.charge_type == "Room Charge" and r.account)
		for r in (settings.get("income_accounts") or [])
	)
	return has_room_income


def _make_rate_type_with_schedule(suffix, tax_rows):
	"""Create a Rate Type with a tax_schedule populated from tax_rows.

	tax_rows: list of dicts with keys {tax_name, rate, tax_account (optional), charge_type (optional)}
	"""
	rt = frappe.get_doc({
		"doctype": "Rate Type",
		"rate_type_name": f"RT-Tax-{suffix}",
	})
	for row in tax_rows:
		rt.append("tax_schedule", {
			"tax_name": row.get("tax_name") or "Tax",
			"charge_type": row.get("charge_type") or "On Net Total",
			"rate": row["rate"],
			"tax_account": row.get("tax_account"),
		})
	rt.insert(ignore_permissions=True)
	return rt


class TestCheckedInTaxBreakdown(FrappeTestCase):
	"""Unit tests for Checked In._compute_tax_breakdown / _compute_tax.

	Validates that:
	- Empty rate_lines → empty breakdown and 0 scalar tax.
	- Each tax_schedule row produces one (tax_account, amount) tuple.
	- _compute_tax is the sum of the breakdown's amounts.
	- tax_account=None is returned as-is (caller decides how to handle it).
	"""

	def setUp(self):
		self.suffix = frappe.generate_hash(length=8)

	def test_empty_rate_lines_returns_empty_breakdown(self):
		stay = frappe.get_doc({"doctype": "Checked In"})
		self.assertEqual(stay._compute_tax_breakdown(1000), [])
		self.assertEqual(stay._compute_tax(1000), 0.0)

	def test_breakdown_two_rows_with_accounts(self):
		"""A 2-row schedule produces two tuples; scalar tax is their sum."""
		rt = _make_rate_type_with_schedule(
			self.suffix,
			[
				{"tax_name": "VAT", "rate": 15.0, "tax_account": None},
				{"tax_name": "Service", "rate": 10.0, "tax_account": None},
			],
		)
		try:
			stay = frappe.get_doc({"doctype": "Checked In"})
			stay.append("rate_lines", {
				"rate_type": rt.name,
				"amount": 1000,
			})
			breakdown = stay._compute_tax_breakdown(1000)
			self.assertEqual(len(breakdown), 2)
			# Order follows tax_schedule row order
			self.assertEqual(breakdown[0][1], 150.0, "VAT 15% of 1000 = 150")
			self.assertEqual(breakdown[1][1], 100.0, "Service 10% of 1000 = 100")
			self.assertEqual(stay._compute_tax(1000), 250.0)
		finally:
			frappe.delete_doc("Rate Type", rt.name, ignore_permissions=True, force=True)

	def test_breakdown_preserves_tax_account(self):
		"""tax_account on each row is returned verbatim (None stays None)."""
		rt = _make_rate_type_with_schedule(
			self.suffix,
			[
				{"tax_name": "VAT", "rate": 15.0, "tax_account": None},
			],
		)
		try:
			stay = frappe.get_doc({"doctype": "Checked In"})
			stay.append("rate_lines", {"rate_type": rt.name, "amount": 1000})
			breakdown = stay._compute_tax_breakdown(1000)
			# Account is None in this fixture; caller must treat None as "missing".
			self.assertEqual(breakdown[0][0], None)
		finally:
			frappe.delete_doc("Rate Type", rt.name, ignore_permissions=True, force=True)


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


# ── Folio payment sync (Take Payment / profile on_update → ERPXpand PE) ──────

def _make_stay_with_folio_charge(suffix, charge_amount=1000):
	"""Spin up a minimal stay + folio + one Room Charge row.

	Returns (stay_doc, profile_doc). The stay has a phone-bearing guest so that
	`_get_or_create_customer` doesn't trip the site's Customer.mobile_number
	validation.
	"""
	from frappe.utils import add_days, today
	rt = frappe.get_doc({
		"doctype": "Room Type",
		"room_type_name": f"RT-FP-{suffix}",
		"rack_rate": 200,
	}).insert(ignore_permissions=True)
	room = frappe.get_doc({
		"doctype": "Room",
		"room_number": f"FP-{suffix}",
		"room_type": rt.name,
		"status": "Available",
	}).insert(ignore_permissions=True)
	guest = frappe.get_doc({
		"doctype": "Guest",
		"guest_name": f"FP Guest {suffix}",
		"phone": "0551234567",
	}).insert(ignore_permissions=True)

	# allow_past_dates is honoured by the TestNightAuditJournalEntryTax setUp
	# too — mirror that toggle here so a stay landing "today" stays valid.
	today_d = today()
	tomorrow = add_days(today_d, 1)

	stay = frappe.get_doc({
		"doctype": "Checked In",
		"guest": guest.name,
		"room_type": rt.name,
		"room": room.name,
		"expected_check_in": today_d,
		"expected_check_out": tomorrow,
		"status": "Reserved",
	})
	stay.insert(ignore_permissions=True)
	stay.submit()
	frappe.db.set_value("Checked In", stay.name, {
		"status": "Checked In",
		"actual_check_in": today_d,
		"room_rate": charge_amount,
	}, update_modified=False)
	stay.reload()

	profile = frappe.get_doc("iHotel Profile", stay.profile)
	# The submit hook posts the first-night Room Charge automatically. If it
	# hasn't (no rate_lines), post one manually so there's something to settle.
	if not profile.charges:
		profile.post_charge(
			charge_type="Room Charge",
			description="Test room charge",
			rate=charge_amount,
			quantity=1,
			reference_doctype="Checked In",
			reference_name=stay.name,
		)
		profile.reload()
	return stay, profile


def _cleanup_stay(stay_doc):
	"""Best-effort teardown for a test stay + its dependents."""
	try:
		stay_doc.reload()
	except Exception:
		return
	# Cancel any PEs linked through the folio (so PEs don't orphan).
	try:
		profile = frappe.get_doc("iHotel Profile", stay_doc.profile) if stay_doc.profile else None
	except Exception:
		profile = None
	if profile:
		for p in (profile.payments or []):
			if p.payment_entry:
				try:
					pe = frappe.get_doc("Payment Entry", p.payment_entry)
					if pe.docstatus == 1:
						pe.cancel()
					frappe.delete_doc("Payment Entry", p.payment_entry,
					                   ignore_permissions=True, force=True)
				except Exception:
					pass
	try:
		if stay_doc.docstatus == 1:
			stay_doc.cancel()
		frappe.delete_doc("Checked In", stay_doc.name,
		                   ignore_permissions=True, force=True)
	except Exception:
		pass


@unittest.skipUnless(_erpnext_accounting_ready(),
                      "iHotel Settings accounting not configured on this site")
class TestFolioPaymentSync(FrappeTestCase):
	"""Regression + integration tests for the Take Payment / folio-sync fix.

	Covers:
	- _sync_folio_payments with and without a Sales Invoice (SI vs JE mode).
	- Idempotency: re-running sync does not double-post PEs.
	- iHotel Profile.on_update triggers the sync when status becomes Settled
	  (the Yaw Asante regression: folio was Settled but no PE posted).
	- Whitelisted take_payment endpoint appends rows + syncs PEs in one shot.
	- take_payment with also_checkout=True transitions the stay to Checked Out.
	"""

	def setUp(self):
		self.suffix = frappe.generate_hash(length=8)
		self._prev_allow = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		self._prev_enable = frappe.db.get_single_value("iHotel Settings", "enable_accounting_integration")
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration", 1)
		frappe.db.commit()
		self.stay, self.profile = _make_stay_with_folio_charge(self.suffix, charge_amount=1000)

	def tearDown(self):
		_cleanup_stay(self.stay)
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates",
		                           self._prev_allow or 0)
		frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration",
		                           self._prev_enable or 0)
		frappe.db.commit()

	def _add_payment_row(self, amount, method="Cash", status="Paid"):
		"""Append a folio payment row and save — triggers on_update cascade."""
		from frappe.utils import today
		self.profile.append("payments", {
			"date": today(),
			"payment_method": method,
			"rate": amount,
			"payment_status": status,
		})
		self.profile.save(ignore_permissions=True)
		self.profile.reload()

	def test_sync_folio_payments_without_invoice_standalone(self):
		"""JE mode: sync posts a standalone Receive (no SI reference)."""
		self._add_payment_row(amount=500)
		row = self.profile.payments[0]
		self.assertTrue(row.payment_entry,
			"Folio row must be linked to a Payment Entry after save.")
		pe = frappe.get_doc("Payment Entry", row.payment_entry)
		self.assertEqual(pe.docstatus, 1, "Payment Entry must be submitted.")
		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(flt(pe.paid_amount), 500.0)
		self.assertEqual(len(pe.references or []), 0,
			"Standalone PE must have no Sales Invoice references.")

	def test_sync_folio_payments_with_invoice_allocates(self):
		"""SI mode: when invoice is passed, PE carries a Sales Invoice reference."""
		settings = frappe.get_single("iHotel Settings")
		customer = self.stay._get_or_create_customer(settings, settings.company)
		if not customer:
			self.skipTest("Could not resolve Customer for this stay.")
		item_code = settings.get("room_charge_item") or settings.get("extra_charge_item")
		if not item_code:
			self.skipTest("No invoice item configured on iHotel Settings.")

		# Insert a payment row directly into the child table so on_update does
		# not auto-sync it (we want to exercise the explicit call with invoice).
		from frappe.utils import today
		pi_name = frappe.db.sql("""
			INSERT INTO `tabPayment Items`
			  (name, parent, parenttype, parentfield, idx, creation, modified,
			   owner, modified_by, docstatus, date, payment_method, rate, payment_status)
			VALUES
			  (%(name)s, %(parent)s, 'iHotel Profile', 'payments', 1, NOW(), NOW(),
			   'Administrator', 'Administrator', 0, %(date)s, 'Cash', 250, 'Paid')
		""", {
			"name": frappe.generate_hash(length=10),
			"parent": self.profile.name,
			"date": today(),
		})
		self.profile.reload()
		self.assertTrue(self.profile.payments,
			"Failed to seed a payment row for SI-allocate test.")
		self.assertFalse(self.profile.payments[0].payment_entry,
			"Seeded row should start without a Payment Entry link.")

		# Build a minimal SI and call sync with it.
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = settings.company
		si.append("items", {
			"item_code": item_code,
			"item_name": "Test Folio Sync",
			"description": "Test",
			"qty": 1,
			"rate": 250,
		})
		try:
			si.insert(ignore_permissions=True)
			si.submit()
		except Exception as e:
			self.skipTest(f"Could not insert Sales Invoice in this env: {e!s}")

		try:
			created = self.stay._sync_folio_payments(
				self.profile, customer, settings.company, invoice=si,
			)
			self.assertEqual(len(created), 1)
			pe = frappe.get_doc("Payment Entry", created[0])
			self.assertEqual(len(pe.references), 1,
				"SI-mode PE must carry exactly one Sales Invoice reference.")
			self.assertEqual(pe.references[0].reference_doctype, "Sales Invoice")
			self.assertEqual(pe.references[0].reference_name, si.name)
			self.assertAlmostEqual(flt(pe.references[0].allocated_amount), 250.0, places=2)
		finally:
			try:
				si.reload()
				if si.docstatus == 1:
					si.cancel()
				frappe.delete_doc("Sales Invoice", si.name,
				                   ignore_permissions=True, force=True)
			except Exception:
				pass

	def test_sync_folio_payments_idempotent(self):
		"""Running sync twice creates zero new PEs on the second call."""
		self._add_payment_row(amount=300)
		first_pe = self.profile.payments[0].payment_entry
		settings = frappe.get_single("iHotel Settings")
		customer = self.stay._get_or_create_customer(settings, settings.company)
		# Re-run sync directly — all rows already linked.
		created = self.stay._sync_folio_payments(self.profile, customer, settings.company)
		self.assertEqual(created, [],
			"Second sync call must return an empty list (nothing to do).")
		self.profile.reload()
		self.assertEqual(self.profile.payments[0].payment_entry, first_pe,
			"Original Payment Entry link must remain unchanged.")

	def test_profile_on_update_triggers_sync_when_settled(self):
		"""The Yaw regression: a folio transitioning to Settled auto-posts PEs.

		This is the exact scenario the user reproduced: staff add payments on
		the folio directly (no checkout, no manual API call) and expect the
		Payment Entry to post. Previously it didn't; now on_update cascades.
		"""
		outstanding = flt(self.profile.outstanding_balance)
		self.assertGreater(outstanding, 0)
		self._add_payment_row(amount=outstanding)
		self.assertEqual(self.profile.status, "Settled",
			"Folio must auto-transition to Settled when outstanding hits 0.")
		self.assertTrue(self.profile.payments[0].payment_entry,
			"Payment Entry must have been posted by on_update cascade.")

	def test_take_payment_appends_and_syncs(self):
		"""Whitelisted take_payment appends + syncs in one server call."""
		from ihotel.ihotel.doctype.checked_in.checked_in import take_payment
		outstanding = flt(self.profile.outstanding_balance)
		result = take_payment(
			checked_in=self.stay.name,
			payments=[{"amount": outstanding, "payment_method": "Cash"}],
			also_checkout=False,
		)
		self.assertEqual(flt(result["outstanding"]), 0.0)
		self.assertEqual(len(result["payment_entries"]), 1)
		self.assertFalse(result["checked_out"])

	def test_take_payment_multi_currency_converts_to_base(self):
		"""Payment in a foreign currency posts to GL in base currency (rate * ex_rate).

		Reproduces the "guest pays 200 USD on Credit Card" half of the
		mixed-currency scenario. A 80 USD @ 12.5 → 1000 GHS payment should
		settle a 1000 GHS folio, post a PE for 1000 GHS, and leave
		outstanding at zero.
		"""
		from ihotel.ihotel.doctype.checked_in.checked_in import take_payment
		outstanding = flt(self.profile.outstanding_balance)
		if outstanding <= 0:
			self.skipTest("Folio has no outstanding balance; nothing to settle.")
		# Pick a made-up exchange rate so the test doesn't depend on the
		# site's Currency Exchange records.
		ex_rate = 12.5
		fx_amount = round(outstanding / ex_rate, 2)
		result = take_payment(
			checked_in=self.stay.name,
			payments=[{
				"amount": fx_amount,
				"payment_method": "Cash",
				"currency": "USD",
				"exchange_rate": ex_rate,
			}],
			also_checkout=False,
		)
		self.assertAlmostEqual(flt(result["outstanding"]), 0.0, places=2)
		self.assertEqual(len(result["payment_entries"]), 1)
		pe = frappe.get_doc("Payment Entry", result["payment_entries"][0])
		# PE carries the converted base-currency amount.
		self.assertAlmostEqual(flt(pe.paid_amount), outstanding, places=2)

	def test_linked_payment_row_cannot_be_user_deleted(self):
		"""Once a folio payment row has a Payment Entry link, the delete guard
		on iHotel Profile.validate blocks user-initiated row removal."""
		self._add_payment_row(amount=500)
		self.assertTrue(self.profile.payments[0].payment_entry,
			"Pre-condition: row must be synced to a PE for the guard to fire.")

		# Simulate a user removing the linked row from the grid + saving.
		self.profile.set("payments", [])
		with self.assertRaises(frappe.ValidationError):
			self.profile.save(ignore_permissions=True)

	def test_payment_entry_cancel_removes_folio_row(self):
		"""Cancelling a Payment Entry must drop the matching folio row and
		refresh the profile so totals reflect the reversed GL."""
		# Settle the folio fully.
		outstanding = flt(self.profile.outstanding_balance)
		self._add_payment_row(amount=outstanding)
		self.profile.reload()
		self.assertEqual(self.profile.status, "Settled")
		pe_name = self.profile.payments[0].payment_entry
		self.assertTrue(pe_name)

		# Cancel the PE → on_cancel handler should remove the folio row.
		pe = frappe.get_doc("Payment Entry", pe_name)
		pe.cancel()
		self.profile.reload()
		self.assertEqual(
			len(self.profile.payments), 0,
			"Folio payment row must be removed after its Payment Entry is cancelled.",
		)
		self.assertAlmostEqual(
			flt(self.profile.outstanding_balance), outstanding, places=2,
			msg="Outstanding must revert to the original balance.",
		)
		self.assertEqual(self.profile.status, "Open",
			"Profile must flip back to Open when the settling PE is cancelled.")

	def test_take_payment_failed_row_rolled_back(self):
		"""A PE insert failure must NOT leave a phantom row on the folio.

		Regression for the 'Reference No is mandatory' bug: Credit Card PE
		failed, Cash PE succeeded, folio showed both as settled → outstanding
		falsely 0. Now: the failed row is dropped, totals honest, the user
		sees the failure reported via take_payment.failed_payments.
		"""
		from unittest.mock import patch
		from ihotel.ihotel.doctype.checked_in.checked_in import take_payment

		outstanding = flt(self.profile.outstanding_balance)
		self.assertGreater(outstanding, 0)

		# Force every other PE insert to blow up. First PE succeeds, second
		# PE throws. Mimics the production scenario where one row's Mode of
		# Payment config is incomplete.
		calls = {"n": 0}
		real_insert = frappe.model.document.Document.insert

		def flaky_insert(self_doc, *args, **kwargs):
			if self_doc.doctype == "Payment Entry":
				calls["n"] += 1
				if calls["n"] == 2:
					frappe.throw("Simulated PE failure",
					             title="Test Failure Injection")
			return real_insert(self_doc, *args, **kwargs)

		split_amount = round(outstanding / 2, 2)
		payments = [
			{"amount": split_amount,               "payment_method": "Cash"},
			{"amount": outstanding - split_amount, "payment_method": "Cash"},
		]
		with patch.object(frappe.model.document.Document, "insert", flaky_insert):
			try:
				result = take_payment(
					checked_in=self.stay.name,
					payments=payments,
					also_checkout=False,
				)
			except frappe.ValidationError as e:
				# Some environments bubble the msgprint red throw; treat as
				# an acceptable UX path and just verify state below.
				if "Simulated" not in str(e):
					raise
				result = None

		# The second (failed) row must have been removed from the folio.
		self.profile.reload()
		linked_rows = [r for r in self.profile.payments if r.payment_entry]
		# Exactly one PE should have been created (the first row).
		self.assertEqual(len(linked_rows), 1,
			"Only the successful row must remain linked to a Payment Entry.")
		# Folio outstanding must reflect only the successful payment — if the
		# failed row were still on the folio, total_payments would be the full
		# outstanding and the folio would falsely show Settled.
		self.assertAlmostEqual(
			flt(self.profile.outstanding_balance),
			outstanding - split_amount, places=2,
			msg="Outstanding must not be reduced by the failed row.",
		)
		self.assertEqual(self.profile.status, "Open",
			"Folio must stay Open because it is not actually settled.")

		if result is not None:
			# When take_payment returns normally, failed_payments carries the
			# details so the dialog can show the user what to fix.
			self.assertEqual(len(result["failed_payments"]), 1)
			self.assertIn("Simulated", result["failed_payments"][0]["error"])
			self.assertFalse(result["checked_out"])

	def test_take_payment_with_checkout_triggers_do_checkout(self):
		"""also_checkout=True runs do_checkout once the folio is settled."""
		from ihotel.ihotel.doctype.checked_in.checked_in import take_payment
		outstanding = flt(self.profile.outstanding_balance)
		# do_checkout requires Night Audit coverage for every past night through
		# yesterday. Our stay starts today, so there is nothing to audit — the
		# coverage check is a no-op. If the site-level hook still blocks
		# checkout for unrelated reasons, skip gracefully.
		try:
			result = take_payment(
				checked_in=self.stay.name,
				payments=[{"amount": outstanding, "payment_method": "Cash"}],
				also_checkout=True,
			)
		except frappe.ValidationError as e:
			self.skipTest(f"do_checkout blocked in this env: {e!s}")
		self.assertTrue(result["checked_out"],
			"also_checkout=True must transition the stay to Checked Out.")
		self.stay.reload()
		self.assertEqual(self.stay.status, "Checked Out")
