# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime, date
from frappe.utils import getdate

class NightAudit(Document):
    def validate(self):
        """
        Validate night audit before submission.
        """
        self.validate_audit_date()
        self.calculate_audit_metrics()

    def calculate_audit_metrics(self):
        """
        Calculate night audit metrics for the audit date:
        - Total rooms from iHotel Settings
        - Occupied rooms: guests in-house on the audit date
        - Occupancy rate (occupied / total * 100)
        - Total revenue from in-house stays
        """
        try:
            settings = frappe.get_single("iHotel Settings")
            self.total_rooms = settings.total_rooms or 0
        except Exception:
            frappe.throw(_("Please configure Total Rooms in iHotel Settings"))

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
        Build a Trial Balance for the audit date.
        Returns revenue grouped by charge type and payments grouped by payment method.
        """
        audit_date = self.audit_date

        revenue_rows = frappe.db.sql("""
            SELECT
                fc.charge_type,
                SUM(fc.amount) AS total
            FROM `tabFolio Charge` fc
            INNER JOIN `tabiHotel Profile` p ON p.name = fc.parent
            WHERE DATE(fc.charge_date) = %(date)s
            AND p.status != 'Transferred'
            GROUP BY fc.charge_type
            ORDER BY fc.charge_type
        """, {"date": audit_date}, as_dict=True)

        payment_rows = frappe.db.sql("""
            SELECT
                pi.payment_method,
                SUM(pi.rate) AS total
            FROM `tabPayment Items` pi
            INNER JOIN `tabiHotel Profile` p ON p.name = pi.parent
            WHERE DATE(pi.date) = %(date)s
            AND p.status != 'Transferred'
            GROUP BY pi.payment_method
            ORDER BY pi.payment_method
        """, {"date": audit_date}, as_dict=True)

        total_revenue  = sum(r.total or 0 for r in revenue_rows)
        total_payments = sum(r.total or 0 for r in payment_rows)

        return {
            "audit_date":     str(audit_date),
            "revenue":        revenue_rows,
            "payments":       payment_rows,
            "total_revenue":  total_revenue,
            "total_payments": total_payments,
            "net_balance":    round(total_revenue - total_payments, 2),
            "occupied_rooms": self.occupied_rooms or 0,
            "total_rooms":    self.total_rooms or 0,
            "occupancy_rate": self.occupancy_rate or 0,
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
