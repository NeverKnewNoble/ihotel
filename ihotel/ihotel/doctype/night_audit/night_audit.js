// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Night Audit", {
	refresh(frm) {
		// Calculate metrics on form load (for new and existing forms)
		if (frm.doc.audit_date) {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
				}
			});
		}

		// Add button to refresh/calculate metrics
		frm.add_custom_button(__("Refresh Metrics"), function() {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
					frappe.show_alert({
						message: __("Metrics refreshed successfully"),
						indicator: "green"
					});
				}
			});
		}).addClass("btn-primary");
	},

	audit_date(frm) {
		// Recalculate metrics when audit date changes
		if (frm.doc.audit_date) {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
				}
			});
		}
	}
});
