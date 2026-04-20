"""Migrate legacy single-field income accounts to the new Income Accounts table.

Before: iHotel Settings had two Link fields — `room_revenue_account` (used for the
"Room Charge" bucket) and `extra_charges_income_account` (used for every other
charge type).

After: A child table `income_accounts` (iHotel Income Account) on iHotel Settings
keyed by Charge Type. This patch seeds the table on first run so sites that
had set the old fields continue to post to the same accounts. Safe to run
multiple times — it skips rows that already exist.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "iHotel Settings"):
		return
	if not frappe.db.exists("DocType", "iHotel Income Account"):
		return

	# Pull legacy values directly from the Singles table; the fields are gone
	# from the JSON so the doctype controller no longer exposes them.
	legacy = {
		row.field: row.value
		for row in frappe.db.sql(
			"""SELECT field, value FROM `tabSingles`
			   WHERE doctype='iHotel Settings'
			     AND field IN ('room_revenue_account', 'extra_charges_income_account')""",
			as_dict=True,
		)
	}

	room_acct  = (legacy.get("room_revenue_account")  or "").strip()
	extra_acct = (legacy.get("extra_charges_income_account") or "").strip()

	if not (room_acct or extra_acct):
		return

	settings = frappe.get_single("iHotel Settings")
	existing_charge_types = {row.charge_type for row in settings.get("income_accounts", [])}

	seeded = []

	def _seed(charge_type, account):
		if not account or charge_type in existing_charge_types:
			return
		if not frappe.db.exists("Charge Type", charge_type):
			return
		if not frappe.db.exists("Account", account):
			return
		settings.append("income_accounts", {
			"charge_type": charge_type,
			"account":     account,
		})
		seeded.append(charge_type)

	_seed("Room Charge",          room_acct)
	_seed("Additional Service",   extra_acct)

	if seeded:
		settings.save(ignore_permissions=True)
		# Drop the now-obsolete Singles rows so they don't linger as orphans.
		frappe.db.delete("Singles", {
			"doctype": "iHotel Settings",
			"field": ("in", ("room_revenue_account", "extra_charges_income_account")),
		})
		print(
			f"iHotel: seeded Income Accounts table from legacy fields ({', '.join(seeded)})."
		)
