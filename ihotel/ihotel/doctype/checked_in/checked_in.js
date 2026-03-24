// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Checked In", {
	onload: function(frm) {
		setup_room_query(frm);
		setup_rate_type_query(frm);
	},

	refresh(frm) {
		// Pre-populate rate_type cache so tax calculates correctly on load
		if (!frm.is_new() && frm.doc.rate_type && !frm._rate_cache) {
			frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
				frm._rate_cache = rate;
				frm.trigger("calculate_total");
			});
		}

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
		if (frm.doc.room_type) {
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

	room_rate(frm)      { frm.trigger("calculate_total"); },
	discount(frm)       { frm.trigger("calculate_total"); },
	other_charges(frm)  { frm.trigger("calculate_total"); },
	tax(frm)            { frm.trigger("calculate_total"); },

	adults(frm)        { apply_cached_rate(frm); },
	children(frm)      { apply_cached_rate(frm); },
	rate_room_type(frm){ apply_cached_rate(frm); },

	// Calculate check-out from nights (user typed nights directly)
	nights(frm) {
		if (frm.doc.nights && frm.doc.nights > 0 && frm.doc.expected_check_in) {
			const check_in  = frappe.datetime.str_to_obj(frm.doc.expected_check_in);
			const check_out = new Date(check_in);
			check_out.setDate(check_out.getDate() + frm.doc.nights);
			frm.doc.expected_check_out = frappe.datetime.obj_to_str(check_out);
			frm.refresh_field("expected_check_out");
			frm.trigger("calculate_total");
		}
	},

	rate_type(frm) {
		if (!frm.doc.rate_type) {
			frm.set_intro("");
			frm._rate_cache = null;
			return;
		}
		frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
			// Cache the rate doc so adults/children/rate_room_type can use it directly
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
		frm.trigger("calculate_total");
		});
	},

	rate_lines_remove(frm) {
		frm.trigger("calculate_total");
	},

	color(frm) {
		if (frm.doc.color) {
			frm.page.set_indicator(frm.doc.status || "", frm.doc.color);
		}
	},

	calculate_total(frm) {
		if (frm.doc.expected_check_in && frm.doc.expected_check_out) {
			const nights = frappe.datetime.get_day_diff(
				frm.doc.expected_check_out,
				frm.doc.expected_check_in
			);
			if (nights > 0) {
				// Set directly to avoid re-triggering the nights event
				frm.doc.nights = nights;
				frm.refresh_field("nights");
			}
		}

		const nights        = frm.doc.nights || 0;
		const room_subtotal = flt((frm.doc.room_rate || 0) * nights, 2);

		// Additional Rate Charges = sum of rate_lines amounts (after row discounts)
		const additional = flt((frm.doc.rate_lines || []).reduce((s, r) => s + (r.amount || 0), 0), 2);
		frm.set_value("total_rent", additional);

		const other        = frm.doc.other_charges || 0;
		const svc_total    = frm.doc.additional_services_total || 0;
		const discount_pct = frm.doc.discount || 0;
		const subtotal     = room_subtotal + additional + svc_total + other;
		const discount_amt = flt(subtotal * discount_pct / 100, 2);
		const total_charges = flt(subtotal - discount_amt, 2);
		frm.set_value("total_charges", total_charges);

		// Tax: auto-compute from Rate Type's tax_schedule applied to pre-tax subtotal
		let tax = frm.doc.tax || 0;
		if (frm._rate_cache && (frm._rate_cache.tax_schedule || []).length) {
			tax = ci_compute_tax_from_schedule(frm._rate_cache.tax_schedule, total_charges);
			frm.set_value("tax", tax);
		}

		frm.set_value("total_amount", flt(total_charges + tax, 2));
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
	frm.trigger("calculate_total");
}

frappe.ui.form.on("Stay Rate Line", {
	rate_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	room_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	rate_column(frm, cdt, cdn){ fetch_rate_line(frm, cdt, cdn); },
	discount1(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	discount2(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	discount3(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	amount(frm, cdt, cdn)     { frm.trigger("calculate_total"); },
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
		frappe.model.set_value(cdt, cdn, "rate", resolved).then(() => {
			ci_apply_line_discounts(frm, cdt, cdn);
		});
	});
}

// Apply cascading discounts to a rate line and update its amount
function ci_apply_line_discounts(frm, cdt, cdn) {
	const row  = locals[cdt][cdn];
	const rate = row.rate || 0;
	const d1   = row.discount1 || 0;
	const d2   = row.discount2 || 0;
	const d3   = row.discount3 || 0;
	const amount = flt(rate * (1 - d1 / 100) * (1 - d2 / 100) * (1 - d3 / 100), 2);
	frappe.model.set_value(cdt, cdn, "amount", amount).then(() => {
		frm.trigger("calculate_total");
	});
}

// Compute total tax from a Rate Type's tax_schedule rows against a net total
function ci_compute_tax_from_schedule(tax_schedule, net_total) {
	let total_tax   = 0;
	let row_amounts = [];

	for (let row of (tax_schedule || [])) {
		const charge_type = row.charge_type || "On Net Total";
		const rate        = row.rate || 0;
		let   amount      = 0;

		if (charge_type === "On Net Total") {
			amount = net_total * rate / 100;
		} else if (charge_type === "Actual") {
			amount = rate;
		} else if (charge_type === "On Previous Row Amount") {
			const idx = parseInt(row.row_id || 1) - 1;
			amount = (row_amounts[idx] || 0) * rate / 100;
		} else if (charge_type === "On Previous Row Total") {
			const idx        = parseInt(row.row_id || 1) - 1;
			const prev_total = net_total + row_amounts.slice(0, idx + 1).reduce((a, b) => a + b, 0);
			amount = prev_total * rate / 100;
		}

		row_amounts.push(amount);
		total_tax += amount;
	}
	return flt(total_tax, 2);
}

// Uses the cached rate doc (set when rate_type is selected) to immediately
// recalculate room_rate from current adults/children/rate_room_type values.
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
	frm.set_value("room_rate", resolved);
	frm.trigger("calculate_total");
}

// Returns the rate from the best-matching Rate Schedule row, applying
// double_rate when adults > 1 and adding extra_child * children.
// Match priority: preferred_rt (rate_room_type) → fallback_rt (room_type) → generic → base_rate
function resolve_schedule_rate(rate_doc, preferred_rt, fallback_rt, today, adults, children) {
	const schedule = rate_doc.rate_schedule || [];
	const in_range = (row) =>
		(!row.from_date || row.from_date <= today) &&
		(!row.to_date   || row.to_date   >= today);

	let matched = (preferred_rt && schedule.find(r => r.room_type === preferred_rt && in_range(r)))
		|| (fallback_rt  && schedule.find(r => r.room_type === fallback_rt  && in_range(r)))
		|| schedule.find(r => !r.room_type && in_range(r));

	if (!matched) return rate_doc.base_rate || 0;

	const base = (adults > 1 && matched.double_rate) ? matched.double_rate : (matched.rate || rate_doc.base_rate || 0);
	const child_supplement = (children > 0 && matched.extra_child) ? matched.extra_child * children : 0;
	return base + child_supplement;
}
