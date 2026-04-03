// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Supplier", {
	refresh(frm) {
		if (!frm.is_new() && !frm.doc.is_active) {
			frm.set_intro(__("This supplier is inactive."), "yellow");
		}
	},

	supplier(frm) {
		if (!frm.doc.supplier) {
			frm.set_value("contact_person", "");
			frm.set_value("phone", "");
			frm.set_value("email", "");
			return;
		}
		// Auto-fill supplier_name from ERPXpand Supplier
		frappe.db.get_value("Supplier", frm.doc.supplier, "supplier_name").then(r => {
			if (r.message && r.message.supplier_name && !frm.doc.supplier_name) {
				frm.set_value("supplier_name", r.message.supplier_name);
			}
		});
		// Auto-fill contact details from the primary Contact linked to this Supplier
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Contact",
				filters: [
					["Dynamic Link", "link_doctype", "=", "Supplier"],
					["Dynamic Link", "link_name", "=", frm.doc.supplier],
				],
				fields: ["name", "full_name", "mobile_no", "email_id"],
				limit: 1,
			},
			callback(r) {
				if (!r.message || !r.message.length) return;
				const c = r.message[0];
				if (c.full_name) frm.set_value("contact_person", c.full_name);
				if (c.mobile_no) frm.set_value("phone", c.mobile_no);
				if (c.email_id)  frm.set_value("email", c.email_id);
			},
		});
	},
});
