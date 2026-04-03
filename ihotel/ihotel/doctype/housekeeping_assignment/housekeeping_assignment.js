// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Housekeeping Assignment", {
	housekeeper(frm) {
		if (!frm.doc.housekeeper || !frm.doc.date) return;

		frappe.call({
			method: "ihotel.ihotel.doctype.housekeeping_assignment.housekeeping_assignment.check_housekeeper_roster",
			args: {
				housekeeper: frm.doc.housekeeper,
				date: frm.doc.date,
			},
			callback(r) {
				if (!r.message) return;
				const { checked, on_roster } = r.message;
				if (checked && !on_roster) {
					frappe.msgprint({
						title: __("Not On Roster"),
						message: __("{0} does not have an active shift assignment on {1} and cannot be assigned.", [frm.doc.housekeeper, frm.doc.date]),
						indicator: "red",
					});
					frm.set_value("housekeeper", "");
				}
			},
		});
	},

	date(frm) {
		// Re-validate roster if housekeeper already selected and date changes
		if (frm.doc.housekeeper) {
			frm.trigger("housekeeper");
		}
	},

	refresh(frm) {
		// Restrict room picker to dirty rooms only
		frm.set_query("room", "rooms", function () {
			return {
				filters: { status: ["in", ["Occupied Dirty", "Vacant Dirty"]] },
			};
		});

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

frappe.ui.form.on("Assignment Room", {
	room(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.room) return;
		frappe.db.get_value("Room", row.room, ["floor", "room_type"]).then(r => {
			if (!r.message) return;
			frappe.model.set_value(cdt, cdn, "floor", r.message.floor || "");
			frappe.model.set_value(cdt, cdn, "room_type", r.message.room_type || "");
		});
	},
});
