// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

const ADULTS_RATE_COLUMN_MAP = {
	1: "Single / Base Rate",
	2: "Double Rate",
	3: "Triple Rate",
	4: "Quad Rate",
};

// Debounce tracker: prevents duplicate housekeeping pings from rapid toggle actions.
// Maps "service_type" → timestamp of last outbound call.
const _hk_notify_last_sent = {};
const HK_CLIENT_DEBOUNCE_MS = 10000;  // 10 seconds between client-side duplicate calls

function notify_housekeeping_debounced(frm, service_type) {
	const now = Date.now();
	const last = _hk_notify_last_sent[service_type] || 0;
	if (now - last < HK_CLIENT_DEBOUNCE_MS) return;  // Still within debounce window
	_hk_notify_last_sent[service_type] = now;
	frappe.call({
		method: "ihotel.ihotel.doctype.checked_in.checked_in.notify_housekeeping",
		args: { checked_in_name: frm.doc.name, service_type },
	});
}

frappe.ui.form.on("Checked In", {
	onload(frm) {
		setup_room_query(frm);
	},

	refresh(frm) {
		setup_room_query(frm);
		ci_set_rate_line_room_type_default(frm);

		// Status indicator badge
		const STATUS_COLORS = {
			"Reserved":    "orange",
			"Checked In":  "blue",
			"Checked Out": "green",
			"No Show":     "grey",
			"Cancelled":   "red",
		};
		if (frm.doc.status) {
			frm.page.set_indicator(
				__(frm.doc.status),
				STATUS_COLORS[frm.doc.status] || "grey"
			);
		}

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

			// Show Retry Invoice Sync button when the ERP sync previously failed
			if (frm.doc.invoice_sync_status === "Failed" && !frm.doc.sales_invoice) {
				frm.add_custom_button(__("Retry Invoice Sync"), function() {
					frappe.call({
						method: "ihotel.ihotel.doctype.checked_in.checked_in.retry_sales_invoice_sync",
						args: { checked_in_name: frm.doc.name },
						callback(r) {
							frm.reload_doc();
							if (r.message === "Synced") {
								frappe.show_alert({ message: __("Invoice sync successful."), indicator: "green" });
							} else {
								frappe.show_alert({ message: __("Invoice sync failed again. Check Error Log."), indicator: "red" });
							}
						},
					});
				}, __("Billing")).addClass("btn-warning");
			}

			// No Post banner — warns staff that room charges are blocked on this stay
			if (frm.doc.no_post) {
				frm.dashboard.add_comment(
					__("No Post is active: room charges are blocked for this stay."),
					"orange",
					true
				);
			}

			// Show invoice sync failure alert on the form
			if (frm.doc.invoice_sync_status === "Failed") {
				let msg = __("ERP Invoice sync failed.");
				if (frm.doc.invoice_sync_error) msg += " " + frm.doc.invoice_sync_error;
				frm.dashboard.add_comment(msg, "red", true);
			}
		}

		// Status-based action buttons
		if (frm.doc.status === "Reserved" && !frm.is_new() && frm.doc.docstatus !== 1) {
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
					const turning_on = !frm.doc.do_not_disturb;
					frm.set_value("do_not_disturb", turning_on ? 1 : 0);
					frm.save().then(() => {
						if (turning_on) notify_housekeeping_debounced(frm, "Do Not Disturb");
					});
				}, __("Guest Services")
			);

			frm.add_custom_button(
				frm.doc.make_up_room ? __("Clear Make Up Room") : __("Make Up Room"),
				function() {
					const turning_on = !frm.doc.make_up_room;
					frm.set_value("make_up_room", turning_on ? 1 : 0);
					frm.save().then(() => {
						if (turning_on) notify_housekeeping_debounced(frm, "Make Up Room");
					});
				}, __("Guest Services")
			);

			frm.add_custom_button(
				frm.doc.turndown_requested ? __("Cancel Turndown") : __("Request Turndown"),
				function() {
					const turning_on = !frm.doc.turndown_requested;
					frm.set_value("turndown_requested", turning_on ? 1 : 0);
					frm.save().then(() => {
						if (turning_on) notify_housekeeping_debounced(frm, "Turndown");
					});
				}, __("Guest Services")
			);


			frm.add_custom_button(__("Check Out"), function() {
				const do_checkout = () => {
					frappe.call({
						method: "ihotel.ihotel.doctype.checked_in.checked_in.do_checkout",
						args: { checked_in_name: frm.doc.name },
						callback(r) {
							if (r.message) {
								frm.reload_doc();
							}
						},
					});
				};
				// Same rules as server: block if any night through yesterday has no Night Audit
				const check_night_audit_then_checkout = () => {
					frappe.call({
						method: "ihotel.ihotel.doctype.checked_in.checked_in.get_night_audit_checkout_blockers",
						args: { checked_in_name: frm.doc.name },
						callback(r) {
							const missing = (r.message && r.message.missing_dates) || [];
							if (missing.length) {
								frappe.msgprint({
									title: __("Night Audit Required"),
									message: __(
										"Cannot check out. Night Audit has not been posted for: {0}",
										[missing.join(", ")]
									),
									indicator: "red",
								});
								return;
							}
							do_checkout();
						},
					});
				};
				// Always fetch profile from DB — frm.doc.profile may be stale
				// if the folio was created after the form was last loaded
				frappe.db.get_value("Checked In", frm.doc.name, "profile").then(r => {
					const profile = r.message && r.message.profile;
					if (!profile) {
						check_night_audit_then_checkout();
						return;
					}
					frappe.db.get_value("iHotel Profile", profile, "outstanding_balance").then(r2 => {
						const bal = parseFloat((r2.message && r2.message.outstanding_balance) || 0);
						if (bal > 0) {
							const profile_url = `/app/ihotel-profile/${encodeURIComponent(profile)}`;
							const settle_link = `<a href="${profile_url}" style="text-decoration: underline;">${__("Please settle")}</a>`;
							frappe.msgprint({
								title: __("Outstanding Balance"),
								message: __("Cannot check out {0}. Outstanding balance of {1} must be settled before checkout.",
									[frm.doc.guest, format_currency(bal)])
									+ "<br>" + __("{0} the outstanding balance to proceed.", [settle_link]),
								indicator: "red",
							});
						} else {
							check_night_audit_then_checkout();
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
								return {
									filters: {
										status: ["in", ["Available", "Vacant Dirty"]],
									},
								};
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

		// Auto-insert one row if the table is empty and a room_type is now selected
		if (frm.doc.room_type && (!frm.doc.rate_lines || frm.doc.rate_lines.length === 0)) {
			const row = frm.add_child("rate_lines");
			frappe.model.set_value("Stay Rate Line", row.name, "room_type", frm.doc.room_type);
			const auto_col = ADULTS_RATE_COLUMN_MAP[frm.doc.adults];
			if (auto_col) frappe.model.set_value("Stay Rate Line", row.name, "rate_column", auto_col);
			frm.refresh_field("rate_lines");
		}

		// Set default so every new rate_lines row picks up this room_type automatically
		ci_set_rate_line_room_type_default(frm);

		// Also sync any already-existing rows
		(frm.doc.rate_lines || []).forEach(row => {
			frappe.model.set_value("Stay Rate Line", row.name, "room_type", frm.doc.room_type || "");
		});

		// Auto-pick a Rate Type that's pinned to this Room Type for any blank rows.
		auto_pick_rate_type_for_room_type(frm);
	},

	adults(frm) {
		const rate_column = ADULTS_RATE_COLUMN_MAP[frm.doc.adults];
		if (!rate_column) return;
		(frm.doc.rate_lines || []).forEach(row => {
			frappe.model.set_value("Stay Rate Line", row.name, "rate_column", rate_column);
		});
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

function ci_set_rate_line_room_type_default(frm) {
	const grid = frm.fields_dict.rate_lines && frm.fields_dict.rate_lines.grid;
	if (!grid) return;
	const df = (grid.docfields || []).find(f => f.fieldname === "room_type");
	if (df) df.default = frm.doc.room_type || "";
}

// Find the first Rate Type that's pinned to this room_type and assign it to any
// rate_lines row whose rate_type is empty. Skips rows that already have one so
// the user's manual override is never clobbered. The fetch_rate_line trigger on
// rate_type then resolves the per-night rate automatically.
function auto_pick_rate_type_for_room_type(frm) {
	if (!frm.doc.room_type) return;
	const blank_rows = (frm.doc.rate_lines || []).filter(r => !r.rate_type);
	if (!blank_rows.length) return;

	frappe.db.get_list("Rate Type", {
		filters: { applicable_to: "Room Type", room_type: frm.doc.room_type },
		fields: ["name"],
		limit: 1,
		order_by: "modified desc",
	}).then(rows => {
		if (!rows || !rows.length) return;
		const rate_type_name = rows[0].name;
		blank_rows.forEach(row => {
			frappe.model.set_value("Stay Rate Line", row.name, "rate_type", rate_type_name);
		});
	});
}

function setup_room_query(frm) {
	// Only show rooms that are bookable: Available or Vacant Dirty (housekeeping
	// will clean before the guest arrives). Prevents assigning a room that is
	// occupied or out of service.
	frm.set_query("room", function() {
		if (frm.doc.room_type) {
			return {
				query: "ihotel.ihotel.doctype.checked_in.checked_in.get_rooms_for_room_type",
				filters: { room_type: frm.doc.room_type },
			};
		}
		return {
			filters: { status: ["in", ["Available", "Vacant Dirty"]] },
		};
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
