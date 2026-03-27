// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Supplier", {
	refresh(frm) {
		if (!frm.is_new() && !frm.doc.is_active) {
			frm.set_intro(__("This supplier is inactive."), "yellow");
		}
	},
});
