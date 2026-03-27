// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.listview_settings["Laundry Order"] = {
	get_indicator(doc) {
		const colour_map = {
			"Draft": "grey",
			"Collected": "blue",
			"Processing": "orange",
			"Quality Check": "yellow",
			"Ready": "green",
			"Delivered": "darkgreen",
			"Cancelled": "red",
		};
		return [__(doc.status), colour_map[doc.status] || "grey", "status,=," + doc.status];
	},

	onload(listview) {
		listview.page.add_menu_item(__("Create Supplier Batch"), function () {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select at least one Laundry Order to batch."));
				return;
			}

			// Validate all selected are Collected + Outsourced
			const invalid = selected.filter(
				o => o.status !== "Collected" || o.processing_mode !== "Outsourced"
			);
			if (invalid.length) {
				frappe.msgprint(
					__("{0} order(s) must be in <b>Collected</b> status and <b>Outsourced</b> mode.", [invalid.length])
				);
				return;
			}

			// Check all same supplier
			const suppliers = [...new Set(selected.map(o => o.laundry_supplier).filter(Boolean))];
			if (suppliers.length > 1) {
				frappe.msgprint(__("All selected orders must have the same Laundry Supplier."));
				return;
			}

			frappe.call({
				method: "ihotel.ihotel.doctype.laundry_order.laundry_order.create_supplier_batch",
				args: { order_names: selected.map(o => o.name) },
				callback(r) {
					if (r.message) {
						frappe.msgprint(
							__("Supplier Batch <b>{0}</b> created.", [r.message]),
							__("Success")
						);
						frappe.set_route("Form", "Supplier Batch", r.message);
					}
				},
			});
		});
	},
};
