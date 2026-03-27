# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class SupplierBatch(Document):
	def before_save(self):
		self._recalc_totals()

	def _recalc_totals(self):
		total_items = 0
		total_value = 0.0
		for row in self.orders:
			if row.laundry_order:
				order = frappe.get_doc("Laundry Order", row.laundry_order)
				row.items_count = sum(item.quantity for item in order.items)
				row.order_value = flt(order.total_amount)
				row.status = order.status
				total_items += row.items_count
				total_value += row.order_value
		self.total_items = total_items
		self.total_value = total_value
