# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class LaundryOrder(Document):
	def validate(self):
		self._calculate_totals()
		self._set_expected_delivery()

	def _calculate_totals(self):
		total = 0.0
		for item in self.items:
			# Auto-fetch rate from Laundry Item if not set
			if item.laundry_item and not flt(item.rate):
				li = frappe.get_doc("Laundry Item", item.laundry_item)
				if self.customer_type == "Guest":
					item.rate = flt(li.guest_price)
				else:
					item.rate = flt(li.outsider_price)
			item.amount = flt(item.rate) * int(item.quantity or 1)
			total += item.amount
		# Apply service type surcharge
		surcharge = 0.0
		if self.service_type:
			st = frappe.get_doc("Laundry Service Type", self.service_type)
			surcharge = flt(st.surcharge_percentage) / 100.0
		self.total_amount = total * (1 + surcharge)
		self.outstanding_amount = flt(self.total_amount) - flt(self.paid_amount)

	def _set_expected_delivery(self):
		if self.service_type and self.order_date and not self.expected_delivery:
			from frappe.utils import add_to_date
			st = frappe.get_doc("Laundry Service Type", self.service_type)
			if st.lead_time_hours:
				self.expected_delivery = add_to_date(
					self.order_date,
					hours=flt(st.lead_time_hours)
				)

	def on_submit(self):
		if self.status == "Draft":
			self.db_set("status", "Collected")
		self._post_to_folio()
		settings = frappe.get_single("Laundry Settings")
		if settings.auto_create_sales_invoice and self.status == "Delivered":
			self._create_sales_invoice()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def _post_to_folio(self):
		if not self.post_to_folio or not self.ihotel_profile:
			return
		if flt(self.total_amount) <= 0:
			return
		profile = frappe.get_doc("iHotel Profile", self.ihotel_profile)
		profile.append("charges", {
			"date": self.order_date or nowdate(),
			"description": _("Laundry — {0}").format(self.name),
			"quantity": 1,
			"rate": flt(self.total_amount),
			"amount": flt(self.total_amount),
		})
		profile.save(ignore_permissions=True)

	def _create_sales_invoice(self):
		settings = frappe.get_single("Laundry Settings")
		if not settings.default_income_account:
			frappe.msgprint(_("Set Default Income Account in Laundry Settings to auto-create invoices."))
			return
		si = frappe.new_doc("Sales Invoice")
		si.customer = self.customer or ""
		si.posting_date = nowdate()
		si.append("items", {
			"item_name": _("Laundry Services — {0}").format(self.name),
			"description": _("Laundry order {0}").format(self.name),
			"qty": 1,
			"rate": flt(self.total_amount),
			"income_account": settings.default_income_account,
		})
		si.insert(ignore_permissions=True)
		si.submit()
		self.db_set("sales_invoice", si.name)


@frappe.whitelist()
def create_supplier_batch(order_names):
	"""Create a Supplier Batch from a list of Laundry Order names."""
	import json
	if isinstance(order_names, str):
		order_names = json.loads(order_names)

	if not order_names:
		frappe.throw(_("No orders provided."))

	# Determine supplier from first order
	first = frappe.get_doc("Laundry Order", order_names[0])
	supplier = first.laundry_supplier
	if not supplier:
		frappe.throw(_("Order {0} has no Laundry Supplier set.").format(order_names[0]))

	batch = frappe.new_doc("Supplier Batch")
	batch.batch_date = nowdate()
	batch.supplier = supplier
	batch.status = "Pending Pickup"

	for name in order_names:
		order = frappe.get_doc("Laundry Order", name)
		if order.laundry_supplier != supplier:
			frappe.throw(_("All orders must share the same Laundry Supplier."))
		batch.append("orders", {"laundry_order": name})

	batch.insert(ignore_permissions=True)
	# Update each order status to Processing
	for name in order_names:
		frappe.db.set_value("Laundry Order", name, "status", "Processing")

	return batch.name


@frappe.whitelist()
def mark_delivered(order_name):
	"""Called from JS to set status to Delivered and post to folio."""
	order = frappe.get_doc("Laundry Order", order_name)
	order.db_set("status", "Delivered")
	order._post_to_folio()
	settings = frappe.get_single("Laundry Settings")
	if settings.auto_create_sales_invoice:
		order._create_sales_invoice()
	return "ok"
