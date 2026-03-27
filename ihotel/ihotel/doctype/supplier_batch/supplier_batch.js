// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier Batch", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh Totals"), function () {
				frm.save();
			}).addClass("btn-primary");
		}
	},
});
