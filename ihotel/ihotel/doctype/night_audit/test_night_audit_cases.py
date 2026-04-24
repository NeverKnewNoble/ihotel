# Copyright (c) 2025, Noble and Contributors
# See license.txt

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, flt, today

from ihotel.ihotel.doctype.night_audit.night_audit import get_stays_in_house_on


# ── Shared helpers for nightly billing model tests ────────────────────────────

def _nb_make_room_type(suffix):
	return frappe.get_doc({
		"doctype": "Room Type",
		"room_type_name": f"RT-NB-{suffix}",
		"rack_rate": 200,
	}).insert(ignore_permissions=True)


def _nb_make_room(suffix, room_type):
	return frappe.get_doc({
		"doctype": "Room",
		"room_number": f"RM-NB-{suffix}",
		"room_type": room_type,
		"status": "Available",
	}).insert(ignore_permissions=True)


def _nb_make_guest(suffix):
	return frappe.get_doc({
		"doctype": "Guest",
		"guest_name": f"NB Guest {suffix}",
	}).insert(ignore_permissions=True)


def _nb_make_stay(suffix, room, room_type, guest, arrive, depart, nightly_rate=200):
	"""Insert and submit a Checked In document for nightly billing tests."""
	stay = frappe.get_doc({
		"doctype": "Checked In",
		"guest": guest,
		"room_type": room_type,
		"room": room,
		"expected_check_in": arrive,
		"expected_check_out": depart,
		"status": "Reserved",
	})
	stay.insert(ignore_permissions=True)
	stay.submit()
	# Force Checked In status and set nightly rate directly (bypassing validate)
	frappe.db.set_value("Checked In", stay.name, {
		"status": "Checked In",
		"actual_check_in": arrive,
		"room_rate": nightly_rate,
	}, update_modified=False)
	stay.reload()
	return stay


def _nb_submit_audit(audit_date):
	"""Create and submit a Night Audit for the given date."""
	na = frappe.new_doc("Night Audit")
	na.audit_date = audit_date
	na.insert(ignore_permissions=True)
	na.submit()
	return na


class TestNightlyBillingModel(FrappeTestCase):
	"""
	Nightly billing model regression tests.

	Validates that:
	- Night Audit posts exactly one Room Charge per stay per audit date.
	- A 3-night stay at 200/night accumulates total charges of 600.
	- Re-running (resubmitting) an audit on the same date never double-posts.
	- Stays with zero room_rate are skipped and logged (not silently posted).
	"""

	def setUp(self):
		self.suffix = frappe.generate_hash(length=8)
		# Spread audit dates far in the past to avoid clashes with other test runs
		base_offset = -(200 + (int(self.suffix, 16) % 400))
		self.night1 = add_days(today(), base_offset)
		self.night2 = add_days(today(), base_offset + 1)
		self.night3 = add_days(today(), base_offset + 2)
		self.arrive = self.night1
		self.depart = add_days(today(), base_offset + 3)

		prev = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		self._prev_allow = prev
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.commit()

		self.rt = _nb_make_room_type(self.suffix)
		self.room = _nb_make_room(self.suffix, self.rt.name)
		self.guest = _nb_make_guest(self.suffix)
		self.stay = _nb_make_stay(
			self.suffix, self.room.name, self.rt.name, self.guest.name,
			self.arrive, self.depart, nightly_rate=200,
		)
		self._audits = []

	def tearDown(self):
		for na in self._audits:
			try:
				na.reload()
				if na.docstatus == 1:
					na.cancel()
				frappe.delete_doc("Night Audit", na.name, ignore_permissions=True, force=True)
			except Exception:
				pass
		try:
			self.stay.reload()
			if self.stay.docstatus == 1:
				self.stay.cancel()
			frappe.delete_doc("Checked In", self.stay.name, ignore_permissions=True, force=True)
		except Exception:
			pass
		for name, dt in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
		]:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				pass
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", self._prev_allow or 0)
		frappe.db.commit()

	def _get_room_charge_rows(self):
		"""Return all Room Charge folio rows for this stay's profile."""
		profile_name = frappe.db.get_value("Checked In", self.stay.name, "profile")
		if not profile_name:
			return []
		return frappe.db.get_all(
			"Folio Charge",
			filters={
				"parent": profile_name,
				"charge_type": "Room Charge",
				"reference_name": self.stay.name,
			},
			fields=["charge_date", "rate", "amount"],
		)

	def test_one_room_charge_per_audit_date(self):
		"""Night audit posts exactly one Room Charge row for the stay on the audit date."""
		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 1,
			"Exactly one Room Charge row must exist after the first night audit")
		self.assertEqual(flt(charges[0].rate), 200.0,
			"Posted room charge rate must equal the nightly room_rate (200)")

	def test_three_night_stay_totals_correctly(self):
		"""
		Running night audit for 3 consecutive nights on a 200/night stay
		must produce total room charges of 600 (3 x 200).
		"""
		for date in (self.night1, self.night2, self.night3):
			na = _nb_submit_audit(date)
			self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 3,
			"3 nights must produce exactly 3 Room Charge rows")
		total = sum(flt(c.amount) for c in charges)
		self.assertEqual(total, 600.0,
			"Total room charges for a 3-night stay at 200/night must be 600")

	def test_duplicate_audit_date_does_not_double_post(self):
		"""
		Calling add_payment_entry for a stay on the same audit date twice
		must not create a second folio charge (idempotency / duplicate guard).
		"""
		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		# Manually invoke add_payment_entry again to simulate a re-run attempt
		na.reload()
		profile_name = frappe.db.get_value("Checked In", self.stay.name, "profile")
		profile_doc = frappe.get_doc("iHotel Profile", profile_name)
		stay_doc = frappe.get_doc("Checked In", self.stay.name)
		na.add_payment_entry(profile_doc, stay_doc)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 1,
			"Duplicate add_payment_entry call must not create a second Room Charge row")

	def test_zero_room_rate_stay_is_skipped(self):
		"""
		A stay with room_rate = 0 must not generate a folio Room Charge row.
		Night audit should skip it and log an error instead.
		"""
		frappe.db.set_value("Checked In", self.stay.name, "room_rate", 0, update_modified=False)

		na = _nb_submit_audit(self.night1)
		self._audits.append(na)

		charges = self._get_room_charge_rows()
		self.assertEqual(len(charges), 0,
			"Night audit must skip Room Charge posting for stays with room_rate = 0")


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


# ── ERPXpand Journal Entry tax posting tests ─────────────────────────────────

def _accounting_ready():
	"""True if this site has enough config for JE integration tests to run.

	Requires the Room Charge income account + AR account + tax accounts to all
	be under the configured Company (the SI / JE path validates that).
	"""
	if "erpnext" not in frappe.get_installed_apps():
		return False
	settings = frappe.get_single("iHotel Settings")
	company = settings.get("company")
	ar = settings.get("accounts_receivable_account")
	if not company or not ar:
		return False

	# AR account must belong to the configured company.
	ar_company = frappe.db.get_value("Account", ar, "company")
	if ar_company != company:
		return False

	# Room Charge income account row must exist AND belong to the company.
	for r in (settings.get("income_accounts") or []):
		if r.charge_type == "Room Charge" and r.account:
			acct_company = frappe.db.get_value("Account", r.account, "company")
			if acct_company == company:
				return True
	return False


def _find_test_tax_accounts(company, n=2):
	"""Return up to n Tax-type leaf accounts scoped to company.

	Strictly scoped to the passed company so the JE validation doesn't
	reject the posting with a cross-company account error. Falls back to
	Liability-type leaves when no Tax-typed accounts exist under this
	company, so tests can still run on a minimally-seeded chart.
	"""
	taxes = frappe.db.get_all(
		"Account",
		filters={"company": company, "account_type": "Tax", "is_group": 0},
		pluck="name",
		limit=n,
	)
	if len(taxes) >= n:
		return list(taxes)
	more = frappe.db.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0},
		pluck="name",
		limit=(n - len(taxes)),
	)
	return list(taxes) + list(more)


@unittest.skipUnless(_accounting_ready(), "iHotel Settings accounting not configured on this site")
class TestNightAuditJournalEntryTax(FrappeTestCase):
	"""Validates the Night Audit JE posts tax per tax_account and cancels cleanly."""

	def setUp(self):
		import unittest as _unittest  # keep symbol in scope for class-level decorator
		self.suffix = frappe.generate_hash(length=8)
		base_offset = -(200 + (int(self.suffix, 16) % 400))
		self.audit_date = add_days(today(), base_offset)

		self.settings = frappe.get_single("iHotel Settings")
		self.company = self.settings.company

		# Snapshot & toggle the JE-mode flags we need.
		self._prev_allow = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
		self._prev_enable = self.settings.get("enable_accounting_integration")
		self._prev_je_mode = self.settings.get("post_room_revenue_via_night_audit_je")
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", 1)
		frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration", 1)
		frappe.db.set_single_value("iHotel Settings", "post_room_revenue_via_night_audit_je", 1)
		frappe.db.commit()

		# Two tax accounts for the schedule (fall back gracefully in minimal envs).
		self.tax_accts = _find_test_tax_accounts(self.company, n=2)
		self._has_two_tax_accts = len(self.tax_accts) >= 2

		# Rate Type with a 2-row tax_schedule.
		schedule = []
		if self._has_two_tax_accts:
			schedule = [
				{"tax_name": "VAT", "charge_type": "On Net Total", "rate": 10.0,
				 "tax_account": self.tax_accts[0]},
				{"tax_name": "Service", "charge_type": "On Net Total", "rate": 5.0,
				 "tax_account": self.tax_accts[1]},
			]
		self.rt_tax = frappe.get_doc({
			"doctype": "Rate Type",
			"rate_type_name": f"RT-JE-{self.suffix}",
		})
		for row in schedule:
			self.rt_tax.append("tax_schedule", row)
		self.rt_tax.insert(ignore_permissions=True)

		# Stay fixtures — attach rate_line BEFORE submit (Checked In blocks
		# rate_lines updates after submit via validate_update_after_submit).
		self.rt = _nb_make_room_type(self.suffix)
		self.room = _nb_make_room(self.suffix, self.rt.name)
		# Guest needs a valid phone so Customer auto-creation during JE post
		# doesn't fall over on sites where Customer.mobile_number is required.
		self.guest = frappe.get_doc({
			"doctype": "Guest",
			"guest_name": f"NB Guest {self.suffix}",
			"phone": "0551234567",
		}).insert(ignore_permissions=True)

		stay = frappe.get_doc({
			"doctype": "Checked In",
			"guest": self.guest.name,
			"room_type": self.rt.name,
			"room": self.room.name,
			"expected_check_in": self.audit_date,
			"expected_check_out": add_days(self.audit_date, 2),
			"status": "Reserved",
		})
		stay.append("rate_lines", {
			"rate_type": self.rt_tax.name,
			"amount": 1000,
		})
		stay.insert(ignore_permissions=True)
		stay.submit()
		frappe.db.set_value("Checked In", stay.name, {
			"status": "Checked In",
			"actual_check_in": self.audit_date,
			"room_rate": 1000,
		}, update_modified=False)
		stay.reload()
		self.stay = stay
		self._audits = []

	def tearDown(self):
		for na in self._audits:
			try:
				na.reload()
				if na.docstatus == 1:
					na.cancel()
				frappe.delete_doc("Night Audit", na.name, ignore_permissions=True, force=True)
			except Exception:
				pass
		try:
			self.stay.reload()
			if self.stay.docstatus == 1:
				self.stay.cancel()
			frappe.delete_doc("Checked In", self.stay.name, ignore_permissions=True, force=True)
		except Exception:
			pass
		for name, dt in [
			(self.guest.name, "Guest"),
			(self.room.name, "Room"),
			(self.rt.name, "Room Type"),
			(self.rt_tax.name, "Rate Type"),
		]:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				pass
		frappe.db.set_single_value("iHotel Settings", "allow_past_dates", self._prev_allow or 0)
		frappe.db.set_single_value("iHotel Settings", "enable_accounting_integration",
		                            self._prev_enable or 0)
		frappe.db.set_single_value("iHotel Settings", "post_room_revenue_via_night_audit_je",
		                            self._prev_je_mode or 0)
		frappe.db.commit()

	def test_je_posts_per_tax_account(self):
		"""JE has: 1 Dr AR gross, 1 Cr revenue net, N Cr lines (one per tax_account)."""
		if not self._has_two_tax_accts:
			self.skipTest("Site has <2 Tax accounts; cannot exercise per-account split.")

		na = _nb_submit_audit(self.audit_date)
		self._audits.append(na)
		na.reload()

		je_name = na.erpnext_journal_entry
		self.assertTrue(je_name, "Night audit must set erpnext_journal_entry after submit.")

		je = frappe.get_doc("Journal Entry", je_name)
		ar_acct = self.settings.accounts_receivable_account

		dr_rows = [a for a in je.accounts if flt(a.debit_in_account_currency) > 0]
		cr_rows = [a for a in je.accounts if flt(a.credit_in_account_currency) > 0]

		# AR debit line: gross = net (1000) + tax (10% + 5% = 150) = 1150
		self.assertEqual(len(dr_rows), 1)
		self.assertEqual(dr_rows[0].account, ar_acct)
		self.assertAlmostEqual(flt(dr_rows[0].debit_in_account_currency), 1150.0, places=2)

		# Credit lines: one revenue (1000) + one per tax account (100 + 50).
		cr_by_acct = {a.account: flt(a.credit_in_account_currency) for a in cr_rows}
		self.assertEqual(len(cr_by_acct), 3,
			"Expected 3 distinct credit accounts: revenue + 2 taxes.")
		self.assertAlmostEqual(cr_by_acct.get(self.tax_accts[0], 0), 100.0, places=2)
		self.assertAlmostEqual(cr_by_acct.get(self.tax_accts[1], 0), 50.0, places=2)

		# Balance check.
		total_debit = sum(flt(a.debit_in_account_currency) for a in je.accounts)
		total_credit = sum(flt(a.credit_in_account_currency) for a in je.accounts)
		self.assertAlmostEqual(total_debit, total_credit, places=2)

	def test_cancel_audit_cascades_je_cancel(self):
		"""Cancelling the Night Audit must cancel the linked Journal Entry."""
		na = _nb_submit_audit(self.audit_date)
		self._audits.append(na)
		na.reload()
		je_name = na.erpnext_journal_entry
		if not je_name:
			self.skipTest("JE was not created (e.g. no rate_lines); cancel cascade not applicable.")

		na.cancel()
		docstatus = frappe.db.get_value("Journal Entry", je_name, "docstatus")
		self.assertEqual(docstatus, 2, "Linked Journal Entry must be cancelled.")

	def test_je_bails_when_tax_row_missing_account(self):
		"""A tax_schedule row without an ERPXpand tax_account must prevent JE creation."""
		# Break the second schedule row's tax_account.
		rt_doc = frappe.get_doc("Rate Type", self.rt_tax.name)
		if not rt_doc.tax_schedule or len(rt_doc.tax_schedule) < 2:
			self.skipTest("Fixture lacks a 2-row schedule.")
		rt_doc.tax_schedule[1].tax_account = None
		rt_doc.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Rate Type")

		na = _nb_submit_audit(self.audit_date)
		self._audits.append(na)
		na.reload()
		self.assertFalse(
			na.erpnext_journal_entry,
			"JE must not be created when a tax_schedule row is missing tax_account.",
		)

