# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

"""
Migration: copy Laundry Order.reservation_id → checked_in

The field was renamed from a free-text "Reservation ID" (which actually stored
a Checked In document name) to a proper Link field called "checked_in".
This patch backfills the new column for every existing Laundry Order that has a
non-empty reservation_id and an empty checked_in, so no historical data is lost.

Only copies the value when:
  1. reservation_id is not blank
  2. checked_in is currently blank (prevents overwriting manual corrections)
  3. The referenced Checked In document actually exists in the database
"""

import frappe


def execute():
    # Frappe won't know the new column exists until the migration runs, so we use
    # raw SQL to be safe. The column is added by the DocType migration before
    # post_model_sync patches run.
    if not frappe.db.has_column("Laundry Order", "checked_in"):
        frappe.log_error(
            "Laundry Order.checked_in column not found — skipping backfill patch.",
            "Patch: rename_laundry_reservation_id_to_checked_in",
        )
        return

    # Fetch rows that need migration: have reservation_id but no checked_in
    rows = frappe.db.sql(
        """
        SELECT name, reservation_id
        FROM `tabLaundry Order`
        WHERE reservation_id IS NOT NULL
          AND reservation_id != ''
          AND (checked_in IS NULL OR checked_in = '')
        """,
        as_dict=True,
    )

    if not rows:
        return

    migrated = 0
    skipped = 0
    for row in rows:
        # Only copy when the Checked In document actually exists — otherwise warn
        if frappe.db.exists("Checked In", row.reservation_id):
            frappe.db.set_value(
                "Laundry Order",
                row.name,
                "checked_in",
                row.reservation_id,
                update_modified=False,
            )
            migrated += 1
        else:
            frappe.log_error(
                f"Laundry Order {row.name}: reservation_id '{row.reservation_id}' "
                "does not match any Checked In record. Manual cleanup may be needed.",
                "Patch: rename_laundry_reservation_id_to_checked_in",
            )
            skipped += 1

    frappe.db.commit()
    print(f"Laundry reservation_id → checked_in: {migrated} migrated, {skipped} skipped (no matching Checked In).")
