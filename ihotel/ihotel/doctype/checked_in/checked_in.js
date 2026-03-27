// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Checked In", {
	onload(frm) {
		setup_room_query(frm);
	},

	refresh(frm) {
		setup_room_query(frm);

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

		// Status-based action buttons
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
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Checked In" && !frm.is_new()) {
			frm.add_custom_button(
				frm.doc.do_not_disturb ? __("Clear DND") : __("Set DND"),
				function() {
					frm.set_value("do_not_disturb", frm.doc.do_not_disturb ? 0 : 1);
					frm.save();
				}, __("Guest Services")
			);

			frm.add_custom_button(
				frm.doc.make_up_room ? __("Clear Make Up Room") : __("Make Up Room"),
				function() {
					frm.set_value("make_up_room", frm.doc.make_up_room ? 0 : 1);
					frm.save();
				}, __("Guest Services")
			);

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
				// Always fetch profile from DB — frm.doc.profile may be stale
				// if the folio was created after the form was last loaded
				frappe.db.get_value("Checked In", frm.doc.name, "profile").then(r => {
					const profile = r.message && r.message.profile;
					if (!profile) {
						do_checkout();
						return;
					}
					frappe.db.get_value("iHotel Profile", profile, "outstanding_balance").then(r2 => {
						const bal = parseFloat((r2.message && r2.message.outstanding_balance) || 0);
						if (bal > 0) {
							frappe.msgprint({
								title: __("Outstanding Balance"),
								message: __("Cannot check out {0}. Outstanding balance of {1} must be settled before checkout.",
									[frm.doc.guest, format_currency(bal)]),
								indicator: "red",
							});
						} else {
							do_checkout();
						}
					});
				});
			}).addClass("btn-danger");

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

		// Color all custom action buttons (skip any already marked danger)
		frm.page.custom_actions.find("button:not(.btn-danger)")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");
	},

	guest(frm) {
		if (frm.doc.guest) {
			show_guest_bad_traces_alert(frm.doc.guest);
		}
	},

	room_type(frm) {
		setup_room_query(frm);

		// Clear room if it no longer matches the new room_type
		if (frm.doc.room && frm.doc.room_type) {
			frappe.db.get_value("Room", frm.doc.room, "room_type").then(r => {
				if (r.message && r.message.room_type !== frm.doc.room_type) {
					frm.set_value("room", "");
				}
			});
		} else if (!frm.doc.room_type) {
			frm.set_value("room", "");
		}
	},

	expected_check_in(frm)  { frm.trigger("calculate_total"); },
	expected_check_out(frm) { frm.trigger("calculate_total"); },

	// User typed nights directly — calculate check-out date
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

	color(frm) {
		if (frm.doc.color) {
			frm.page.set_indicator(frm.doc.status || "", frm.doc.color);
		}
	},

	rate_lines_remove(frm) { frm.trigger("calculate_total"); },

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

		const rate_lines_total = flt(
			(frm.doc.rate_lines || []).reduce((s, r) => s + (r.amount || 0), 0), 2
		);
		const svc_total    = frm.doc.additional_services_total || 0;
		const total_charges = flt(rate_lines_total + svc_total, 2);
		frm.set_value("total_charges", total_charges);

		// Compute tax from first rate_line's Rate Type tax_schedule
		const primary = (frm.doc.rate_lines || []).find(r => r.rate_type);
		if (primary) {
			frappe.db.get_doc("Rate Type", primary.rate_type).then(rate_doc => {
				const tax_amt = compute_tax_from_schedule(rate_doc.tax_schedule || [], total_charges);
				frm.set_value("tax",          tax_amt);
				frm.set_value("total_amount", flt(total_charges + tax_amt, 2));
			});
		} else {
			frm.set_value("tax",          0);
			frm.set_value("total_amount", total_charges);
		}
	},
});

// ── Guest Traces alert ────────────────────────────────────────────────────────

function show_guest_bad_traces_alert(guest_name) {
	frappe.call({
		method: "ihotel.ihotel.doctype.guest.guest.get_guest_bad_traces",
		args: { guest_name },
		callback(r) {
			const traces = r.message || [];
			if (!traces.length) return;

			const rows = traces.map(t =>
				`<tr>
					<td style="padding:4px 8px;border:1px solid #e2e2e2">${frappe.utils.escape_html(t.category)}</td>
					<td style="padding:4px 8px;border:1px solid #e2e2e2">${t.date || ""}</td>
					<td style="padding:4px 8px;border:1px solid #e2e2e2">${frappe.utils.escape_html(t.description || "")}</td>
					<td style="padding:4px 8px;border:1px solid #e2e2e2">${frappe.utils.escape_html(t.recorded_by || "")}</td>
				</tr>`
			).join("");

			frappe.msgprint({
				title: __("⚠ Guest Has Bad History"),
				indicator: "red",
				message: `
					<p style="color:#e03e3e;font-weight:600;margin-bottom:8px">
						${__("This guest has {0} bad trace(s) on record:", [traces.length])}
					</p>
					<table style="width:100%;border-collapse:collapse;font-size:12px">
						<thead>
							<tr style="background:#fce8e8">
								<th style="padding:4px 8px;border:1px solid #e2e2e2;text-align:left">${__("Category")}</th>
								<th style="padding:4px 8px;border:1px solid #e2e2e2;text-align:left">${__("Date")}</th>
								<th style="padding:4px 8px;border:1px solid #e2e2e2;text-align:left">${__("Description")}</th>
								<th style="padding:4px 8px;border:1px solid #e2e2e2;text-align:left">${__("Recorded By")}</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
				`,
			});
		},
	});
}

// ── Stay Service Item events ──────────────────────────────────────────────────
frappe.ui.form.on("Stay Service Item", {
	rate(frm, cdt, cdn)     { calculate_service_amount(frm, cdt, cdn); },
	quantity(frm, cdt, cdn) { calculate_service_amount(frm, cdt, cdn); },
	services_remove(frm)    { frm.trigger("calculate_total"); },
});

// ── Stay Rate Line events ─────────────────────────────────────────────────────
frappe.ui.form.on("Stay Rate Line", {
	rate_type(frm, cdt, cdn) {
		if (frm._syncing_rate_type) return;
		const row = locals[cdt][cdn];
		const new_rt = row.rate_type;

		// Propagate rate_type to all other rows
		const others = (frm.doc.rate_lines || []).filter(r => r.name !== row.name && r.rate_type !== new_rt);
		if (others.length) {
			frm._syncing_rate_type = true;
			Promise.all(
				others.map(r => frappe.model.set_value("Stay Rate Line", r.name, "rate_type", new_rt))
			).then(() => {
				frm._syncing_rate_type = false;
				(frm.doc.rate_lines || []).forEach(r => fetch_rate_line(frm, "Stay Rate Line", r.name));
			});
		} else {
			fetch_rate_line(frm, cdt, cdn);
		}
	},
	room_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	rate_column(frm, cdt, cdn){ fetch_rate_line(frm, cdt, cdn); },
	discount1(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	discount2(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	discount3(frm, cdt, cdn)  { ci_apply_line_discounts(frm, cdt, cdn); },
	amount(frm)               { frm.trigger("calculate_total"); },
});

// ── Helpers ───────────────────────────────────────────────────────────────────

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
			frm.trigger("calculate_total");
		});
	}
}

function compute_tax_from_schedule(tax_schedule, net_total) {
	const amounts = [];
	for (const row of (tax_schedule || [])) {
		const ct   = row.charge_type || "On Net Total";
		const rate = row.rate || 0;
		let   amt  = 0;
		if (ct === "On Net Total") {
			amt = net_total * rate / 100;
		} else if (ct === "Actual") {
			amt = rate;
		} else if (ct === "On Previous Row Amount") {
			const idx = parseInt(row.row_id || 1) - 1;
			amt = (amounts[idx] || 0) * rate / 100;
		} else if (ct === "On Previous Row Total") {
			const idx = parseInt(row.row_id || 1) - 1;
			amt = (net_total + amounts.slice(0, idx + 1).reduce((a, b) => a + b, 0)) * rate / 100;
		}
		amounts.push(flt(amt, 2));
	}
	return flt(amounts.reduce((a, b) => a + b, 0), 2);
}

// Maps Rate Column label to its field name in Rate Schedule
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
		const today     = frappe.datetime.get_today();
		const desc      = rate_doc.rate_type_name || rate_doc.name;
		const preferred = row.room_type || frm.doc.room_type || "";
		const fallback  = frm.doc.room_type || "";

		const schedule = rate_doc.rate_schedule || [];
		const in_range = (s) =>
			(!s.from_date || s.from_date <= today) && (!s.to_date || s.to_date >= today);
		const matched = (preferred && schedule.find(s => s.room_type === preferred && in_range(s)))
			|| (fallback  && schedule.find(s => s.room_type === fallback  && in_range(s)))
			|| schedule.find(s => !s.room_type && in_range(s));

		let resolved = 0;
		if (matched) {
			if (row.rate_column && RATE_COLUMN_MAP[row.rate_column]) {
				resolved = matched[RATE_COLUMN_MAP[row.rate_column]] || 0;
			} else {
				resolved = resolve_schedule_rate(rate_doc, preferred, fallback, today,
					frm.doc.adults || 1, frm.doc.children || 0);
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

function ci_apply_line_discounts(frm, cdt, cdn) {
	const row    = locals[cdt][cdn];
	const rate   = row.rate || 0;
	const d1     = row.discount1 || 0;
	const d2     = row.discount2 || 0;
	const d3     = row.discount3 || 0;
	const amount = flt(rate * (1 - d1 / 100) * (1 - d2 / 100) * (1 - d3 / 100), 2);
	frappe.model.set_value(cdt, cdn, "amount", amount).then(() => {
		frm.trigger("calculate_total");
	});
}

function resolve_schedule_rate(rate_doc, preferred_rt, fallback_rt, today, adults, children) {
	const schedule = rate_doc.rate_schedule || [];
	const in_range = (row) =>
		(!row.from_date || row.from_date <= today) &&
		(!row.to_date   || row.to_date   >= today);

	const matched = (preferred_rt && schedule.find(r => r.room_type === preferred_rt && in_range(r)))
		|| (fallback_rt  && schedule.find(r => r.room_type === fallback_rt  && in_range(r)))
		|| schedule.find(r => !r.room_type && in_range(r));

	if (!matched) return rate_doc.base_rate || 0;

	const base = (adults > 1 && matched.double_rate)
		? matched.double_rate
		: (matched.rate || rate_doc.base_rate || 0);
	const child_supplement = (children > 0 && matched.extra_child)
		? matched.extra_child * children : 0;
	return base + child_supplement;
}
