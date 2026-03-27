# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}

	columns = [
		{"label": _("Order"), "fieldname": "name", "fieldtype": "Link", "options": "Laundry Order", "width": 130},
		{"label": _("Date"), "fieldname": "order_date", "fieldtype": "Datetime", "width": 140},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
		{"label": _("Mode"), "fieldname": "processing_mode", "fieldtype": "Data", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 120},
		{"label": _("Supplier Cost"), "fieldname": "supplier_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 120},
		{"label": _("Margin %"), "fieldname": "margin", "fieldtype": "Percent", "width": 100},
	]

	conditions = ["lo.docstatus = 1"]
	values = {}

	if filters.get("from_date"):
		conditions.append("lo.order_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("lo.order_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]
	if filters.get("customer"):
		conditions.append("lo.customer = %(customer)s")
		values["customer"] = filters["customer"]
	if filters.get("processing_mode"):
		conditions.append("lo.processing_mode = %(processing_mode)s")
		values["processing_mode"] = filters["processing_mode"]
	if filters.get("status"):
		conditions.append("lo.status = %(status)s")
		values["status"] = filters["status"]

	where = "WHERE " + " AND ".join(conditions)

	data = frappe.db.sql(f"""
		SELECT
			lo.name,
			lo.order_date,
			lo.customer,
			lo.processing_mode,
			lo.status,
			lo.total_amount AS revenue,
			COALESCE(sb_agg.supplier_cost, 0) AS supplier_cost,
			lo.total_amount - COALESCE(sb_agg.supplier_cost, 0) AS profit,
			CASE
				WHEN lo.total_amount > 0
				THEN ROUND(
					(lo.total_amount - COALESCE(sb_agg.supplier_cost, 0))
					/ lo.total_amount * 100, 2
				)
				ELSE 0
			END AS margin
		FROM `tabLaundry Order` lo
		LEFT JOIN (
			SELECT
				sbo.laundry_order,
				SUM(sb.supplier_invoice_amount / NULLIF(sb_cnt.order_count, 0)) AS supplier_cost
			FROM `tabSupplier Batch Order` sbo
			JOIN `tabSupplier Batch` sb ON sb.name = sbo.parent
			JOIN (
				SELECT parent, COUNT(*) AS order_count
				FROM `tabSupplier Batch Order`
				GROUP BY parent
			) sb_cnt ON sb_cnt.parent = sb.name
			WHERE sb.status = 'Completed'
			GROUP BY sbo.laundry_order
		) sb_agg ON sb_agg.laundry_order = lo.name
		{where}
		ORDER BY lo.order_date DESC
	""", values, as_dict=True)

	return columns, data
