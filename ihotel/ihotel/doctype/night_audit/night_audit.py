# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime, date
from frappe.utils import getdate, flt

from ihotel.ihotel.doctype.charge_type.charge_type import resolve_hotel_account_for_charge_type

class NightAudit(Document):
    def validate(self):
        """
        Validate night audit before submission.
        """
        if not self.performed_by:
            self.performed_by = frappe.session.user
        self.validate_audit_date()
        self.calculate_audit_metrics()

    def calculate_audit_metrics(self):
        """
        Calculate night audit metrics for the audit date:
        - Total rooms from Room doctype count
        - Occupied rooms: guests in-house on the audit date
        - Occupancy rate (occupied / total * 100)
        - Total revenue from in-house stays
        """
        self.total_rooms = frappe.db.count("Room") or 0

        audit_date = self.audit_date
        occupied_stays = frappe.db.sql("""
            SELECT name, room_rate
            FROM `tabChecked In`
            WHERE status = 'Checked In'
            AND docstatus = 1
            AND DATE(expected_check_in) <= %(date)s
            AND DATE(expected_check_out) > %(date)s
        """, {"date": audit_date}, as_dict=True)

        self.occupied_rooms = len(occupied_stays)

        if self.total_rooms and self.total_rooms > 0:
            self.occupancy_rate = (self.occupied_rooms / self.total_rooms) * 100
        else:
            self.occupancy_rate = 0

        self.total_revenue = sum(stay.room_rate or 0 for stay in occupied_stays)
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

    def after_insert(self):
        """
        Night audit should also run as soon as the document is created.
        """
        self.run_night_audit()

    def run_night_audit(self):
        """
        Post one nightly room charge per guest who is in-house on the audit date.
        A guest is in-house if: check_in <= audit_date < check_out.
        The charge is posted with the audit date, not the current date.
        """
        audit_date = self.audit_date

        in_house_stays = frappe.db.sql("""
            SELECT name FROM `tabChecked In`
            WHERE status = 'Checked In'
            AND docstatus = 1
            AND DATE(expected_check_in) <= %(date)s
            AND DATE(expected_check_out) > %(date)s
        """, {"date": audit_date}, as_dict=True)

        for stay in in_house_stays:
            stay_doc = frappe.get_doc("Checked In", stay.name)
            profile_doc = self.ensure_profile_for_stay(stay_doc)
            self.add_payment_entry(profile_doc, stay_doc)
            # Mark room as Occupied Dirty for housekeeping
            if stay_doc.room:
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
        Append a nightly room charge to the folio using the audit date.
        Skips if a room charge for this audit date already exists (prevents duplicates on re-run).
        """
        audit_date = self.audit_date

        # Duplicate guard: don't post twice for the same audit date
        already_posted = any(
            str(r.charge_date) == str(audit_date)
            and r.charge_type == "Room Charge"
            and r.reference_name == stay_doc.name
            for r in profile_doc.get("charges", [])
        )
        if already_posted:
            return

        # Resolve mapping so configuration can be validated early by lookup.
        resolve_hotel_account_for_charge_type("Room Charge")

        profile_doc.append("charges", {
            "charge_date": audit_date,
            "charge_type": "Room Charge",
            "description": _("Nightly room charge — Room {0} ({1})").format(
                stay_doc.room or "", audit_date
            ),
            "quantity": 1,
            "rate": stay_doc.room_rate or 0,
            "amount": stay_doc.room_rate or 0,
            "reference_doctype": "Checked In",
            "reference_name": stay_doc.name,
        })
        profile_doc.save(ignore_permissions=True)

    def _post_erpnext_journal_for_night_audit(self):
        """
        When ERPXpand (ERPNext) is installed and iHotel Settings opt-in is on, post one Journal Entry
        for in-house room revenue (Dr receivable / Cr room revenue). Checkout Sales Invoices should
        omit Room Charge lines (same setting) so revenue is not doubled.
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

        company = settings.company
        ar_acct = settings.accounts_receivable_account
        rev_acct = settings.room_revenue_account
        if not all([company, ar_acct, rev_acct]):
            frappe.msgprint(
                _("Set Company, Accounts Receivable and Room Revenue in iHotel Settings to post night audit to ERPXpand."),
                indicator="orange",
                title=_("ERPXpand Journal Entry skipped"),
            )
            return

        audit_date = self.audit_date
        rows = frappe.db.sql(
            """
            SELECT name FROM `tabChecked In`
            WHERE status = 'Checked In'
            AND docstatus = 1
            AND DATE(expected_check_in) <= %(date)s
            AND DATE(expected_check_out) > %(date)s
            """,
            {"date": audit_date},
            as_dict=True,
        )

        total_credit = 0.0
        debit_entries = []

        for row in rows:
            stay = frappe.get_doc("Checked In", row.name)
            rate = flt(stay.room_rate)
            if rate <= 0:
                continue
            cust = stay._get_or_create_customer(settings, company)
            if not cust:
                frappe.log_error(f"Night audit JE: no ERPXpand Customer for stay {stay.name}")
                continue
            debit_entries.append((rate, cust))
            total_credit += rate

        if total_credit <= 0:
            return

        try:
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = company
            je.posting_date = audit_date
            je.user_remark = _("Night audit room revenue — {0}").format(self.name)

            for rate, cust in debit_entries:
                je.append(
                    "accounts",
                    {
                        "account": ar_acct,
                        "party_type": "Customer",
                        "party": cust,
                        "debit_in_account_currency": rate,
                        "credit_in_account_currency": 0,
                    },
                )

            je.append(
                "accounts",
                {
                    "account": rev_acct,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": total_credit,
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
          Section I  — Charges (Guest Ledger): all revenue posted today by charge type
          Section II — Collections: cash & card payments received today
          Section III — City Ledger: amounts transferred to corporate/AR accounts today

        Balance equation:
          Guest Ledger Total = Collections + City Ledger + Net Outstanding
        """
        audit_date = self.audit_date

        # ── Section I: Revenue / Charges ─────────────────────────────────────
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

        # ── Section II: Cash & Card Collections ──────────────────────────────
        # All payment methods EXCEPT City Ledger and Complimentary
        CASH_CARD_METHODS = (
            "Cash", "Visa", "Mastercard", "Amex",
            "Bank Transfer", "Cheque"
        )
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

        # ── Complimentary (shown separately within collections) ───────────────
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

        # ── Section III: City Ledger Transfers ────────────────────────────────
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

        # ── Outstanding open folio balances (in-house guests) ────────────────
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

        # ── Totals ────────────────────────────────────────────────────────────
        total_charges      = sum(r.total or 0 for r in revenue_rows)
        total_collections  = sum(r.total or 0 for r in collection_rows)
        total_complimentary = sum(r.total or 0 for r in comp_rows)
        total_city_ledger  = sum(r.total or 0 for r in city_ledger_rows)
        total_outstanding  = sum(r.outstanding_balance or 0 for r in outstanding_rows)

        # Net balance check: charges should equal collections + city ledger + outstanding
        # (small float differences are normal; this is the reconciliation figure)
        balance_difference = round(
            total_charges - total_collections - total_complimentary - total_city_ledger,
            2
        )

        return {
            "audit_date":           str(audit_date),
            # Section I
            "charges":              revenue_rows,
            "total_charges":        round(total_charges, 2),
            # Section II
            "collections":          collection_rows,
            "complimentary":        comp_rows,
            "total_collections":    round(total_collections, 2),
            "total_complimentary":  round(total_complimentary, 2),
            # Section III
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
