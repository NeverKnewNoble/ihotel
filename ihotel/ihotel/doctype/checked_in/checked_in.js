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


			frm.add_custom_button(__("Take Payment"), function() {
				open_take_payment_dialog(frm, { also_checkout: false });
			}).addClass("btn-primary");

			frm.add_custom_button(__("Check Out"), function() {
				const do_checkout_now = () => {
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
							do_checkout_now();
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
							// Auto-open Take Payment dialog in "Save & Check Out" mode —
							// front desk can settle and leave in one submit.
							open_take_payment_dialog(frm, { also_checkout: true });
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

// ── Take Payment dialog ───────────────────────────────────────────────────────
//
// One dialog used by the "Take Payment" button (also_checkout=false) and by
// the "Check Out" button when outstanding > 0 (also_checkout=true). Captures
// payment rows and posts via the take_payment whitelisted API, which appends
// to the folio and syncs ERPXpand Payment Entries in one server round-trip.

function open_take_payment_dialog(frm, opts) {
	const also_checkout = !!(opts && opts.also_checkout);

	// Fetch the folio summary + base currency in parallel.
	const base_currency = frappe.defaults.get_global_default("currency")
		|| frappe.boot.sysdefaults.currency
		|| "USD";

	// Resolve the profile name, then fetch the full document (we need the
	// payments child table to render the "Previous Payments" section).
	const fetch_profile = frappe.db.get_value(
		"iHotel Profile",
		{ hotel_stay: frm.doc.name },
		["name"]
	).then(r => {
		const profile_name = r && r.message && r.message.name;
		if (!profile_name) return null;
		return frappe.db.get_doc("iHotel Profile", profile_name);
	});

	fetch_profile.then(profile_doc => {
		const p = profile_doc || {};
		const outstanding = parseFloat(p.outstanding_balance || 0);
		const total_charges = parseFloat(p.total_amount || 0);
		const total_paid = parseFloat(p.total_payments || 0);
		const past_payments = (p.payments || []).slice();

		// All folio totals are in base currency (company currency).
		const fmt = (v) => frappe.format(v, { fieldtype: "Currency", options: base_currency },
			{ only_value: true });

		// Card-style header: guest/room line, three big stat blocks, then a
		// live footer that updates as the user keys payment rows. Kept plain
		// CSS so it renders consistently in both light and dark desk themes.
		const summary_html = `
			<div class="tp-card" style="padding:6px 0 10px;">
				<div style="display:flex; align-items:baseline; justify-content:space-between; margin-bottom:10px;">
					<div>
						<div style="font-size:1.05em; font-weight:600;">${frappe.utils.escape_html(frm.doc.guest || "")}</div>
						<div class="text-muted" style="font-size:0.85em;">
							${__("Room")} ${frappe.utils.escape_html(frm.doc.room || "")}
							· ${frm.doc.nights || 0} ${__("night(s)")}
						</div>
					</div>
					<div class="text-muted" style="font-size:0.8em;">
						${__("Base Currency")}: <strong>${base_currency}</strong>
					</div>
				</div>
				<div class="tp-stats" style="display:grid; grid-template-columns:repeat(3, 1fr); gap:10px;">
					<div style="padding:10px 12px; background:var(--bg-light-gray, #f6f7f8); border-radius:6px;">
						<div class="text-muted" style="font-size:0.75em; text-transform:uppercase; letter-spacing:0.5px;">${__("Total Charges")}</div>
						<div style="font-size:1.1em; font-weight:600;">${fmt(total_charges)}</div>
					</div>
					<div style="padding:10px 12px; background:var(--bg-light-gray, #f6f7f8); border-radius:6px;">
						<div class="text-muted" style="font-size:0.75em; text-transform:uppercase; letter-spacing:0.5px;">${__("Total Paid")}</div>
						<div style="font-size:1.1em; font-weight:600;">${fmt(total_paid)}</div>
					</div>
					<div style="padding:10px 12px; border-radius:6px; background:${outstanding > 0 ? "#fdecea" : "#e9f8ee"}; color:${outstanding > 0 ? "#922" : "#1e7e34"};">
						<div style="font-size:0.75em; text-transform:uppercase; letter-spacing:0.5px; opacity:0.8;">${__("Outstanding")}</div>
						<div style="font-size:1.25em; font-weight:700;">${fmt(outstanding)}</div>
					</div>
				</div>
			</div>
		`;

		const today_str = frappe.datetime.get_today();

		// Render the history list when the folio already has payments.
		// Each row carries a Print button that reuses the exact receipt
		// template used by the iHotel Profile grid so receipts look
		// identical whether printed from the folio or from this dialog.
		const render_past_payments_html = () => {
			if (!past_payments.length) return "";
			const rows = past_payments.map((row, i) => {
				// Use format_currency (not frappe.format) so a literal
				// currency code like "USD" resolves to the right symbol
				// per-row. frappe.format's `options` expects a fieldname,
				// not a code, so all rows were falling back to GHS.
				const fmt_row = (v) => format_currency(
					v || 0, row.currency || base_currency
				);
				const date_str = frappe.datetime.str_to_user(row.date) || "";
				const pe_badge = row.payment_entry
					? `<span class="indicator green" title="${frappe.utils.escape_html(row.payment_entry)}">GL</span>`
					: `<span class="indicator gray" title="${__('Not yet posted to GL')}">—</span>`;
				return `
					<tr>
						<td>${frappe.utils.escape_html(date_str)}</td>
						<td>${frappe.utils.escape_html(row.payment_method || "")}</td>
						<td>${frappe.utils.escape_html(row.currency || base_currency)}</td>
						<td class="text-right">${fmt_row(row.rate)}</td>
						<td>${frappe.utils.escape_html(row.payment_status || "")}</td>
						<td>${pe_badge}</td>
						<td class="text-right">
							<button type="button" class="btn btn-xs btn-default tp-print-row"
							        data-idx="${i}" title="${__('Print receipt')}">
								${__("Print")}
							</button>
						</td>
					</tr>
				`;
			}).join("");
			return `
				<div style="margin-top:4px;">
					<div style="font-size:0.82em; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:6px;">
						${__("Previous Payments")}
					</div>
					<div class="table-responsive" style="border:1px solid var(--border-color, #e2e2e2); border-radius:6px;">
						<table class="table table-sm" style="margin:0; font-size:0.87em;">
							<thead style="background:var(--bg-light-gray, #f6f7f8);">
								<tr>
									<th>${__("Date")}</th>
									<th>${__("Method")}</th>
									<th>${__("Currency")}</th>
									<th class="text-right">${__("Amount")}</th>
									<th>${__("Status")}</th>
									<th>${__("GL")}</th>
									<th></th>
								</tr>
							</thead>
							<tbody>${rows}</tbody>
						</table>
					</div>
				</div>
			`;
		};

		const d = new frappe.ui.Dialog({
			title: also_checkout ? __("Settle & Check Out") : __("Take Payment"),
			size: "large",
			fields: [
				{ fieldtype: "HTML", fieldname: "summary", options: summary_html },
				{ fieldtype: "HTML", fieldname: "past_payments",
				  options: render_past_payments_html() },
				{ fieldtype: "Section Break", label: __("New Payment") },
				{
					fieldtype: "Table",
					fieldname: "payments",
					label: __("Payments"),
					cannot_add_rows: 0,
					in_place_edit: true,
					data: [{
						date: today_str,
						payment_method: "Cash",
						currency: base_currency,
						exchange_rate: 1,
						rate: outstanding > 0 ? outstanding : 0,
					}],
					fields: [
						{
							fieldtype: "Date", fieldname: "date",
							label: __("Date"), in_list_view: 1, reqd: 1, default: today_str,
							columns: 2,
						},
						{
							fieldtype: "Link", fieldname: "payment_method",
							label: __("Method"), in_list_view: 1, reqd: 1,
							options: "Mode of Payment", default: "Cash",
							columns: 2,
						},
						{
							fieldtype: "Link", fieldname: "currency",
							label: __("Currency"), in_list_view: 1, reqd: 1,
							options: "Currency", default: base_currency,
							columns: 2,
						},
						{
							fieldtype: "Float", fieldname: "exchange_rate",
							label: __("Rate to {0}", [base_currency]),
							in_list_view: 1, default: 1, precision: 6,
							columns: 2,
						},
						{
							fieldtype: "Currency", fieldname: "rate",
							label: __("Amount"), in_list_view: 1, reqd: 1,
							options: "currency",
							columns: 2,
						},
					],
				},
				{ fieldtype: "HTML", fieldname: "totals_footer", options: "" },
			],
		});

		// Cap validation + live totals. Sum is in base currency so multi-
		// currency rows (e.g. 100 GHS Cash + 200 USD Credit Card) are
		// comparable to the folio outstanding.
		const render_totals = () => {
			const rows = d.get_value("payments") || [];
			const total_base = rows.reduce((s, r) => {
				const amt = parseFloat(r.rate) || 0;
				const ex  = parseFloat(r.exchange_rate) || 1;
				return s + amt * ex;
			}, 0);
			const diff = outstanding - total_base;
			const over = -diff;
			const tol  = fx_tolerance();
			const $wrap = d.fields_dict.totals_footer.$wrapper;

			// Footer: always present. Red when over beyond the FX-rounding
			// tolerance, green when settling (including sub-cent FX slack),
			// grey when there's a real remaining amount.
			let status_color = "#555", status_bg = "var(--bg-light-gray, #f6f7f8)",
			    status_label = __("Remaining"), status_value = fmt(Math.max(diff, 0));
			if (outstanding > 0 && over > tol) {
				status_color = "#922"; status_bg = "#fdecea";
				status_label = __("Over");  status_value = fmt(over);
			} else if (outstanding > 0 && Math.abs(diff) <= tol) {
				status_color = "#1e7e34"; status_bg = "#e9f8ee";
				status_label = __("Settles");  status_value = fmt(outstanding);
			}
			$wrap.html(`
				<div style="display:flex; gap:10px; margin-top:4px; font-size:0.9em;">
					<div style="flex:1; padding:8px 12px; background:var(--bg-light-gray, #f6f7f8); border-radius:6px;">
						<span class="text-muted">${__("Payments total")}</span>
						<strong style="float:right;">${fmt(total_base)}</strong>
					</div>
					<div style="flex:1; padding:8px 12px; background:${status_bg}; color:${status_color}; border-radius:6px;">
						<span>${status_label}</span>
						<strong style="float:right;">${status_value}</strong>
					</div>
				</div>
			`);
		};

		// Given a row, compute the remaining outstanding absorbed by this row
		// (in the row's currency, using its exchange rate). Rounds to 2dp —
		// the tiny rounding delta (≤ 0.5 unit × ex_rate in base currency)
		// is tolerated downstream by `fx_tolerance` so the submit doesn't
		// block on sub-cent FX artifacts.
		const compute_row_fill = (rows, row_idx) => {
			const target = rows[row_idx];
			if (!target) return 0;
			const ex = parseFloat(target.exchange_rate) || 1;
			if (ex <= 0) return 0;
			const others_base = rows.reduce((s, r, i) => {
				if (i === row_idx) return s;
				const amt = parseFloat(r.rate) || 0;
				const rx  = parseFloat(r.exchange_rate) || 1;
				return s + amt * rx;
			}, 0);
			const remaining_base = outstanding - others_base;
			return remaining_base > 0
				? Math.round((remaining_base / ex) * 100) / 100
				: 0;
		};

		// FX rounding tolerance: at 2dp in a foreign currency, one cent is
		// worth `ex_rate` in base currency. So a perfectly-auto-filled row
		// can be up to 0.5 cent × max(ex_rate) off the outstanding. Treat
		// that as "Settles" rather than a real over/under.
		const fx_tolerance = () => {
			const rows = d.get_value("payments") || [];
			const max_ex = rows.reduce((m, r) => {
				const ex = parseFloat(r.exchange_rate) || 1;
				return Math.max(m, ex);
			}, 1);
			return Math.max(0.02, max_ex * 0.005);
		};

		// Non-destructive update of a row's Amount cell — mutates the model
		// and rewrites the input's displayed value without calling
		// grid.refresh(). grid.refresh() tears down the cell that the user
		// is typing in, so we avoid it during live input.
		const set_row_amount_live = (row_idx, new_amount) => {
			const rows = d.get_value("payments") || [];
			const target = rows[row_idx];
			if (!target) return;
			target.rate = new_amount;
			const $input = d.$wrapper.find(
				`.grid-row[data-idx="${row_idx + 1}"] input[data-fieldname="rate"]`
			);
			if ($input.length && !$input.is(":focus")) {
				$input.val(new_amount);
			}
		};

		// Full refresh path — used after currency/method changes (commit
		// events) where a grid.refresh is safe and the formatted display
		// matters.
		const apply_smart_balance = (row_idx) => {
			const rows = d.get_value("payments") || [];
			const new_amount = compute_row_fill(rows, row_idx);
			const target = rows[row_idx];
			if (!target) return;
			target.rate = new_amount;
			d.fields_dict.payments.grid.refresh();
			render_totals();
		};

		// Live path — called from the input handler as the user types.
		// Updates the LAST row (unless the user is editing it) so the
		// balance always flows to the tail of the list. Debounced so a fast
		// typer doesn't churn the DOM on every keystroke.
		let live_pending = null;
		const schedule_live_last_fill = (source_idx) => {
			if (live_pending) clearTimeout(live_pending);
			live_pending = setTimeout(() => {
				live_pending = null;
				const rows = d.get_value("payments") || [];
				const last_idx = rows.length - 1;
				if (last_idx < 0) return;
				if (source_idx === last_idx) return; // don't fight the user
				const new_amount = compute_row_fill(rows, last_idx);
				set_row_amount_live(last_idx, new_amount);
				render_totals();
			}, 120);
		};

		// Async: fetch FX when the user picks a non-base currency. Kept
		// separate from render_totals so we don't blow up the rate on every
		// keystroke of the Amount field.
		const fetch_rate_for_row = (row_doc, row_idx) => {
			const cur = row_doc.currency;
			if (!cur) return;
			if (cur === base_currency) {
				if (row_doc.exchange_rate !== 1) {
					row_doc.exchange_rate = 1;
				}
				apply_smart_balance(row_idx);
				return;
			}
			frappe.call({
				method: "erpnext.setup.utils.get_exchange_rate",
				args: {
					from_currency: cur,
					to_currency: base_currency,
					transaction_date: row_doc.date || today_str,
				},
				callback(r2) {
					const rate = parseFloat(r2 && r2.message) || 0;
					if (!rate) {
						frappe.msgprint(__("No exchange rate found from {0} to {1}. Enter it manually.",
							[cur, base_currency]));
						return;
					}
					row_doc.exchange_rate = rate;
					apply_smart_balance(row_idx);
				},
			});
		};

		// Print a past-payment receipt. Stop propagation so the click
		// doesn't also trigger the table-change handler below.
		d.$wrapper.on("click", ".tp-print-row", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const idx = parseInt($(e.currentTarget).attr("data-idx") || "-1", 10);
			const row = past_payments[idx];
			if (row) {
				ihotel_print_payment_receipt(p, row);
			}
		});

		// Live Amount updates: listen on `input` (fires per keystroke).
		// Restricted to numeric Amount cells so we never race the Currency
		// autocomplete (which needs commit-on-blur).
		d.$wrapper.on("input", '.grid-row input[data-fieldname="rate"]', (e) => {
			const $target = $(e.target);
			const row_el = $target.closest(".grid-row");
			const idx_attr = row_el.attr("data-idx");
			if (!idx_attr) return;
			const idx = parseInt(idx_attr, 10) - 1;
			const rows = d.get_value("payments") || [];
			const row_doc = rows[idx];
			if (!row_doc) return;
			// Mirror the live value into the model so render_totals and
			// schedule_live_last_fill both see it.
			row_doc.rate = parseFloat($target.val()) || 0;
			render_totals();
			schedule_live_last_fill(idx);
		});

		// Commit events for the non-numeric fields (Currency autocomplete,
		// Method Link, Date). Also refresh totals on Amount blur so the
		// formatted display catches up.
		d.$wrapper.on("change", 'input,select,[contenteditable="true"]', (e) => {
			render_totals();
			const $target = $(e.target);
			const row_el = $target.closest(".grid-row");
			const idx_attr = row_el.attr("data-idx");
			if (!idx_attr) return;
			const idx = parseInt(idx_attr, 10) - 1;
			const rows = d.get_value("payments") || [];
			const row_doc = rows[idx];
			if (row_doc && $target.attr("data-fieldname") === "currency") {
				fetch_rate_for_row(row_doc, idx);
			}
		});

		// Smart balance on row-add: when the user clicks "Add Row" in the
		// grid, auto-fill the new row's Amount with whatever remains of the
		// outstanding (converted via its currency's exchange rate). User can
		// still override — we only pre-fill the fresh zero row.
		d.$wrapper.on("click", ".grid-add-row", () => {
			setTimeout(() => {
				const rows = d.get_value("payments") || [];
				if (!rows.length) return;
				apply_smart_balance(rows.length - 1);
			}, 60);
		});

		setTimeout(render_totals, 0);

		// Submit actions. Cap + base-currency math re-done here so Enter on a
		// cell can't bypass the warning.
		const submit_take_payment = (post_checkout) => {
			const rows = d.get_value("payments") || [];
			const payments = rows
				.map(r => ({
					date: r.date || today_str,
					payment_method: r.payment_method || "Cash",
					currency: r.currency || base_currency,
					exchange_rate: parseFloat(r.exchange_rate) || 1,
					amount: parseFloat(r.rate || 0),
					payment_status: "Paid",
				}))
				.filter(p => p.amount > 0);
			if (!payments.length) {
				frappe.msgprint(__("Enter at least one payment with a non-zero amount."));
				return;
			}
			const total_base = payments.reduce(
				(s, p) => s + (p.amount * (p.exchange_rate || 1)), 0);
			if (outstanding > 0 && total_base - outstanding > fx_tolerance()) {
				frappe.msgprint({
					title: __("Over the Outstanding Balance"),
					message: __("Total payments ({0}) exceed the outstanding balance ({1}). Adjust so the total is at most the outstanding.",
						[fmt(total_base), fmt(outstanding)]),
					indicator: "red",
				});
				return;
			}
			frappe.dom.freeze(__("Posting payments..."));
			frappe.call({
				method: "ihotel.ihotel.doctype.checked_in.checked_in.take_payment",
				args: {
					checked_in: frm.doc.name,
					payments: JSON.stringify(payments),
					also_checkout: post_checkout ? 1 : 0,
				},
				callback(r) {
					frappe.dom.unfreeze();
					if (!r || !r.message) return;
					const m = r.message;
					const created = (m.payment_entries || []).length;
					const failed = (m.failed_payments || []).length;

					if (failed > 0) {
						// Server already showed a red msgprint with per-row
						// details. Keep the dialog open so the user can fix
						// and retry with the failed amount; still reload the
						// form behind so the outstanding now reflects only
						// what actually posted.
						frappe.show_alert({
							message: __("{0} posted, {1} failed. See the Payment Posting Failed message for details.",
								[created, failed]),
							indicator: "orange",
						});
						frm.reload_doc();
						return;
					}

					let msg = __("{0} payment(s) posted.", [created]);
					if (m.checked_out) msg += " " + __("Guest checked out.");
					else if (m.outstanding > 0) msg += " " + __("Outstanding: {0}", [fmt(m.outstanding)]);
					frappe.show_alert({ message: msg, indicator: "green" });
					d.hide();
					frm.reload_doc();
				},
				error() {
					frappe.dom.unfreeze();
				},
			});
		};

		if (also_checkout) {
			d.set_primary_action(__("Save & Check Out"), () => submit_take_payment(true));
			d.set_secondary_action_label(__("Save Payment Only"));
			d.set_secondary_action(() => submit_take_payment(false));
		} else {
			d.set_primary_action(__("Save Payment"), () => submit_take_payment(false));
			d.set_secondary_action_label(__("Save & Check Out"));
			d.set_secondary_action(() => submit_take_payment(true));
		}

		d.show();
	});
}

// ── Shared: Print a single payment receipt ────────────────────────────────────
//
// Mirrors the receipt printed from the Payment Items row on iHotel Profile
// so receipts look identical whether the user triggers them from the folio
// form or from the Take Payment dialog on Checked In.
function ihotel_print_payment_receipt(profile, row) {
	const hotel_name = (frappe.sys_defaults && frappe.sys_defaults.company) || "Hotel";
	// format_currency(value, currency_code) resolves per-row so USD prints
	// with "$"/"USD" and GHS prints with "GH₵" — frappe.format's `options`
	// field expects a fieldname, not a literal code.
	const amount_fmt = format_currency(row.rate, row.currency || undefined);
	const date_fmt = frappe.datetime.str_to_user(row.date);

	const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Payment Receipt</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; max-width: 380px; margin: 30px auto; padding: 20px; color: #111; }
  h1 { text-align: center; font-size: 1.1em; letter-spacing: 2px; margin-bottom: 4px; }
  .subtitle { text-align: center; font-size: 0.78em; color: #555; margin-bottom: 16px; }
  .dashed { border-top: 1px dashed #999; margin: 10px 0; }
  .row { display: flex; justify-content: space-between; font-size: 0.85em; margin: 5px 0; }
  .row.big { font-size: 1.05em; font-weight: bold; margin-top: 8px; }
  .label { color: #555; }
  .status-badge { display: inline-block; padding: 2px 8px; border: 1px solid #333; border-radius: 3px; font-size: 0.78em; }
  .footer { text-align: center; font-size: 0.75em; color: #777; margin-top: 16px; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
  <h1>${frappe.utils.escape_html(hotel_name)}</h1>
  <div class="subtitle">PAYMENT RECEIPT</div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Guest</span><span>${frappe.utils.escape_html(profile.guest_name || profile.guest || "")}</span></div>
  <div class="row"><span class="label">Room</span><span>${frappe.utils.escape_html(profile.room || "")}</span></div>
  <div class="row"><span class="label">Profile</span><span>${frappe.utils.escape_html(profile.name || "")}</span></div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Date</span><span>${date_fmt}</span></div>
  <div class="row"><span class="label">Method</span><span>${frappe.utils.escape_html(row.payment_method || "")}</span></div>
  ${row.detail ? `<div class="row"><span class="label">Description</span><span>${frappe.utils.escape_html(row.detail)}</span></div>` : ""}
  <div class="dashed"></div>
  <div class="row big"><span>AMOUNT PAID</span><span>${amount_fmt}</span></div>
  <div class="dashed"></div>
  <div class="row">
    <span class="label">Status</span>
    <span class="status-badge">${frappe.utils.escape_html(row.payment_status || "")}</span>
  </div>
  <div class="footer">
    <p>Printed: ${frappe.datetime.now_datetime()}</p>
    <p style="margin-top:4px;">Thank you — please retain this receipt</p>
  </div>
</body>
</html>`;

	const w = window.open("", "_blank", "width=480,height=640,toolbar=0,menubar=0");
	if (!w) {
		frappe.msgprint(__("Please allow popups to print receipts."));
		return;
	}
	w.document.write(html);
	w.document.close();
	w.focus();
	setTimeout(() => w.print(), 400);
}

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
