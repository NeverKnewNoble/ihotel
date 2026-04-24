"""Collapse legacy room statuses into the new 6-state housekeeping cycle.

Old states: Available, Occupied, Vacant Dirty, Occupied Dirty, Vacant Clean,
Occupied Clean, Dirty, Pickup, Inspected, Housekeeping, Out of Order, Out of Service.

New states: Available, Occupied, Vacant Dirty, Occupied Dirty, Out of Order, Out of Service.

Mapping (legacy → new):
  Vacant Clean   → Available
  Inspected      → Available
  Pickup         → Available
  Dirty          → Vacant Dirty
  Housekeeping   → Vacant Dirty
  Occupied Clean → Occupied

Idempotent. Safe to re-run.
"""

import frappe


_REMAP = {
	"Vacant Clean":   "Available",
	"Inspected":      "Available",
	"Pickup":         "Available",
	"Dirty":          "Vacant Dirty",
	"Housekeeping":   "Vacant Dirty",
	"Occupied Clean": "Occupied",
}


def execute():
	if not frappe.db.exists("DocType", "Room"):
		return

	updated = 0
	for old, new in _REMAP.items():
		count = frappe.db.count("Room", {"status": old})
		if not count:
			continue
		frappe.db.sql(
			"UPDATE `tabRoom` SET status=%s WHERE status=%s",
			(new, old),
		)
		updated += count
		print(f"iHotel: Room status '{old}' → '{new}': {count} rooms remapped.")

	if updated:
		frappe.db.commit()
