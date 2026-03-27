// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Room", {
	refresh(frm) {
		// Show current stay if room is occupied
		if (frm.doc.status === "Occupied") {
			frappe.db.get_value("Checked In", {
				"room": frm.doc.name,
				"status": ["in", ["Checked In", "Reserved"]],
				"docstatus": 1
			}, "name")
			.then(r => {
				if (r.message && r.message.name) {
					frm.add_custom_button(__("View Stay"), function() {
						frappe.set_route("Form", "Checked In", r.message.name);
					}).addClass("btn-primary");
				}
			});
		}
	},

	// Auto-update status based on room type selection
	room_type(frm) {
		if (frm.doc.room_type && !frm.doc.status) {
			frm.set_value("status", "Available");
		}
	}
});
