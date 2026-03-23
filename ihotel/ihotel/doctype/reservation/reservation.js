// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reservation", {
	refresh(frm) {
		// Restrict date pickers to today or later unless allow_past_dates is enabled
		if (frm.is_new()) {
			frappe.db.get_single_value("iHotel Settings", "allow_past_dates").then(allow => {
				if (!allow) {
					const today = frappe.datetime.get_today();
					frm.set_df_property("check_in_date",  "options", { minDate: today });
					frm.set_df_property("check_out_date", "options", { minDate: today });
				}
			});
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
				if (!frm.doc.country && g.nationality) frm.set_value("country", g.nationality);
			});
		}
	},

	room_type(frm) {
		if (frm.doc.room_type) {
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

	adults(frm)        { apply_cached_rate(frm); },
	children(frm)      { apply_cached_rate(frm); },
	rate_room_type(frm){ apply_cached_rate(frm); },

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
		let total_rent       = frm.doc.total_rent || 0;
		let tax              = frm.doc.tax        || 0;
		let discount         = frm.doc.discount   || 0;
		let other            = frm.doc.other_charges || 0;
		let rate_lines_total = (frm.doc.rate_lines || []).reduce((s, r) => s + (r.amount || 0), 0);
		frm.set_value("total_rental",  total_rent + tax);
		frm.set_value("total_charges", total_rent + tax + other + rate_lines_total - discount);
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
			frm._rate_cache = null;
			return;
		}
		frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
			frm._rate_cache = rate;

			// --- filter rate_room_type to room types present in this rate's schedule ---
			const sched_room_types = [...new Set(
				(rate.rate_schedule || []).map(r => r.room_type).filter(Boolean)
			)];
			if (sched_room_types.length) {
				frm.set_query("rate_room_type", () => ({
					filters: { name: ["in", sched_room_types] }
				}));
			}

			// --- indicators ---
			let indicators = [];
			if (rate.includes_breakfast) indicators.push("Breakfast included");
			if (rate.refundable)         indicators.push("Refundable");
			if (rate.includes_taxes)     indicators.push("Taxes included");
			frm.set_intro(indicators.length ? indicators.join(" | ") : "", "blue");

			apply_cached_rate(frm);
		});
	},

	rate_lines_remove(frm) {
		frm.trigger("calculate_totals");
	},
});

frappe.ui.form.on("Stay Rate Line", {
	rate_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	room_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	rate_column(frm, cdt, cdn){ fetch_rate_line(frm, cdt, cdn); },
	amount(frm, cdt, cdn)     { frm.trigger("calculate_totals"); },
});

// Maps the Rate Column label to its field name in Rate Schedule
const RATE_COLUMN_MAP = {
	"Single / Base Rate": "rate",
	"Double Rate":        "double_rate",
	"Triple Rate":        "triple_rate",
	"Quad Rate":          "quad_rate",
	"Extra Adult Charge": "extra_adult",
	"Extra Child Charge": "extra_child",
	"Bed Only Rate":      "bed_only_rate",
	"Weekday Rate":       "weekday_rate",
	"Weekend Rate":       "weekend_rate",
	"Day Use Rate":       "bed_and_day_use",
};

function fetch_rate_line(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.rate_type) return;
	frappe.db.get_doc("Rate Type", row.rate_type).then((rate_doc) => {
		const today = frappe.datetime.get_today();
		const desc  = rate_doc.rate_type_name || rate_doc.name;
		// Priority: row's own room_type → rate_room_type → room_type → generic
		const preferred = row.room_type || frm.doc.rate_room_type || "";
		const fallback  = frm.doc.room_type || "";
		let resolved = 0;

		const schedule = rate_doc.rate_schedule || [];
		const in_range = (s) =>
			(!s.from_date || s.from_date <= today) && (!s.to_date || s.to_date >= today);

		const matched = (preferred && schedule.find(s => s.room_type === preferred && in_range(s)))
			|| (fallback && schedule.find(s => s.room_type === fallback  && in_range(s)))
			|| schedule.find(s => !s.room_type && in_range(s));

		if (matched) {
			if (row.rate_column && RATE_COLUMN_MAP[row.rate_column]) {
				resolved = matched[RATE_COLUMN_MAP[row.rate_column]] || 0;
			} else {
				const adults = frm.doc.adults || 1;
				const children = frm.doc.children || 0;
				resolved = resolve_schedule_rate(rate_doc, preferred, fallback, today, adults, children);
			}
		} else {
			resolved = rate_doc.base_rate || 0;
		}

		frappe.model.set_value(cdt, cdn, "description", desc);
		frappe.model.set_value(cdt, cdn, "rate", resolved);
		frappe.model.set_value(cdt, cdn, "amount", resolved);
	});
}

function apply_cached_rate(frm) {
	if (!frm._rate_cache || !frm.doc.rate_type) return;
	const resolved = resolve_schedule_rate(
		frm._rate_cache,
		frm.doc.rate_room_type || "",
		frm.doc.room_type || "",
		frappe.datetime.get_today(),
		frm.doc.adults || 1,
		frm.doc.children || 0
	);
	frm.set_value("rent", resolved);
	frm.trigger("calculate_days");
}

// Returns the rate from the best-matching Rate Schedule row, applying
// double_rate when adults > 1 and adding extra_child * children.
// Match priority: preferred_rt (rate_room_type) → fallback_rt (room_type) → generic → base_rate
function resolve_schedule_rate(rate_doc, preferred_rt, fallback_rt, today, adults, children) {
	const schedule = rate_doc.rate_schedule || [];
	const in_range = (row) =>
		(!row.from_date || row.from_date <= today) &&
		(!row.to_date   || row.to_date   >= today);

	const matched = (preferred_rt && schedule.find(r => r.room_type === preferred_rt && in_range(r)))
		|| (fallback_rt  && schedule.find(r => r.room_type === fallback_rt  && in_range(r)))
		|| schedule.find(r => !r.room_type && in_range(r));

	if (!matched) return rate_doc.base_rate || 0;

	const base = (adults > 1 && matched.double_rate) ? matched.double_rate : (matched.rate || rate_doc.base_rate || 0);
	const child_supplement = (children > 0 && matched.extra_child) ? matched.extra_child * children : 0;
	return base + child_supplement;
}
