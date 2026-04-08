# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    # Append summary row
    data += get_summary(filters, data)
    return columns, data


def get_columns():
    return [
        {"label": _("Room Type"),      "fieldname": "room_type",      "fieldtype": "Link",     "options": "Room Type",               "width": 150},
        {"label": _("Business Source"),"fieldname": "business_source","fieldtype": "Link",     "options": "Business Source Category","width": 180},
        {"label": _("Total Stays"),    "fieldname": "total_stays",    "fieldtype": "Int",      "width": 100},
        {"label": _("Total Nights"),   "fieldname": "total_nights",   "fieldtype": "Int",      "width": 100},
        {"label": _("Total Revenue"),  "fieldname": "total_revenue",  "fieldtype": "Currency", "width": 150},
        {"label": _("ADR"),            "fieldname": "adr",            "fieldtype": "Currency", "width": 120,
         "description": "Average Daily Rate"},
    ]


def get_data(filters):
    conditions = ["hs.docstatus = 1"]
    values = {}

    if filters.get("from_date"):
        conditions.append("hs.expected_check_in >= %(from_date)s")
        values["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conditions.append("hs.expected_check_in <= %(to_date)s")
        values["to_date"] = filters["to_date"]
    if filters.get("room_type"):
        conditions.append("hs.room_type = %(room_type)s")
        values["room_type"] = filters["room_type"]
    if filters.get("business_source"):
        conditions.append("hs.business_source = %(business_source)s")
        values["business_source"] = filters["business_source"]

    where = " AND ".join(conditions)

    rows = frappe.db.sql(f"""
        SELECT
            hs.room_type,
            hs.business_source,
            COUNT(hs.name) as total_stays,
            SUM(hs.nights) as total_nights,
            SUM(hs.total_amount) as total_revenue,
            CASE WHEN SUM(hs.nights) > 0
                 THEN SUM(hs.total_amount) / SUM(hs.nights)
                 ELSE 0 END as adr
        FROM `tabChecked In` hs
        WHERE {where}
        GROUP BY hs.room_type, hs.business_source
        ORDER BY total_revenue DESC
    """, values, as_dict=True)

    return rows


def get_summary(filters, data):
    """Add a grand-total row with overall ADR and RevPAR."""
    if not data:
        return []

    total_stays   = sum(flt(r.total_stays) for r in data)
    total_nights  = sum(flt(r.total_nights) for r in data)
    total_revenue = sum(flt(r.total_revenue) for r in data)
    adr = round(total_revenue / total_nights, 2) if total_nights else 0

    summary = [{
        "room_type": _("TOTAL"),
        "business_source": "",
        "total_stays": int(total_stays),
        "total_nights": int(total_nights),
        "total_revenue": total_revenue,
        "adr": adr,
        "bold": 1,
    }]

    return summary
