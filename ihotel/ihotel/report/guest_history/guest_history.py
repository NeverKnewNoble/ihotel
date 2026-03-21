# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": "Guest", "fieldname": "guest", "fieldtype": "Link", "options": "Guest", "width": 150},
		{"label": "Stay", "fieldname": "stay", "fieldtype": "Link", "options": "Checked In", "width": 120},
		{"label": "Room", "fieldname": "room", "fieldtype": "Link", "options": "Room", "width": 100},
		{"label": "Room Type", "fieldname": "room_type", "fieldtype": "Link", "options": "Room Type", "width": 120},
		{"label": "Checked In", "fieldname": "check_in", "fieldtype": "Datetime", "width": 160},
		{"label": "Check Out", "fieldname": "check_out", "fieldtype": "Datetime", "width": 160},
		{"label": "Nights", "fieldname": "nights", "fieldtype": "Int", "width": 80},
		{"label": "Total Amount", "fieldname": "total_amount", "fieldtype": "Currency", "width": 130},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	conditions = ["hs.docstatus != 2"]
	values = {}

	if filters.get("guest"):
		conditions.append("hs.guest = %(guest)s")
		values["guest"] = filters["guest"]

	where = " AND ".join(conditions)

	data = frappe.db.sql(f"""
		SELECT
			hs.guest,
			hs.name as stay,
			hs.room,
			hs.room_type,
			hs.expected_check_in as check_in,
			hs.expected_check_out as check_out,
			hs.nights,
			hs.total_amount,
			hs.status
		FROM `tabChecked In` hs
		WHERE {where}
		ORDER BY hs.guest, hs.expected_check_in DESC
	""", values, as_dict=True)

	return data
