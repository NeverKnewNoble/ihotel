# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, nowdate, getdate


# Standard Ghana hotel taxes: (field_apply, field_rate, column_label, fieldname)
GHANA_TAXES = [
    ("apply_vat",          "vat_rate",          "VAT",             "vat_amount"),
    ("apply_nhil",         "nhil_rate",          "NHIL",            "nhil_amount"),
    ("apply_getfund",      "getfund_rate",        "GETFund",         "getfund_amount"),
    ("apply_covid_levy",   "covid_levy_rate",     "COVID-19 Levy",   "covid_amount"),
    ("apply_tourism_levy", "tourism_levy_rate",   "Tourism Levy",    "tourism_amount"),
]


def execute(filters=None):
    filters = filters or {}
    report_date = getdate(filters.get("date") or nowdate())

    stays = get_stays(report_date, filters)
    rate_type_cache = {}

    rows = []
    for stay in stays:
        rt = None
        if stay.rate_type:
            if stay.rate_type not in rate_type_cache:
                rate_type_cache[stay.rate_type] = frappe.get_cached_doc("Rate Type", stay.rate_type)
            rt = rate_type_cache[stay.rate_type]

        revenue = flt(stay.total_amount)
        row = {
            "checked_in": stay.name,
            "guest":       stay.guest or "",
            "room":        stay.room or "",
            "room_type":   stay.room_type or "",
            "rate_type":   stay.rate_type or "",
            "nights":      stay.nights or 0,
            "room_rate":   flt(stay.room_rate),
            "revenue":     revenue,
        }

        total_tax = 0.0

        # --- Ghana standard taxes ---
        for apply_field, rate_field, _, col_field in GHANA_TAXES:
            if rt and getattr(rt, apply_field, 0):
                rate = flt(getattr(rt, rate_field, 0))
                amount = round(revenue * rate / 100, 2)
            else:
                amount = 0.0
            row[col_field] = amount
            total_tax += amount

        # --- Custom / additional taxes ---
        custom_tax = 0.0
        if rt and rt.additional_taxes:
            for tax_row in rt.additional_taxes:
                custom_tax += round(revenue * flt(tax_row.tax_rate) / 100, 2)
        row["custom_tax_amount"] = custom_tax
        total_tax += custom_tax

        row["total_tax"]   = round(total_tax, 2)
        row["grand_total"] = round(revenue + total_tax, 2)

        rows.append(row)

    # Sort by guest name
    rows.sort(key=lambda r: r["guest"])

    columns = get_columns()
    return columns, rows


def get_stays(report_date, filters=None):
    """Return all submitted stays that were active on report_date."""
    conditions = [
        "docstatus = 1",
        "status IN ('Checked In', 'Checked Out', 'Reserved')",
        "DATE(expected_check_in)  <= %(date)s",
        "DATE(expected_check_out) >  %(date)s",
    ]
    values = {"date": report_date}

    if filters:
        if filters.get("rate_type"):
            conditions.append("rate_type = %(rate_type)s")
            values["rate_type"] = filters["rate_type"]
        if filters.get("room_type"):
            conditions.append("room_type = %(room_type)s")
            values["room_type"] = filters["room_type"]

    where = " AND ".join(conditions)
    return frappe.db.sql(f"""
        SELECT
            name,
            guest,
            room,
            room_type,
            rate_type,
            nights,
            room_rate,
            total_amount,
            status
        FROM `tabChecked In`
        WHERE {where}
    """, values, as_dict=True)


def get_columns():
    cols = [
        {"label": _("Checked In #"),  "fieldname": "checked_in",  "fieldtype": "Link",     "options": "Checked In", "width": 150},
        {"label": _("Guest"),          "fieldname": "guest",        "fieldtype": "Link",     "options": "Guest",      "width": 160},
        {"label": _("Room"),           "fieldname": "room",         "fieldtype": "Link",     "options": "Room",       "width": 80},
        {"label": _("Room Type"),      "fieldname": "room_type",    "fieldtype": "Link",     "options": "Room Type",  "width": 130},
        {"label": _("Rate Type"),      "fieldname": "rate_type",    "fieldtype": "Link",     "options": "Rate Type",  "width": 130},
        {"label": _("Nights"),         "fieldname": "nights",       "fieldtype": "Int",                               "width": 70},
        {"label": _("Room Rate"),      "fieldname": "room_rate",    "fieldtype": "Currency",                          "width": 110},
        {"label": _("Room Revenue"),   "fieldname": "revenue",      "fieldtype": "Currency",                          "width": 130},
    ]

    # One column per Ghana standard tax
    for _apply, _rate, label, fieldname in GHANA_TAXES:
        cols.append({
            "label":     _(label),
            "fieldname": fieldname,
            "fieldtype": "Currency",
            "width":     110,
        })

    cols += [
        {"label": _("Other Taxes"),    "fieldname": "custom_tax_amount", "fieldtype": "Currency", "width": 110},
        {"label": _("Total Tax"),      "fieldname": "total_tax",         "fieldtype": "Currency", "width": 120},
        {"label": _("Grand Total"),    "fieldname": "grand_total",       "fieldtype": "Currency", "width": 130},
    ]

    return cols
