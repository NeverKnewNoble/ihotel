# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, flt

from ihotel.ihotel.doctype.charge_type.charge_type import resolve_hotel_account_for_charge_type


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
                ):
                    frappe.db.set_value("Room", stay_doc.room, "status", "Occupied Dirty")
                continue

            profile_doc = self.ensure_profile_for_stay(stay_doc)
            self.add_payment_entry(profile_doc, stay_doc)
            # Housekeeping: only for today's audit and still in-house (skip backfill / checked-out)
            if (
                stay_doc.room
                and stay_doc.status == "Checked In"
                and getdate(audit_date) == today
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

        profile_doc.append("charges", {
            "charge_date": audit_date,
            "charge_type": "Room Charge",
            "description": _("Nightly room charge — Room {0} ({1})").format(
                stay_doc.room or "", audit_date
            ),
            "quantity": 1,
            "rate": nightly_rate,
            "amount": nightly_rate,
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
        rows = get_stays_in_house_on(audit_date)

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
