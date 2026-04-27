"""Drop the stale `tax_account` value from iHotel Settings if present.

A previous development branch introduced a single `tax_account` field on
iHotel Settings to aggregate all Night Audit JE tax into one credit line.
That model was replaced by per-tax-schedule routing (tax accounts come
from the stay's Rate Type tax_schedule), so the field is no longer read
by any code.

iHotel Settings is a Single DocType, so its data lives in `tabSingles`
(key/value), not a dedicated table. This patch removes any lingering
value for the `tax_account` field and any Custom Field record that may
have been created on sites that ran the old branch.
"""

import frappe


def execute():
	# Drop the stale Single-DocType value for this field, if any.
	frappe.db.delete("Singles", {"doctype": "iHotel Settings", "field": "tax_account"})

	# Defensive: drop any Custom Field record left behind by an earlier install.
	frappe.db.delete("Custom Field", {"dt": "iHotel Settings", "fieldname": "tax_account"})
