// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Group Reservation", {
	refresh(frm) {
		// Status workflow buttons (draft only)
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			if (frm.doc.status === "Tentative") {
				frm.add_custom_button(__("Confirm Reservation"), function() {
					frm.set_value("status", "Confirmed");
					frm.save();
				}).addClass("btn-primary");
			}

			if (!["Cancelled"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Cancel"), function() {
					frappe.prompt(
						{ fieldtype: "Small Text", fieldname: "reason", label: __("Cancellation Reason"), reqd: 1 },
						function(values) {
							frm.set_value("status", "Cancelled");
							frm.set_value("cancellation_reason", values.reason);
							frm.save();
						},
						__("Cancel Group Reservation"), __("Confirm Cancellation")
					);
				}, __("Actions"));
			}
		}

		// Generate individual reservations (submitted docs, not cancelled)
		if (frm.doc.docstatus === 1 && !["Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Generate Reservations"), function() {
				frappe.confirm(
					__("This will create individual Reservation records for each room in this group. Continue?"),
					function() {
						frappe.call({
							method: "ihotel.ihotel.doctype.group_reservation.group_reservation.generate_reservations",
							args: { group_reservation_name: frm.doc.name },
							callback(r) {
								if (r.message && r.message.length) {
									frm.reload_doc();
								}
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		// Color all custom action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");

		// Show linked reservations count
		if (!frm.is_new()) {
			frappe.call({
				method: "frappe.client.get_count",
				args: {
					doctype: "Reservation",
					filters: { group_reservation: frm.doc.name },
				},
				callback(r) {
					if (r.message && r.message > 0) {
						frm.set_intro(
							__("{0} reservation(s) linked to this group. ", [r.message]) +
							`<a href="/app/reservation?group_reservation=${encodeURIComponent(frm.doc.name)}">View Reservations</a>`,
							"blue"
						);
					}
				},
			});
		}
	},

	check_in_date(frm) { frm.trigger("calculate"); },
	check_out_date(frm) { frm.trigger("calculate"); },
	no_of_rooms(frm) { frm.trigger("calculate"); },
	rate_per_night(frm) { frm.trigger("calculate"); },

	rate_type(frm) {
		if (!frm.doc.rate_type) return;
		frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
			if (rate.base_rate) {
				frm.set_value("rate_per_night", rate.base_rate);
			}
		});
	},

	calculate(frm) {
		const { check_in_date, check_out_date, no_of_rooms, rate_per_night } = frm.doc;
		if (check_in_date && check_out_date) {
			const nights = frappe.datetime.get_day_diff(check_out_date, check_in_date);
			if (nights > 0) {
				frm.doc.days = nights;
				frm.refresh_field("days");
				if (no_of_rooms && rate_per_night) {
					frm.doc.total_room_revenue = nights * (no_of_rooms || 0) * (rate_per_night || 0);
					frm.refresh_field("total_room_revenue");
				}
			}
		}
	},
});
