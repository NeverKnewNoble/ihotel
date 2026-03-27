// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Housekeeping Task", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Pending") {
			frm.add_custom_button(__("Start Cleaning"), function () {
				frm.set_value("status", "In Progress");
				frm.set_value("assigned_date", frappe.datetime.now_datetime());
				frm.save();
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "In Progress") {
			frm.add_custom_button(__("Mark Completed"), function () {
				frm.set_value("status", "Completed");
				frm.set_value("cleaned_date", frappe.datetime.now_datetime());
				frm.save();
			}).addClass("btn-primary");
		}
	},
});
