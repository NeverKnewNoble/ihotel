// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Item", {
	refresh(frm) {
		if (!frm.doc.is_active) {
			frm.set_intro(__("This item is inactive and will not appear on new orders."), "yellow");
		}
	},
});
