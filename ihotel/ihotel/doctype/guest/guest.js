// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Guest", {
	refresh(frm) {
		// Restricted guest warning banner
		if (frm.doc.restricted) {
			frm.set_intro(
				__("⚠ Restricted Guest: {0}", [frm.doc.restriction_note || "No reason provided"]),
				"red"
			);
		}

		// VIP indicator
		if (frm.doc.vip_type) {
			frm.set_indicator_formatter &&
				frm.page.set_indicator(__(frm.doc.vip_type), "orange");
		}

		if (frm.is_new()) return;

		// View Stay History button
		frm.add_custom_button(__("Stay History"), function () {
			frappe.set_route("query-report", "Guest History", {
				guest: frm.doc.name,
			});
		}, __("View"));

		// New Reservation button
		frm.add_custom_button(__("New Checked In"), function () {
			frappe.new_doc("Checked In", { guest: frm.doc.name });
		}, __("View"));

		// Load stay statistics into the Stats tab
		frappe.call({
			method: "ihotel.ihotel.doctype.guest.guest.get_guest_stats",
			args: { guest_name: frm.doc.name },
			callback(r) {
				if (r.message) {
					const s = r.message;
					frm.set_value("total_stays",   s.total_stays   || 0);
					frm.set_value("total_nights",  s.total_nights  || 0);
					frm.set_value("total_revenue", s.total_revenue || 0);
					frm.set_value("last_stay_date", s.last_stay_date || null);
				}
			},
		});
	},
});
