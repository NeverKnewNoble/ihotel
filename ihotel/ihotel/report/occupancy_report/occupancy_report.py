# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, add_days, flt


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"fieldname": "date",           "label": _("Date"),           "fieldtype": "Date",     "width": 110},
        {"fieldname": "total_rooms",    "label": _("Total Rooms"),    "fieldtype": "Int",      "width": 100},
        {"fieldname": "occupied_rooms", "label": _("Occupied"),       "fieldtype": "Int",      "width": 90},
        {"fieldname": "occupancy_rate", "label": _("Occupancy %"),    "fieldtype": "Percent",  "width": 110},
        {"fieldname": "revenue",        "label": _("Room Revenue"),   "fieldtype": "Currency", "width": 130},
        {"fieldname": "adr",            "label": _("ADR"),            "fieldtype": "Currency", "width": 120,
         "description": "Average Daily Rate — revenue ÷ occupied rooms"},
        {"fieldname": "revpar",         "label": _("RevPAR"),         "fieldtype": "Currency", "width": 120,
         "description": "Revenue Per Available Room — revenue ÷ total rooms"},
    ]


def get_data(filters):
    from_date = getdate(filters.get("from_date") or frappe.utils.add_months(frappe.utils.today(), -1))
    to_date   = getdate(filters.get("to_date")   or frappe.utils.today())

    total_rooms = flt(frappe.get_single("iHotel Settings").get("total_rooms") or 0)
    if not total_rooms:
        total_rooms = flt(frappe.db.count("Room",
            filters={"status": ["not in", ["Out of Order", "Out of Service"]]}))

    data = []
    current = from_date
    while current <= to_date:
        date_str = str(current)

        # Count rooms occupied on this date (stay spans this date)
        occupied = frappe.db.sql("""
            SELECT COUNT(DISTINCT room) as cnt, SUM(room_rate) as rev
            FROM `tabChecked In`
            WHERE status IN ('Checked In', 'Checked Out', 'Reserved')
            AND docstatus = 1
            AND room IS NOT NULL AND room != ''
            AND DATE(expected_check_in) <= %s
            AND DATE(expected_check_out) > %s
        """, (date_str, date_str), as_dict=True)

        occ_count = flt(occupied[0].cnt) if occupied else 0
        revenue = flt(occupied[0].rev) if occupied else 0

        occ_rate = round(occ_count / total_rooms * 100, 2) if total_rooms else 0
        adr = round(revenue / occ_count, 2) if occ_count else 0
        revpar = round(revenue / total_rooms, 2) if total_rooms else 0

        data.append({
            "date": current,
            "total_rooms": int(total_rooms),
            "occupied_rooms": int(occ_count),
            "occupancy_rate": occ_rate,
            "revenue": revenue,
            "adr": adr,
            "revpar": revpar,
        })

        current = add_days(current, 1)

    return data
