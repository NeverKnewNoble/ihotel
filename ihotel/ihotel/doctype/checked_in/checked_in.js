// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Checked In", {
	onload: function(frm) {
		setup_room_query(frm);
		setup_rate_type_query(frm);
	},

	refresh(frm) {
		setup_room_query(frm);
		setup_rate_type_query(frm);

		// Restrict date pickers to today or later unless allow_past_dates is enabled
		if (frm.is_new()) {
			frappe.db.get_single_value("iHotel Settings", "allow_past_dates").then(allow => {
				if (!allow) {
					const today = frappe.datetime.get_today();
					frm.set_df_property("expected_check_in",  "options", { minDate: today });
					frm.set_df_property("expected_check_out", "options", { minDate: today });
				}
			});
		}

		// Folio button (only on submitted docs)
		if (frm.doc.docstatus === 1) {
			if (frm.doc.profile) {
				frm.add_custom_button(__("Open Folio"), function() {
					frappe.set_route("Form", "iHotel Profile", frm.doc.profile);
				}, __("Billing"));
			} else {
				frm.add_custom_button(__("Create Folio"), function() {
					frappe.call({
						method: "ihotel.ihotel.doctype.checked_in.checked_in.create_folio",
						args: { checked_in_name: frm.doc.name },
						callback(r) {
							if (r.message) {
								frm.reload_doc();
								frappe.set_route("Form", "iHotel Profile", r.message);
							}
						},
					});
				}, __("Billing"));
			}
		}

		// Add custom buttons based on status
		if (frm.doc.status === "Reserved" && !frm.is_new()) {
			frm.add_custom_button(__("Checked In"), function() {
				frm.set_value("status", "Checked In");
				frm.set_value("actual_check_in", frappe.datetime.now_datetime());
				frm.save();
			}).addClass("btn-primary");

			frm.add_custom_button(__("No Show"), function() {
				frappe.confirm(
					__("Mark this reservation as No Show? This will free the room."),
					function() {
						frm.set_value("status", "No Show");
						frm.save();
					}
				);
			});
		}

		if (frm.doc.status === "Checked In" && !frm.is_new()) {
			// DND toggle
			frm.add_custom_button(
				frm.doc.do_not_disturb ? __("Clear DND") : __("Set DND"),
				function() {
					frm.set_value("do_not_disturb", frm.doc.do_not_disturb ? 0 : 1);
					frm.save();
				}, __("Guest Services")
			);

			// MUR toggle
			frm.add_custom_button(
				frm.doc.make_up_room ? __("Clear Make Up Room") : __("Make Up Room"),
				function() {
					frm.set_value("make_up_room", frm.doc.make_up_room ? 0 : 1);
					frm.save();
				}, __("Guest Services")
			);

			// Turndown toggle
			frm.add_custom_button(
				frm.doc.turndown_requested ? __("Cancel Turndown") : __("Request Turndown"),
				function() {
					frm.set_value("turndown_requested", frm.doc.turndown_requested ? 0 : 1);
					frm.save();
				}, __("Guest Services")
			);

			frm.add_custom_button(__("Check Out"), function() {
				const do_checkout = () => {
					frm.set_value("status", "Checked Out");
					frm.set_value("actual_check_out", frappe.datetime.now_datetime());
					frm.save();
				};
				if (frm.doc.profile) {
					frappe.db.get_value("iHotel Profile", frm.doc.profile,
						["outstanding_balance"])
					.then(r => {
						const bal = r.message && parseFloat(r.message.outstanding_balance || 0);
						if (bal > 0) {
							frappe.confirm(
								__("Folio has an outstanding balance of {0}. Check out anyway?",
									[format_currency(bal)]),
								do_checkout
							);
						} else {
							do_checkout();
						}
					});
				} else {
					do_checkout();
				}
			});

			frm.add_custom_button(__("Extend Stay"), function() {
			const d = new frappe.ui.Dialog({
				title: __("Extend Stay"),
				fields: [
					{
						fieldtype: "Data",
						fieldname: "current_checkout",
						label: __("Current Checkout"),
						default: frm.doc.expected_check_out || __("(none)"),
						read_only: 1,
					},
					{
						fieldtype: "Datetime",
						fieldname: "new_checkout",
						label: __("New Checkout Date/Time"),
						reqd: 1,
					},
					{
						fieldtype: "Small Text",
						fieldname: "reason",
						label: __("Reason (optional)"),
					},
				],
				primary_action_label: __("Extend"),
				primary_action(values) {
					frappe.call({
						method: "ihotel.ihotel.doctype.checked_in.checked_in.extend_stay",
						args: {
							checked_in_name: frm.doc.name,
							new_checkout: values.new_checkout,
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

		frm.add_custom_button(__("Room Move"), function() {
				const d = new frappe.ui.Dialog({
					title: __("Move Guest to Another Room"),
					fields: [
						{
							fieldtype: "Data",
							fieldname: "current_room",
							label: __("Current Room"),
							default: frm.doc.room || __("(none)"),
							read_only: 1,
						},
						{
							fieldtype: "Link",
							fieldname: "new_room",
							label: __("Move to Room"),
							options: "Room",
							reqd: 1,
							get_query: function () {
								return { filters: { status: "Available" } };
							},
						},
						{
							fieldtype: "Small Text",
							fieldname: "reason",
							label: __("Reason (optional)"),
						},
					],
					primary_action_label: __("Confirm Move"),
					primary_action(values) {
						frappe.call({
							method: "ihotel.ihotel.doctype.checked_in.checked_in.move_room",
							args: {
								checked_in_name: frm.doc.name,
								new_room: values.new_room,
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
	},

	// Auto-fetch room rate from room type and update room query filter
	room_type(frm) {
		// Fetch room rate from room type
		if (frm.doc.room_type) {
			frappe.db.get_value("Room Type", frm.doc.room_type, "rack_rate")
				.then(r => {
					if (r.message && r.message.rack_rate) {
						frm.set_value("room_rate", r.message.rack_rate);
						frm.trigger("calculate_total");
					}
				});
		}

		setup_room_query(frm);
		setup_rate_type_query(frm);

		// Clear rate_type if it no longer matches the new room_type
		if (frm.doc.rate_type && frm.doc.room_type) {
			frappe.db.get_value("Rate Type", frm.doc.rate_type, ["applicable_to", "room_type"])
				.then(r => {
					const rt = r.message;
					if (rt && rt.applicable_to === "Room Type" && rt.room_type !== frm.doc.room_type) {
						frm.set_value("rate_type", "");
					}
				});
		}

		// Clear room field if current room doesn't match the new room_type
		if (frm.doc.room && frm.doc.room_type) {
			frappe.db.get_value("Room", frm.doc.room, "room_type")
				.then(r => {
					if (r.message && r.message.room_type !== frm.doc.room_type) {
						frm.set_value("room", "");
					}
				});
		} else if (!frm.doc.room_type) {
			// Clear room if room_type is cleared
			frm.set_value("room", "");
		}
	},

	// Calculate total when dates or rate change
	expected_check_in(frm) {
		frm.trigger("calculate_total");
		// Update room query when dates change
		frm.trigger("room_type");
	},

	expected_check_out(frm) {
		frm.trigger("calculate_total");
		// Update room query when dates change
		frm.trigger("room_type");
	},

	room_rate(frm) {
		frm.trigger("calculate_total");
	},

	discount(frm) {
		frm.trigger("calculate_total");
	},

	// Calculate check-out from nights (user typed nights directly)
	nights(frm) {
		if (frm.doc.nights && frm.doc.nights > 0 && frm.doc.expected_check_in) {
			const check_in = frappe.datetime.str_to_obj(frm.doc.expected_check_in);
			const check_out = new Date(check_in);
			check_out.setDate(check_out.getDate() + frm.doc.nights);
			// Use doc + refresh to avoid re-triggering expected_check_out event
			frm.doc.expected_check_out = frappe.datetime.obj_to_str(check_out);
			frm.refresh_field("expected_check_out");
			if (frm.doc.room_rate) {
				const svcTotal = frm.doc.additional_services_total || 0;
				const discount = frm.doc.discount || 0;
				frm.doc.total_amount = Math.max(0,
					(frm.doc.nights * frm.doc.room_rate) + svcTotal - discount
				);
				frm.refresh_field("total_amount");
			}
		}
	},

	rate_type(frm) {
		if (!frm.doc.rate_type) {
			frm.set_intro("");
			return;
		}
		frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
			// --- indicators ---
			let indicators = [];
			if (rate.includes_breakfast) indicators.push("Breakfast included");
			if (rate.refundable)         indicators.push("Refundable");
			if (rate.includes_taxes)     indicators.push("Taxes included");
			frm.set_intro(indicators.length ? indicators.join(" | ") : "", "blue");

			// --- rate autofill ---
			let resolved_rate = null;
			const today = frappe.datetime.get_today();
			const room_type = frm.doc.room_type || "";

			if (rate.rate_schedule && rate.rate_schedule.length) {
				// Find the best matching schedule row
				for (const row of rate.rate_schedule) {
					const type_match = !row.room_type || row.room_type === room_type;
					const in_range   = (!row.from_date || row.from_date <= today) &&
					                   (!row.to_date   || row.to_date   >= today);
					if (type_match && in_range && row.rate) {
						resolved_rate = row.rate;
						break;
					}
				}
			}

			if (!resolved_rate && rate.base_rate) {
				resolved_rate = rate.base_rate;
			}

			if (resolved_rate) {
				frm.set_value("room_rate", resolved_rate);
				frm.trigger("calculate_total");
			}
		});
	},

	color(frm) {
		if (frm.doc.color) {
			frm.page.set_indicator(frm.doc.status || "", frm.doc.color);
		}
	},

	calculate_total(frm) {
		if (frm.doc.expected_check_in && frm.doc.expected_check_out && frm.doc.room_rate) {
			const nights = frappe.datetime.get_day_diff(
				frm.doc.expected_check_out,
				frm.doc.expected_check_in
			);
			if (nights > 0) {
				const svcTotal = frm.doc.additional_services_total || 0;
				const discount = frm.doc.discount || 0;
				frm.doc.nights = nights;
				frm.refresh_field("nights");
				frm.doc.total_amount = Math.max(0,
					(nights * frm.doc.room_rate) + svcTotal - discount
				);
				frm.refresh_field("total_amount");
			}
		}
	}
});

// Calculate amount for additional services (rate * quantity) and update parent total
frappe.ui.form.on("Stay Service Item", {
	rate(frm, cdt, cdn) {
		calculate_service_amount(frm, cdt, cdn);
	},
	quantity(frm, cdt, cdn) {
		calculate_service_amount(frm, cdt, cdn);
	},
	services_remove(frm) {
		recalc_services_total(frm);
	}
});

// Filter rate_type by room_type (All Rooms + Room Type-specific)
function setup_rate_type_query(frm) {
	frm.set_query("rate_type", function() {
		if (frm.doc.room_type) {
			return {
				query: "ihotel.ihotel.doctype.checked_in.checked_in.get_rate_types_for_room_type",
				filters: { room_type: frm.doc.room_type },
			};
		}
		return {};
	});
}

// Filter room by room_type using a server-side query
function setup_room_query(frm) {
	frm.set_query("room", function() {
		if (frm.doc.room_type) {
			return {
				query: "ihotel.ihotel.doctype.checked_in.checked_in.get_rooms_for_room_type",
				filters: { room_type: frm.doc.room_type },
			};
		}
		return {};
	});
}

function calculate_service_amount(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.rate !== undefined && row.quantity !== undefined) {
		const amount = (row.rate || 0) * (row.quantity || 0);
		frappe.model.set_value(cdt, cdn, "amount", amount).then(() => {
			recalc_services_total(frm);
		});
	}
}

function recalc_services_total(frm) {
	const rows = frm.doc.additional_services || [];
	const total = rows.reduce((sum, r) => sum + (r.amount || 0), 0);
	frm.doc.additional_services_total = Math.round(total * 100) / 100;
	frm.refresh_field("additional_services_total");
	frm.trigger("calculate_total");
}
