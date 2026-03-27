// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Housekeeping Assignment", {
	refresh(frm) {
		// Load Dirty Rooms button — always visible on unsaved/saved forms
		frm.add_custom_button(__("Load Dirty Rooms"), function () {
			frappe.call({
				method: "ihotel.ihotel.doctype.housekeeping_assignment.housekeeping_assignment.get_dirty_rooms",
				callback(r) {
					const dirty = r.message || [];
					if (!dirty.length) {
						frappe.show_alert({ message: __("No dirty rooms found."), indicator: "orange" });
						return;
					}

					// Avoid duplicates — collect rooms already in the table
					const existing = new Set((frm.doc.rooms || []).map(row => row.room));
					let added = 0;
					dirty.forEach(room => {
						if (!existing.has(room.name)) {
							const row = frappe.model.add_child(frm.doc, "Assignment Room", "rooms");
							frappe.model.set_value(row.doctype, row.name, "room", room.name);
							added++;
						}
					});

					frm.refresh_field("rooms");
					frappe.show_alert({
						message: added
							? __("{0} dirty room(s) loaded.", [added])
							: __("All dirty rooms already added."),
						indicator: added ? "green" : "blue",
					});
				},
			});
		}, __("Actions"));

		if (!frm.is_new()) {
			// Send Notification button
			const notif_label = frm.doc.notification_sent
				? __("Resend Notification")
				: __("Send Notification");

			frm.add_custom_button(notif_label, function () {
				frappe.confirm(
					__("Send assignment notification to {0}?", [frm.doc.housekeeper]),
					function () {
						frappe.call({
							method: "ihotel.ihotel.doctype.housekeeping_assignment.housekeeping_assignment.send_notification",
							args: { assignment_name: frm.doc.name },
							callback() {
								frappe.show_alert({ message: __("Notification sent."), indicator: "green" });
								frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Color all action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary")
			.addClass("btn-primary");
	},
});
