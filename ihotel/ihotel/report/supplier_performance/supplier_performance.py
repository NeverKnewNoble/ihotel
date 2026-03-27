# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}

	columns = [
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Laundry Supplier", "width": 180},
		{"label": _("Total Batches"), "fieldname": "total_batches", "fieldtype": "Int", "width": 110},
		{"label": _("Total Items"), "fieldname": "total_items", "fieldtype": "Int", "width": 100},
		{"label": _("Avg Turnaround (hrs)"), "fieldname": "avg_turnaround", "fieldtype": "Float", "width": 160},
		{"label": _("On-Time %"), "fieldname": "on_time_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Damage / Loss %"), "fieldname": "damage_rate", "fieldtype": "Percent", "width": 130},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 120},
	]

	conditions = ["vb.status = 'Completed'"]
	values = {}

	if filters.get("supplier"):
		conditions.append("vb.supplier = %(supplier)s")
		values["supplier"] = filters["supplier"]
	if filters.get("from_date"):
		conditions.append("vb.batch_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("vb.batch_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	where = "WHERE " + " AND ".join(conditions)

	data = frappe.db.sql(f"""
		SELECT
			vb.supplier,
			COUNT(DISTINCT vb.name) AS total_batches,
			SUM(vb.total_items) AS total_items,
			ROUND(AVG(
				CASE
					WHEN vb.pickup_datetime IS NOT NULL AND vb.return_datetime IS NOT NULL
					THEN TIMESTAMPDIFF(MINUTE, vb.pickup_datetime, vb.return_datetime) / 60.0
					ELSE NULL
				END
			), 1) AS avg_turnaround,
			ROUND(
				SUM(CASE
					WHEN vb.pickup_datetime IS NOT NULL
						AND vb.return_datetime IS NOT NULL
						AND ls.lead_time_hours IS NOT NULL
						AND vb.return_datetime <=
							DATE_ADD(vb.pickup_datetime, INTERVAL ls.lead_time_hours HOUR)
					THEN 1 ELSE 0
				END) / NULLIF(COUNT(vb.name), 0) * 100
			, 2) AS on_time_pct,
			ROUND(
				SUM(CASE
					WHEN damaged.order_name IS NOT NULL THEN 1 ELSE 0
				END) / NULLIF(SUM(vb.total_items), 0) * 100
			, 2) AS damage_rate,
			SUM(COALESCE(vb.supplier_invoice_amount, 0)) AS total_cost
		FROM `tabSupplier Batch` vb
		JOIN `tabLaundry Supplier` ls ON ls.name = vb.supplier
		LEFT JOIN (
			SELECT DISTINCT sbo.parent AS batch_name, sbo.laundry_order AS order_name
			FROM `tabSupplier Batch Order` sbo
			JOIN `tabLaundry Order Item` loi ON loi.parent = sbo.laundry_order
			WHERE loi.status IN ('Damaged', 'Lost')
		) damaged ON damaged.batch_name = vb.name
		{where}
		GROUP BY vb.supplier
		ORDER BY total_cost DESC
	""", values, as_dict=True)

	return columns, data
