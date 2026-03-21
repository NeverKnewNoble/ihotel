# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"label": _("Type"),           "fieldname": "type",          "fieldtype": "Data",     "width": 100},
        {"label": _("Stay"),           "fieldname": "stay",          "fieldtype": "Link",     "options": "Checked In", "width": 120},
        {"label": _("Guest"),          "fieldname": "guest",         "fieldtype": "Link",     "options": "Guest",      "width": 120},
        {"label": _("Guest Name"),     "fieldname": "guest_name",    "fieldtype": "Data",     "width": 160},
        {"label": _("Room"),           "fieldname": "room",          "fieldtype": "Link",     "options": "Room",       "width": 80},
        {"label": _("Room Type"),      "fieldname": "room_type",     "fieldtype": "Link",     "options": "Room Type",  "width": 120},
        {"label": _("Expected Time"),  "fieldname": "expected_time", "fieldtype": "Datetime", "width": 150},
        {"label": _("Nights"),         "fieldname": "nights",        "fieldtype": "Int",      "width": 70},
        {"label": _("Rate / Night"),   "fieldname": "room_rate",     "fieldtype": "Currency", "width": 120},
        {"label": _("Total Amount"),   "fieldname": "total_amount",  "fieldtype": "Currency", "width": 130},
        {"label": _("Status"),         "fieldname": "status",        "fieldtype": "Data",     "width": 100},
        {"label": _("Rate Type"),      "fieldname": "rate_type",     "fieldtype": "Link",     "options": "Rate Type",  "width": 120},
    ]


def get_data(filters):
    date = filters.get("date") or nowdate()

    # Arrivals
    arrivals = frappe.db.sql("""
        SELECT
            'Arrival' as type,
            ci.name as stay,
            ci.guest,
            g.guest_name,
            ci.room,
            ci.room_type,
            ci.expected_check_in as expected_time,
            ci.nights,
            ci.room_rate,
            ci.total_amount,
            ci.status,
            ci.rate_type
        FROM `tabChecked In` ci
        LEFT JOIN `tabGuest` g ON g.name = ci.guest
        WHERE DATE(ci.expected_check_in) = %s
        AND ci.docstatus != 2
        ORDER BY ci.expected_check_in
    """, date, as_dict=True)

    # Departures
    departures = frappe.db.sql("""
        SELECT
            'Departure' as type,
            ci.name as stay,
            ci.guest,
            g.guest_name,
            ci.room,
            ci.room_type,
            ci.expected_check_out as expected_time,
            ci.nights,
            ci.room_rate,
            ci.total_amount,
            ci.status,
            ci.rate_type
        FROM `tabChecked In` ci
        LEFT JOIN `tabGuest` g ON g.name = ci.guest
        WHERE DATE(ci.expected_check_out) = %s
        AND ci.docstatus != 2
        ORDER BY ci.expected_check_out
    """, date, as_dict=True)

    return arrivals + departures
