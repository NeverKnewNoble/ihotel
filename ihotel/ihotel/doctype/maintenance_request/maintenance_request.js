// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Maintenance Request", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.reported_by) {
			frm.set_value("reported_by", frappe.session.user);
		}
	},

	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Open") {
			frm.add_custom_button(__("Mark In Progress"), function () {
				frm.set_value("status", "In Progress");
				frm.save();
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "In Progress") {
			frm.add_custom_button(__("Mark Resolved"), function () {
				frm.set_value("status", "Resolved");
				frm.save();
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Resolved") {
			frm.add_custom_button(__("Close"), function () {
				frm.set_value("status", "Closed");
				frm.save();
			}).addClass("btn-primary");
		}

		// Place Room OOO button — only when room is set and no OOO linked yet
		if (frm.doc.room && !frm.doc.linked_ooo && frm.doc.status !== "Resolved" && frm.doc.status !== "Closed") {
			frm.add_custom_button(__("Place Room OOO"), function () {
				const d = new frappe.ui.Dialog({
					title: __("Place Room Out of Order"),
					fields: [
						{
							fieldtype: "Data",
							fieldname: "room_display",
							label: __("Room"),
							default: frm.doc.room,
							read_only: 1,
						},
						{
							fieldtype: "Date",
							fieldname: "from_date",
							label: __("From Date"),
							default: frappe.datetime.get_today(),
							reqd: 1,
						},
						{
							fieldtype: "Date",
							fieldname: "to_date",
							label: __("To Date"),
							reqd: 1,
						},
						{
							fieldtype: "Small Text",
							fieldname: "reason",
							label: __("Reason"),
							default: frm.doc.description || "",
						},
					],
					primary_action_label: __("Create OOO"),
					primary_action(values) {
						frappe.call({
							method: "ihotel.ihotel.doctype.maintenance_request.maintenance_request.create_ooo_from_request",
							args: {
								maintenance_request_name: frm.doc.name,
								from_date: values.from_date,
								to_date: values.to_date,
								reason: values.reason || "",
							},
							callback(r) {
								if (r.message) {
									d.hide();
									frm.reload_doc();
								}
							},
						});
					},
				});
				d.show();
			}, __("Actions"));
		}

		// Show link to OOO record if linked
		if (frm.doc.linked_ooo) {
			frm.add_custom_button(__("View OOO Record"), function () {
				frappe.set_route("Form", "Room Out of Order", frm.doc.linked_ooo);
			}, __("Actions"));
		}

		// Show room history link
		if (frm.doc.room) {
			frm.add_custom_button(__("Room History"), function () {
				frappe.set_route("room-maintenance-history", { room: frm.doc.room });
			}, __("Actions"));
		}

		// Color all custom action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");
	},
});
