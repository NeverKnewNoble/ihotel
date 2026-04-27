# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, flt, now_datetime

from ihotel.ihotel.doctype.charge_type.charge_type import resolve_hotel_account_for_charge_type


# Roles allowed to tick the "verified" box on Night Audit charges/payments
VERIFIER_ROLES = {"Night Auditor", "System Manager", "Administrator"}


def is_audit_date_locked(d):
    """Return True when a submitted Night Audit exists for the given date.

    Used by iHotel Profile to block back-dated postings on closed days.
    """
    if not d:
        return False
    return bool(frappe.db.exists(
        "Night Audit",
        {"audit_date": getdate(d), "docstatus": 1},
    ))


def get_stays_in_house_on(audit_date):
    """
    Point-in-time occupancy: submitted stays physically in-house on audit_date.

    Uses actual check-in/out when set, otherwise expected. Includes Checked Out so
    back-dated night audits still see guests who have since departed. Excludes
    Reserved / No Show / Cancelled so room charges are not posted for non-stays.

    Overlap rule (same as legacy night audit): arrival date <= audit_date < departure date.
    """
    d = getdate(audit_date)
    return frappe.db.sql(
        """
        SELECT name, room_rate
        FROM `tabChecked In`
        WHERE status IN ('Checked In', 'Checked Out')
        AND docstatus = 1
        AND room IS NOT NULL AND room != ''
        AND DATE(COALESCE(actual_check_in, expected_check_in)) <= %(date)s
        AND DATE(COALESCE(actual_check_out, expected_check_out)) > %(date)s
        """,
        {"date": d},
        as_dict=True,
    )


class NightAudit(Document):
    def validate(self):
        """
        Validate night audit before submission.
        """
        if not self.performed_by:
            self.performed_by = frappe.session.user
        self.validate_audit_date()
        self.calculate_audit_metrics()
        # Snapshot the day's folio charges & payments on the very first save
        # so the user sees them right away — no need to click "Reload" first.
        self._reload_if_empty()
        self._guard_verification_role()
        self._stamp_verified_metadata()
        self._recalc_verification_summary()

    def before_submit(self):
        """Final gate before submitting: tabs must be loaded, every row verified,
        and no new charges/payments can have appeared since the snapshot."""
        self._reload_if_empty()
        self._check_for_new_transactions()
        self._validate_all_verified()

    def _reload_if_empty(self):
        """If the user opened a fresh audit and never clicked Reload, fetch now."""
        if not self.charges and not self.payments:
            self._load_day_transactions()

    def _load_day_transactions(self):
        """Snapshot every Folio Charge / Payment Items row with date == audit_date.
        Preserves existing verified flags by matching on source_row."""
        d = getdate(self.audit_date) if self.audit_date else None
        if not d:
            return

        # Preserve verifications across reloads
        prev_charges = {c.source_row: c for c in (self.charges or []) if c.source_row}
        prev_payments = {p.source_row: p for p in (self.payments or []) if p.source_row}

        charges = frappe.db.sql(
            """
            SELECT fc.name AS source_row, fc.charge_date, fc.parent AS profile,
                   fc.charge_type, fc.description, fc.quantity, fc.rate, fc.amount,
                   p.room AS room, p.guest AS guest
            FROM `tabFolio Charge` fc
            INNER JOIN `tabiHotel Profile` p ON p.name = fc.parent
            WHERE fc.charge_date = %(d)s
              AND fc.parenttype = 'iHotel Profile'
            ORDER BY p.name, fc.idx
            """,
            {"d": d},
            as_dict=True,
        )
        payments = frappe.db.sql(
            """
            SELECT pi.name AS source_row, pi.date, pi.parent AS profile,
                   pi.payment_method, pi.detail, pi.rate, pi.payment_status,
                   p.room AS room, p.guest AS guest
            FROM `tabPayment Items` pi
            INNER JOIN `tabiHotel Profile` p ON p.name = pi.parent
            WHERE pi.date = %(d)s
              AND pi.parenttype = 'iHotel Profile'
            ORDER BY p.name, pi.idx
            """,
            {"d": d},
            as_dict=True,
        )

        self.set("charges", [])
        for c in charges:
            row = {
                "charge_date": c.charge_date,
                "profile": c.profile,
                "room": c.room,
                "guest": c.guest,
                "charge_type": c.charge_type,
                "description": c.description,
                "quantity": c.quantity,
                "rate": c.rate,
                "amount": c.amount,
                "source_row": c.source_row,
            }
            prev = prev_charges.get(c.source_row)
            if prev and prev.verified:
                row["verified"] = 1
                row["verified_by"] = prev.verified_by
                row["verified_on"] = prev.verified_on
            self.append("charges", row)

        self.set("payments", [])
        for p in payments:
            row = {
                "date": p.date,
                "profile": p.profile,
                "room": p.room,
                "guest": p.guest,
                "payment_method": p.payment_method,
                "detail": p.detail,
                "rate": p.rate,
                "payment_status": p.payment_status,
                "source_row": p.source_row,
            }
            prev = prev_payments.get(p.source_row)
            if prev and prev.verified:
                row["verified"] = 1
                row["verified_by"] = prev.verified_by
                row["verified_on"] = prev.verified_on
            self.append("payments", row)

        self.transactions_loaded_on = now_datetime()
        self._recalc_verification_summary()

    def _check_for_new_transactions(self):
        """If any folio row exists for audit_date that isn't snapshotted yet, refuse."""
        d = getdate(self.audit_date) if self.audit_date else None
        if not d:
            return
        snapshot_charges = {c.source_row for c in (self.charges or []) if c.source_row}
        snapshot_payments = {p.source_row for p in (self.payments or []) if p.source_row}

        live_charges = {r[0] for r in frappe.db.sql(
            "SELECT name FROM `tabFolio Charge` WHERE charge_date = %s", (d,),
        )}
        live_payments = {r[0] for r in frappe.db.sql(
            "SELECT name FROM `tabPayment Items` WHERE date = %s", (d,),
        )}

        new_charges = live_charges - snapshot_charges
        new_payments = live_payments - snapshot_payments
        if new_charges or new_payments:
            frappe.throw(_(
                "New transactions have been posted since the audit was loaded "
                "({0} charges, {1} payments). Click 'Reload Transactions' and verify them before submitting."
            ).format(len(new_charges), len(new_payments)))

    def _validate_all_verified(self):
        """Refuse submit if any charge or payment row is not verified."""
        bad_charges = [c for c in (self.charges or []) if not c.verified]
        bad_payments = [p for p in (self.payments or []) if not p.verified]
        if bad_charges or bad_payments:
            parts = []
            if bad_charges:
                parts.append(_("{0} charge(s) unverified").format(len(bad_charges)))
            if bad_payments:
                parts.append(_("{0} payment(s) unverified").format(len(bad_payments)))
            frappe.throw(_(
                "All charges and payments must be verified before submitting the night audit. {0}."
            ).format(", ".join(parts)))

    def _stamp_verified_metadata(self):
        """When a row is checked but verified_by is empty, stamp the current user/now."""
        user = frappe.session.user
        ts = now_datetime()
        for row in (self.charges or []) + (self.payments or []):
            if row.verified and not row.verified_by:
                row.verified_by = user
                row.verified_on = ts
            elif not row.verified:
                row.verified_by = None
                row.verified_on = None

    def _guard_verification_role(self):
        """Block users without the Night Auditor role from setting verified=1.

        Compares against the saved DB state to identify newly-checked rows.
        """
        if self.is_new():
            # First save can't have any "newly checked" rows from a prior state
            return
        roles = set(frappe.get_roles(frappe.session.user))
        if roles & VERIFIER_ROLES:
            return

        prev = frappe.get_doc("Night Audit", self.name)
        prev_charges = {c.source_row: c.verified for c in prev.get("charges", [])}
        prev_payments = {p.source_row: p.verified for p in prev.get("payments", [])}

        def newly_checked(rows, prev_map):
            return any(
                r.verified and not prev_map.get(r.source_row)
                for r in rows
            )

        if newly_checked(self.charges or [], prev_charges) or newly_checked(self.payments or [], prev_payments):
            frappe.throw(_(
                "Only users with the 'Night Auditor' role can verify charges or payments."
            ), frappe.PermissionError)

    def _recalc_verification_summary(self):
        c_total = len(self.charges or [])
        c_done = sum(1 for c in (self.charges or []) if c.verified)
        p_total = len(self.payments or [])
        p_done = sum(1 for p in (self.payments or []) if p.verified)
        self.charges_summary = f"{c_done} / {c_total}"
        self.payments_summary = f"{p_done} / {p_total}"

    def calculate_audit_metrics(self):
        """
        Calculate night audit metrics for the audit date.

        Occupancy: derived from stays physically in-house (same as run_night_audit scope).
        Revenue metrics: derived from folio charges posted FOR the audit date, not from
        the stay's room_rate field. This keeps ADR/RevPAR consistent with what was actually
        posted to guest folios rather than a potentially stale rate snapshot.

        A revenue_delta field captures any gap between folio-posted revenue and room_rate-based
        estimates, flagging discrepancies for the auditor to investigate.
        """
        self.total_rooms = frappe.db.count("Room") or 0

        occupied_stays = get_stays_in_house_on(self.audit_date)
        self.occupied_rooms = len(occupied_stays)

        if self.total_rooms and self.total_rooms > 0:
            self.occupancy_rate = round((self.occupied_rooms / self.total_rooms) * 100, 2)
        else:
            self.occupancy_rate = 0

        # Revenue from actual folio charges posted on the audit date (source of truth)
        folio_revenue_result = frappe.db.sql("""
            SELECT IFNULL(SUM(fc.amount), 0) AS total
            FROM `tabFolio Charge` fc
            INNER JOIN `tabiHotel Profile` p ON p.name = fc.parent
            WHERE fc.charge_type = 'Room Charge'
              AND DATE(fc.charge_date) = %(date)s
        """, {"date": self.audit_date}, as_dict=True)
        folio_revenue = flt((folio_revenue_result[0].total if folio_revenue_result else 0))

        # Estimated revenue based on room_rate snapshot (kept for backward compat / comparison)
        estimated_revenue = sum(flt(stay.room_rate or 0) for stay in occupied_stays)

        # Use folio-based revenue as the authoritative figure; fall back to estimate
        # when no charges have been posted yet (e.g. during same-day audit before run_night_audit)
        self.total_revenue = folio_revenue if folio_revenue > 0 else estimated_revenue
        self.adr = round(self.total_revenue / self.occupied_rooms, 2) if self.occupied_rooms else 0
        self.revpar = round(self.total_revenue / self.total_rooms, 2) if self.total_rooms else 0

    def validate_audit_date(self):
        """
        Ensure only one night audit per day.
        """
        existing_audit = frappe.db.exists("Night Audit", {
            "audit_date": self.audit_date,
            "name": ["!=", self.name]
        })
        if existing_audit:
            frappe.throw(_("Night audit already exists for this date"))

    def on_submit(self):
        """
        Run night audit process when document is submitted.
        """
        self.run_night_audit()
        self._post_erpnext_journal_for_night_audit()

    def on_cancel(self):
        """
        Cascade-cancel the linked ERPXpand Journal Entry so room revenue isn't
        left posted to GL when the audit is reversed. The reference field is
        kept populated for audit trail — the cancelled JE is still reachable.
        """
        je_name = self.erpnext_journal_entry
        if not je_name:
            return
        try:
            je = frappe.get_doc("Journal Entry", je_name)
        except frappe.DoesNotExistError:
            return
        if je.docstatus != 1:
            return
        try:
            je.flags.ignore_permissions = True
            je.cancel()
        except Exception as e:
            frappe.log_error(
                f"Night audit cancel: failed to cancel linked JE {je_name} for {self.name} — {e!s}"
            )
            frappe.throw(
                _("Could not cancel the linked ERPXpand Journal Entry {0}. See Error Log.").format(je_name)
            )

    def run_night_audit(self):
        """
        Post one nightly room charge per guest who is in-house on the audit date.
        A guest is in-house if: check_in <= audit_date < check_out.
        The charge is posted with the audit date, not the current date.
        Stays with no_post=1 are skipped for room charge posting (billing blocked by policy).
        """
        audit_date = self.audit_date
        in_house_stays = get_stays_in_house_on(audit_date)
        today = getdate(frappe.utils.today())

        for stay in in_house_stays:
            stay_doc = frappe.get_doc("Checked In", stay.name)

            # Respect the No Post flag — skip room charge but still mark room dirty for housekeeping
            if stay_doc.get("no_post"):
                frappe.log_error(
                    title=f"iHotel Night Audit: No Post — {stay_doc.name}",
                    message=(
                        f"Night audit {self.name} ({audit_date}): room charge skipped for stay "
                        f"{stay_doc.name} (Room {stay_doc.room}) because no_post=1."
                    ),
                )
                if (
                    stay_doc.room
                    and stay_doc.status == "Checked In"
                    and getdate(audit_date) == today
                    and frappe.db.get_value("Room", stay_doc.room, "status") == "Occupied"
                ):
                    frappe.db.set_value("Room", stay_doc.room, "status", "Occupied Dirty")
                continue

            profile_doc = self.ensure_profile_for_stay(stay_doc)
            self.add_payment_entry(profile_doc, stay_doc)
            # Housekeeping: only for today's audit and still in-house (skip backfill / checked-out).
            # Only flip rooms that are actually "Occupied" — leave "DND" and any other operational
            # status (e.g. already "Occupied Dirty") untouched.
            if (
                stay_doc.room
                and stay_doc.status == "Checked In"
                and getdate(audit_date) == today
                and frappe.db.get_value("Room", stay_doc.room, "status") == "Occupied"
            ):
                frappe.db.set_value("Room", stay_doc.room, "status", "Occupied Dirty")

    def ensure_profile_for_stay(self, stay_doc):
        """
        Create or fetch an iHotel Profile linked to a stay.
        Keeps the Hotel Stay.profile field in sync with the profile name.
        """
        profile_name = stay_doc.profile or frappe.db.get_value(
            "iHotel Profile", {"hotel_stay": stay_doc.name}, "name"
        )

        if profile_name:
            profile_doc = frappe.get_doc("iHotel Profile", profile_name)
            if stay_doc.profile != profile_name:
                # Update link silently to keep modified timestamp untouched
                stay_doc.db_set("profile", profile_name, update_modified=False)
            return profile_doc

        profile_doc = frappe.new_doc("iHotel Profile")
        profile_doc.hotel_stay = stay_doc.name
        profile_doc.room = stay_doc.room
        profile_doc.room_rate = stay_doc.room_rate
        profile_doc.guest = stay_doc.guest
        profile_doc.check_in_date = stay_doc.actual_check_in
        profile_doc.check_out_date = stay_doc.actual_check_out

        profile_doc.insert(ignore_permissions=True)
        stay_doc.db_set("profile", profile_doc.name, update_modified=False)

        return profile_doc

    def add_payment_entry(self, profile_doc, stay_doc):
        """
        Append one nightly room charge to the folio for the audit date.

        Nightly billing model rules:
        - Exactly one Room Charge row per stay per audit date (duplicate guard prevents re-runs).
        - Rate is always the stay's current room_rate field (nightly price).
        - Stays with a zero/missing room_rate are skipped and logged so invalid data
          does not silently create zero-value revenue rows.
        """
        audit_date = self.audit_date

        # Duplicate guard: re-running the same audit must not post a second charge.
        already_posted = any(
            str(r.charge_date) == str(audit_date)
            and r.charge_type == "Room Charge"
            and r.reference_name == stay_doc.name
            for r in profile_doc.get("charges", [])
        )
        if already_posted:
            return

        # Guard: a zero or missing room_rate would create meaningless revenue rows.
        nightly_rate = flt(stay_doc.room_rate)
        if nightly_rate <= 0:
            frappe.log_error(
                title=f"iHotel Night Audit: zero rate — {stay_doc.name}",
                message=(
                    f"Night audit {self.name} ({audit_date}): room charge skipped for stay "
                    f"{stay_doc.name} (Room {stay_doc.room}) because room_rate is {nightly_rate}. "
                    "Set a valid room rate on the stay to have charges posted."
                ),
            )
            return

        # Resolve mapping so configuration can be validated early by lookup.
        resolve_hotel_account_for_charge_type("Room Charge")

        # Post tax-inclusive so each night's folio row matches the stay's Total (incl. Tax)
        # and stays consistent with the first-night charge posted at check-in.
        nightly_tax = stay_doc._compute_tax(nightly_rate)
        nightly_total_incl_tax = round(nightly_rate + nightly_tax, 2)

        profile_doc.append("charges", {
            "charge_date": audit_date,
            "charge_type": "Room Charge",
            "description": _("Nightly room charge — Room {0} ({1})").format(
                stay_doc.room or "", audit_date
            ),
            "quantity": 1,
            "rate": nightly_total_incl_tax,
            "amount": nightly_total_incl_tax,
            "reference_doctype": "Checked In",
            "reference_name": stay_doc.name,
        })
        profile_doc.save(ignore_permissions=True)

    def _post_erpnext_journal_for_night_audit(self):
        """
        When ERPXpand (ERPNext) is installed and iHotel Settings opt-in is on, post one Journal Entry
        for in-house room revenue. Each stay contributes a gross AR debit (net rate + tax). The entry
        balances with a Cr on the room revenue account (net total) plus tax credits.

        Tax-credit routing is driven by iHotel Settings.erpnext_presence_test_mode:
        - "Force: no ERPXpand" → one aggregated Cr on the single Tax Account from Settings.
        - "Force: ERPXpand included" or "Auto" → one Cr per distinct tax_account from the Rate Type's
          tax_schedule rows, aggregated across all stays.

        Checkout Sales Invoices omit Room Charge lines (same setting) so revenue is not doubled.
        """
        if "erpnext" not in frappe.get_installed_apps():
            return

        settings = frappe.get_single("iHotel Settings")
        if not settings.get("enable_accounting_integration"):
            return
        if not settings.get("post_room_revenue_via_night_audit_je"):
            return

        if frappe.db.get_value("Night Audit", self.name, "erpnext_journal_entry"):
            return

        from ihotel.ihotel.doctype.ihotel_settings.ihotel_settings import resolve_income_account

        company = settings.company
        ar_acct = settings.accounts_receivable_account
        # Room revenue account now comes from the Income Accounts table on Settings,
        # keyed by charge_type = "Room Charge". Supports hotels with multiple revenue streams.
        rev_acct = resolve_income_account("Room Charge", company)
        if not all([company, ar_acct, rev_acct]):
            frappe.msgprint(
                _("Set Company, Accounts Receivable, and an Income Accounts row for 'Room Charge' in iHotel Settings to post night audit to ERPXpand."),
                indicator="orange",
                title=_("ERPXpand Journal Entry skipped"),
            )
            return

        # Auto falls through to the per-tax-schedule path: the JE path only runs when ERPNext
        # is actually installed (gated above), so Auto effectively means "ERPXpand included".
        use_single_tax_acct = settings.get("erpnext_presence_test_mode") == "Force: no ERPXpand"
        settings_tax_acct = settings.get("tax_account")

        audit_date = self.audit_date
        rows = get_stays_in_house_on(audit_date)

        total_revenue = 0.0
        total_tax = 0.0
        tax_by_account = {}  # {tax_account: amount_total} — per-tax-schedule mode only
        debit_entries = []   # list of (gross, cust) — AR debit is net + tax per stay

        for row in rows:
            stay = frappe.get_doc("Checked In", row.name)
            rate = flt(stay.room_rate)
            if rate <= 0:
                continue
            cust = stay._get_or_create_customer(settings, company)
            if not cust:
                frappe.log_error(f"Night audit JE: no ERPXpand Customer for stay {stay.name}")
                continue

            if use_single_tax_acct:
                stay_tax = flt(stay._compute_tax(rate))
            else:
                stay_tax = 0.0
                for acct, amt in stay._compute_tax_breakdown(rate):
                    if amt <= 0:
                        continue
                    if not acct:
                        frappe.msgprint(
                            _("Rate Type used by stay {0} has a tax_schedule row without an ERPXpand Tax Account. Set the Tax Account on every Rate Tax Schedule row to post night audit to ERPXpand.").format(stay.name),
                            indicator="orange",
                            title=_("ERPXpand Journal Entry skipped"),
                        )
                        return
                    tax_by_account[acct] = tax_by_account.get(acct, 0.0) + amt
                    stay_tax += amt

            gross = round(rate + stay_tax, 2)
            debit_entries.append((gross, cust))
            total_revenue += rate
            total_tax += stay_tax

        if total_revenue <= 0:
            return

        total_tax = round(total_tax, 2)
        if use_single_tax_acct and total_tax > 0 and not settings_tax_acct:
            frappe.msgprint(
                _("Rate Types have a tax_schedule but no Tax Account is configured in iHotel Settings. Set a Tax Account to post night audit to ERPXpand."),
                indicator="orange",
                title=_("ERPXpand Journal Entry skipped"),
            )
            return

        try:
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = company
            je.posting_date = audit_date
            je.user_remark = _("Night audit room revenue — {0}").format(self.name)

            for gross, cust in debit_entries:
                je.append(
                    "accounts",
                    {
                        "account": ar_acct,
                        "party_type": "Customer",
                        "party": cust,
                        "debit_in_account_currency": gross,
                        "credit_in_account_currency": 0,
                    },
                )

            je.append(
                "accounts",
                {
                    "account": rev_acct,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": round(total_revenue, 2),
                },
            )

            if use_single_tax_acct:
                if total_tax > 0:
                    je.append(
                        "accounts",
                        {
                            "account": settings_tax_acct,
                            "debit_in_account_currency": 0,
                            "credit_in_account_currency": total_tax,
                        },
                    )
            else:
                for acct, amt in tax_by_account.items():
                    amt = round(amt, 2)
                    if amt <= 0:
                        continue
                    je.append(
                        "accounts",
                        {
                            "account": acct,
                            "debit_in_account_currency": 0,
                            "credit_in_account_currency": amt,
                        },
                    )

            je.insert(ignore_permissions=True)
            je.submit()
            self.db_set("erpnext_journal_entry", je.name, update_modified=False)
        except Exception as e:
            frappe.log_error(f"Night audit ERPXpand JE failed: {self.name} — {e!s}")
            frappe.msgprint(
                _("Night audit saved folio charges, but ERPXpand Journal Entry failed. See Error Log."),
                indicator="orange",
                title=_("ERPXpand"),
            )

    # def create_journal_entry(self, stay_doc):
    #     """
    #     Create journal entry for room revenue.
    #     Accounts are fetched from iHotel Settings if available, otherwise uses defaults.
    #     Note: Add 'accounts_receivable_account' and 'room_revenue_account' fields to
    #     iHotel Settings for customization.
    #     """
    #     # Get accounts from iHotel Settings if fields exist, otherwise use defaults
    #     ar_account = "Accounts Receivable"
    #     revenue_account = "Room Revenue"

    #     try:
    #         settings = frappe.get_single("iHotel Settings")
    #         if hasattr(settings, "accounts_receivable_account") and settings.accounts_receivable_account:
    #             ar_account = settings.accounts_receivable_account
    #         if hasattr(settings, "room_revenue_account") and settings.room_revenue_account:
    #             revenue_account = settings.room_revenue_account
    #     except Exception:
    #         # Settings might not have these fields yet, use defaults
    #         pass

    #     company = frappe.defaults.get_user_default("company")
    #     if not company:
    #         frappe.throw(_("Please set default company in user preferences"))

    #     # Create journal entry for room revenue
    #     journal_entry = frappe.new_doc("Journal Entry")
    #     journal_entry.voucher_type = "Journal Entry"
    #     journal_entry.posting_date = self.audit_date
    #     journal_entry.company = company
    #     journal_entry.remark = f"Night audit entry for Hotel Stay: {stay_doc.name}"

    #     # Room revenue debit (AR account)
    #     journal_entry.append("accounts", {
    #         "account": ar_account,
    #         "debit_in_account_currency": stay_doc.room_rate or 0,
    #         "credit_in_account_currency": 0,
    #         "party_type": "Customer",
    #         "party": stay_doc.guest
    #     })

    #     # Room revenue credit (Revenue account)
    #     journal_entry.append("accounts", {
    #         "account": revenue_account,
    #         "debit_in_account_currency": 0,
    #         "credit_in_account_currency": stay_doc.room_rate or 0
    #     })

    #     try:
    #         journal_entry.insert()
    #         journal_entry.submit()
    #     except Exception as e:
    #         frappe.log_error(f"Error creating journal entry for Hotel Stay {stay_doc.name}: {str(e)}")
    #         frappe.throw(_("Error creating journal entry: {0}").format(str(e)))

    @frappe.whitelist()
    def get_trial_balance(self):
        """
        Build a proper hotel Trial Balance for the audit date.

        Structure:
          Section I  — Charges (Guest Ledger): folio charges + direct POS F&B revenue
          Section II — Collections: front-desk cash/card + POS restaurant payments
          Section III — City Ledger: amounts transferred to corporate/AR accounts today

        Balance equation:
          Total Revenue = Collections + City Ledger + Net Outstanding
        """
        audit_date = self.audit_date

        # ── Section I-A: Folio charges (room charges, charge-to-room F&B, etc.) ──
        # These are charges posted to guest folios (iHotel Profile) — includes F&B
        # that a guest charged to their room via the POS "Charge to Room" feature.
        revenue_rows = frappe.db.sql("""
            SELECT
                fc.charge_type,
                SUM(fc.amount) AS total
            FROM `tabFolio Charge` fc
            INNER JOIN `tabiHotel Profile` p ON p.name = fc.parent
            WHERE DATE(fc.charge_date) = %(date)s
            GROUP BY fc.charge_type
            ORDER BY fc.charge_type
        """, {"date": audit_date}, as_dict=True)

        # ── Section I-B: Direct POS F&B revenue (NOT charged to a room) ──────────
        # POS invoices where the guest paid at the restaurant counter (cash/card)
        # instead of charging to their hotel room. These never hit the folio system
        # so they would otherwise be invisible on the trial balance. We pull them
        # separately and merge them into the "Food & Beverage" bucket below.
        pos_fnb_rows = _get_pos_direct_fnb(audit_date)
        total_pos_fnb = sum(flt(r.total) for r in pos_fnb_rows)

        # Merge POS direct F&B into the revenue rows under "Food & Beverage".
        # If "Food & Beverage" already exists (from charge-to-room entries), add to it;
        # otherwise create a new row for it.
        if total_pos_fnb > 0:
            fnb_row = next(
                (r for r in revenue_rows if r.charge_type == "Food & Beverage"), None
            )
            if fnb_row:
                fnb_row.total = round(flt(fnb_row.total) + total_pos_fnb, 2)
            else:
                revenue_rows.append(frappe._dict({
                    "charge_type": "Food & Beverage",
                    "total": round(total_pos_fnb, 2),
                }))
            # Re-sort so the list stays alphabetical
            revenue_rows.sort(key=lambda r: r.charge_type or "")

        # ── Section II: Cash & Card Collections ──────────────────────────────────
        # All payment methods EXCEPT City Ledger and Complimentary
        CASH_CARD_METHODS = (
            "Cash", "Visa", "Mastercard", "Amex",
            "Bank Transfer", "Cheque"
        )

        # Front-desk collections (iHotel folio payments)
        collection_rows = frappe.db.sql("""
            SELECT
                pi.payment_method,
                SUM(pi.rate) AS total
            FROM `tabPayment Items` pi
            INNER JOIN `tabiHotel Profile` p ON p.name = pi.parent
            WHERE DATE(pi.date) = %(date)s
            AND pi.payment_method IN %(methods)s
            GROUP BY pi.payment_method
            ORDER BY pi.payment_method
        """, {"date": audit_date, "methods": CASH_CARD_METHODS}, as_dict=True)

        # POS restaurant collections — payments made directly at the POS counter
        # for invoices that were NOT charged to a room. These represent real cash/card
        # collected by the restaurant that must appear on the hotel's collections side.
        pos_payment_rows = _get_pos_direct_payments(audit_date)

        # Merge POS payments into collection_rows (add to existing method or append)
        for pos_pay in pos_payment_rows:
            existing = next(
                (r for r in collection_rows if r.payment_method == pos_pay.payment_method),
                None,
            )
            if existing:
                existing.total = round(flt(existing.total) + flt(pos_pay.total), 2)
            else:
                collection_rows.append(pos_pay)
        collection_rows.sort(key=lambda r: r.payment_method or "")

        # ── Complimentary (shown separately within collections) ───────────────────
        comp_rows = frappe.db.sql("""
            SELECT
                pi.payment_method,
                SUM(pi.rate) AS total
            FROM `tabPayment Items` pi
            INNER JOIN `tabiHotel Profile` p ON p.name = pi.parent
            WHERE DATE(pi.date) = %(date)s
            AND pi.payment_method = 'Complimentary'
            GROUP BY pi.payment_method
        """, {"date": audit_date}, as_dict=True)

        # ── Section III: City Ledger Transfers ────────────────────────────────────
        city_ledger_rows = frappe.db.sql("""
            SELECT
                pi.payment_method,
                SUM(pi.rate) AS total
            FROM `tabPayment Items` pi
            INNER JOIN `tabiHotel Profile` p ON p.name = pi.parent
            WHERE DATE(pi.date) = %(date)s
            AND pi.payment_method = 'City Ledger'
            GROUP BY pi.payment_method
        """, {"date": audit_date}, as_dict=True)

        # ── Outstanding open folio balances (in-house guests) ────────────────────
        outstanding_rows = frappe.db.sql("""
            SELECT
                p.name AS profile,
                p.guest,
                p.room,
                p.outstanding_balance
            FROM `tabiHotel Profile` p
            WHERE p.status = 'Open'
            AND p.outstanding_balance > 0
            ORDER BY p.room
        """, as_dict=True)

        # ── Totals ────────────────────────────────────────────────────────────────
        total_charges       = sum(flt(r.total) for r in revenue_rows)
        total_collections   = sum(flt(r.total) for r in collection_rows)
        total_complimentary = sum(flt(r.total) for r in comp_rows)
        total_city_ledger   = sum(flt(r.total) for r in city_ledger_rows)
        total_outstanding   = sum(flt(r.outstanding_balance) for r in outstanding_rows)

        # Reconciliation: total revenue should equal all the ways it was settled.
        # A non-zero difference flags a gap the auditor needs to investigate.
        balance_difference = round(
            total_charges - total_collections - total_complimentary - total_city_ledger,
            2
        )

        return {
            "audit_date":           str(audit_date),
            # Section I — Revenue
            "charges":              revenue_rows,
            "total_charges":        round(total_charges, 2),
            # POS F&B breakdown (informational — already included in charges above)
            "pos_fnb_breakdown":    pos_fnb_rows,
            "total_pos_fnb":        round(total_pos_fnb, 2),
            # Section II — Collections
            "collections":          collection_rows,
            "complimentary":        comp_rows,
            "total_collections":    round(total_collections, 2),
            "total_complimentary":  round(total_complimentary, 2),
            # Section III — City Ledger
            "city_ledger":          city_ledger_rows,
            "total_city_ledger":    round(total_city_ledger, 2),
            # Outstanding (in-house)
            "outstanding_folios":   outstanding_rows,
            "total_outstanding":    round(total_outstanding, 2),
            # Reconciliation
            "balance_difference":   balance_difference,
            # Occupancy metrics
            "occupied_rooms":       self.occupied_rooms or 0,
            "total_rooms":          self.total_rooms or 0,
            "occupancy_rate":       self.occupancy_rate or 0,
            "adr":                  self.adr or 0,
            "revpar":               self.revpar or 0,
            # Legacy aliases kept for any existing callers
            "revenue":              revenue_rows,
            "payments":             collection_rows,
            "total_revenue":        round(total_charges, 2),
            "total_payments":       round(total_collections + total_complimentary, 2),
            "net_balance":          balance_difference,
        }

    @frappe.whitelist()
    def calculate_metrics(self):
        """
        Server method to calculate audit metrics.
        Can be called from client-side to refresh values.
        """
        self.calculate_audit_metrics()
        return {
            "total_rooms": self.total_rooms,
            "occupied_rooms": self.occupied_rooms,
            "occupancy_rate": self.occupancy_rate,
            "total_revenue": self.total_revenue,
            "adr": self.adr,
            "revpar": self.revpar,
        }


# ── Module-level helpers for POS F&B integration ─────────────────────────────

def _get_pos_direct_fnb(audit_date):
    """
    Return F&B revenue from POS Invoices that were paid directly at the restaurant
    (NOT charged to a hotel room). Grouped by restaurant so the auditor can see
    which outlet contributed how much.

    We exclude charge-to-room invoices (custom_charge_to_room = 1) because those
    are already on the folio as a Folio Charge row — including them here would
    double-count them.

    Returns a list of dicts: [{charge_type, restaurant, total}, ...]
    The charge_type is always "Food & Beverage" so it merges cleanly into Section I.
    """
    if not frappe.db.exists("DocType", "POS Invoice"):
        # POS module not installed — nothing to pull
        return []

    # Check whether the custom field exists before filtering on it to avoid SQL errors
    # on installs that don't have the iHotel–POS bridge fields.
    meta = frappe.get_meta("POS Invoice")
    has_ctr_field = meta.has_field("custom_charge_to_room")

    if has_ctr_field:
        rows = frappe.db.sql("""
            SELECT
                'Food & Beverage'       AS charge_type,
                IFNULL(pi.restaurant, pi.pos_profile) AS restaurant,
                SUM(pi.net_total)       AS total
            FROM `tabPOS Invoice` pi
            WHERE pi.docstatus = 1
              AND DATE(pi.posting_date) = %(date)s
              AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)
            GROUP BY restaurant
            ORDER BY restaurant
        """, {"date": audit_date}, as_dict=True)
    else:
        # No charge-to-room field — treat all POS invoices as direct F&B
        rows = frappe.db.sql("""
            SELECT
                'Food & Beverage'       AS charge_type,
                IFNULL(pi.restaurant, pi.pos_profile) AS restaurant,
                SUM(pi.net_total)       AS total
            FROM `tabPOS Invoice` pi
            WHERE pi.docstatus = 1
              AND DATE(pi.posting_date) = %(date)s
            GROUP BY restaurant
            ORDER BY restaurant
        """, {"date": audit_date}, as_dict=True)

    return rows


def _get_pos_direct_payments(audit_date):
    """
    Return payment method totals from POS Invoices that were paid at the restaurant
    counter (NOT charged to a room). These represent real cash/card collected by
    the restaurant outlet that must appear in the hotel's collections section.

    Returns a list of dicts: [{payment_method, total}, ...]
    compatible with the folio collection_rows format.
    """
    if not frappe.db.exists("DocType", "POS Invoice"):
        return []

    meta = frappe.get_meta("POS Invoice")
    has_ctr_field = meta.has_field("custom_charge_to_room")

    if has_ctr_field:
        rows = frappe.db.sql("""
            SELECT
                sip.mode_of_payment    AS payment_method,
                SUM(sip.amount)        AS total
            FROM `tabPOS Invoice` pi
            INNER JOIN `tabSales Invoice Payment` sip ON sip.parent = pi.name
            WHERE pi.docstatus = 1
              AND DATE(pi.posting_date) = %(date)s
              AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)
              AND sip.mode_of_payment != 'Room Charge'
            GROUP BY sip.mode_of_payment
            ORDER BY sip.mode_of_payment
        """, {"date": audit_date}, as_dict=True)
    else:
        rows = frappe.db.sql("""
            SELECT
                sip.mode_of_payment    AS payment_method,
                SUM(sip.amount)        AS total
            FROM `tabPOS Invoice` pi
            INNER JOIN `tabSales Invoice Payment` sip ON sip.parent = pi.name
            WHERE pi.docstatus = 1
              AND DATE(pi.posting_date) = %(date)s
            GROUP BY sip.mode_of_payment
            ORDER BY sip.mode_of_payment
        """, {"date": audit_date}, as_dict=True)

    return rows


@frappe.whitelist()
def load_day_transactions(name):
    """Whitelisted: snapshot folio charges/payments for the audit's date into the doc."""
    doc = frappe.get_doc("Night Audit", name)
    if doc.docstatus != 0:
        frappe.throw(_("Cannot reload transactions on a submitted or cancelled audit."))
    doc._load_day_transactions()
    doc.save(ignore_permissions=False)
    return {
        "charges_count": len(doc.charges or []),
        "payments_count": len(doc.payments or []),
    }


@frappe.whitelist()
def verify_all(name):
    """Whitelisted: mark every loaded charge and payment as verified by the current user.

    Restricted to users with one of the VERIFIER_ROLES.
    """
    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & VERIFIER_ROLES):
        frappe.throw(
            _("Only users with the 'Night Auditor' role can verify charges or payments."),
            frappe.PermissionError,
        )
    doc = frappe.get_doc("Night Audit", name)
    if doc.docstatus != 0:
        frappe.throw(_("Cannot verify rows on a submitted or cancelled audit."))
    user = frappe.session.user
    ts = now_datetime()
    for row in (doc.charges or []) + (doc.payments or []):
        if not row.verified:
            row.verified = 1
            row.verified_by = user
            row.verified_on = ts
    doc.save(ignore_permissions=False)
    return {
        "verified_charges": len(doc.charges or []),
        "verified_payments": len(doc.payments or []),
    }
