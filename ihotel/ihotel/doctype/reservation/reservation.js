// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reservation", {
	refresh(frm) {
		// Restrict date pickers to today or later for new documents
		if (frm.is_new()) {
			frm.set_df_property("check_in_date",  "options", { minDate: frappe.datetime.get_today() });
			frm.set_df_property("check_out_date", "options", { minDate: frappe.datetime.get_today() });
		}

		// Room filter by room_type, excluding permanently unavailable rooms
		frm.set_query("room", function () {
			let filters = { status: ["not in", ["Out of Order", "Out of Service"]] };
			if (frm.doc.room_type) filters["room_type"] = frm.doc.room_type;
			return { filters };
		});

		// Convert to Check In button
		if (!frm.is_new() && frm.doc.status !== "cancelled" && !frm.doc.hotel_stay) {
			frm.add_custom_button(__("Convert to Checked In"), function () {
				frappe.call({
					method: "ihotel.ihotel.doctype.reservation.reservation.convert_to_hotel_stay",
					args: { reservation_name: frm.doc.name },
					callback(r) {
						if (r.message) frm.reload_doc();
					},
				});
			}, __("Actions"));
		}

		// Cancel button
		if (!frm.is_new() && frm.doc.status !== "cancelled") {
			frm.add_custom_button(__("Cancel Reservation"), function () {
				frappe.confirm(
					__("Are you sure you want to cancel this reservation?"),
					function () {
						frm.set_value("status", "cancelled");
						frm.save();
					}
				);
			}, __("Actions"));
		}

		// Confirm button
		if (!frm.is_new() && frm.doc.status === "pending") {
			frm.add_custom_button(__("Confirm"), function () {
				frm.set_value("status", "confirmed");
				frm.save();
			}, __("Actions"));
		}

		// Intro: linked Check In
		if (frm.doc.hotel_stay) {
			frm.set_intro(
				__("Converted to Checked In: {0}", [
					`<a href="/app/checked-in/${frm.doc.hotel_stay}">${frm.doc.hotel_stay}</a>`
				]),
				"green"
			);
		}

		// Intro: cancellation number
		if (frm.doc.status === "cancelled" && frm.doc.cancellation_number) {
			frm.set_intro(
				__("Cancelled — Cancellation No: {0}", [frm.doc.cancellation_number]),
				"red"
			);
		}
	},

	// When guest profile is selected, auto-fill contact details
	guest(frm) {
		if (frm.doc.guest) {
			frappe.db.get_doc("Guest", frm.doc.guest).then((g) => {
				if (!frm.doc.full_name)      frm.set_value("full_name", g.guest_name);
				if (!frm.doc.email_address)  frm.set_value("email_address", g.email);
				if (!frm.doc.phone_number)   frm.set_value("phone_number", g.phone);
				if (!frm.doc.date_of_birth)  frm.set_value("date_of_birth", g.date_of_birth);
				if (!frm.doc.country && g.nationality) frm.set_value("company", g.loyalty_tier);
			});
		}
	},

	room_type(frm) {
		if (frm.doc.room_type) {
			frappe.db.get_value("Room Type", frm.doc.room_type, "rack_rate").then((r) => {
				if (r.message && r.message.rack_rate) {
					frm.set_value("rent", r.message.rack_rate);
				}
			});

			// Clear room if it doesn't match the new room_type
			if (frm.doc.room) {
				frappe.db.get_value("Room", frm.doc.room, "room_type").then((r) => {
					if (r.message && r.message.room_type !== frm.doc.room_type) {
						frm.set_value("room", "");
					}
				});
			}
		}
	},

	check_in_date(frm) { frm.trigger("calculate_days"); },
	check_out_date(frm) { frm.trigger("calculate_days"); },
	rent(frm)          { frm.trigger("calculate_days"); },
	tax(frm)           { frm.trigger("calculate_totals"); },
	discount(frm)      { frm.trigger("calculate_totals"); },
	other_charges(frm) { frm.trigger("calculate_totals"); },

	calculate_days(frm) {
		if (frm.doc.check_in_date && frm.doc.check_out_date) {
			let days = frappe.datetime.get_day_diff(frm.doc.check_out_date, frm.doc.check_in_date);
			if (days > 0) {
				frm.set_value("days", days);
				frm.set_value("total_rent", days * (frm.doc.rent || 0));
				frm.trigger("calculate_totals");
			}
		}
	},

	calculate_totals(frm) {
		let total_rent = frm.doc.total_rent || 0;
		let tax        = frm.doc.tax        || 0;
		let discount   = frm.doc.discount   || 0;
		let other      = frm.doc.other_charges || 0;
		frm.set_value("total_rental",  total_rent + tax);
		frm.set_value("total_charges", total_rent + tax + other - discount);
	},

	color(frm) {
		// Live-preview the color indicator in the form header
		if (frm.doc.color) {
			frm.page.set_indicator(frm.doc.status || "", frm.doc.color);
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
				frm.set_value("rent", resolved_rate);
			}
		});
	},
});
