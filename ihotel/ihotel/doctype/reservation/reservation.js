// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

const STATUS_COLORS = {
	pending:   "orange",
	confirmed: "green",
	cancelled: "red",
};

frappe.ui.form.on("Reservation", {
	refresh(frm) {
		// Status indicator in form header
		if (frm.doc.status) {
			const color = STATUS_COLORS[frm.doc.status] || "gray";
			frm.page.set_indicator(__(frm.doc.status), color);
		}

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

		// Customer ID filter: only show Company-type customers
		frm.set_query("customer_id", function () {
			return { filters: { customer_type: "Company" } };
		});

		// Room filter by room_type, excluding permanently unavailable rooms
		frm.set_query("room", function () {
			let filters = { status: ["not in", ["Out of Order", "Out of Service"]] };
			if (frm.doc.room_type) filters["room_type"] = frm.doc.room_type;
			return { filters };
		});

		if (!frm.is_new()) {
			// 1. Confirm — first
			if (frm.doc.status === "pending") {
				frm.add_custom_button(__("Confirm"), function () {
					frm.set_value("status", "confirmed");
					frm.save();
				}, __("Actions"));
			}

			// 2. Convert to Checked In
			if (frm.doc.status !== "cancelled" && !frm.doc.hotel_stay) {
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

			// 3. Proforma Invoice
			if (frm.doc.status !== "cancelled") {
				if (frm.doc.proforma_invoice) {
					frm.add_custom_button(__("View Proforma Invoice"), function () {
						frappe.set_route("Form", "Sales Invoice", frm.doc.proforma_invoice);
					}, __("Actions"));
				} else {
					frm.add_custom_button(__("Create Proforma Invoice"), function () {
						frappe.confirm(
							__("Create a proforma invoice for this reservation?"),
							function () {
								frappe.call({
									method: "ihotel.ihotel.doctype.reservation.reservation.create_proforma_invoice",
									args: { reservation_name: frm.doc.name },
									callback(r) {
										if (r.message) frm.reload_doc();
									},
								});
							}
						);
					}, __("Actions"));
				}
			}

			// 4. Turndown
			if (frm.doc.status !== "cancelled") {
				const td_label = frm.doc.turndown_requested
					? __("Cancel Turndown")
					: __("Request Turndown");
				frm.add_custom_button(td_label, function () {
					const new_val = frm.doc.turndown_requested ? 0 : 1;
					frappe.call({
						method: "ihotel.ihotel.page.turndown.turndown.toggle_turndown",
						args: { doctype: "Reservation", docname: frm.doc.name, value: new_val },
						callback() {
							frm.reload_doc();
						},
					});
				}, __("Actions"));
			}

			// 5. Cancel Reservation — last
			if (frm.doc.status !== "cancelled") {
				frm.add_custom_button(__("Cancel Reservation"), function () {
					frappe.confirm(
						__("Are you sure you want to cancel this reservation?"),
						function () {
							frm.set_value("status", "cancelled");
							frm.save();
						}
					);
				}, __("Actions")).css("color", "#c0392b");
			}

			// Color all custom action buttons
			frm.page.custom_actions.find("button")
				.removeClass("btn-default btn-secondary")
				.addClass("btn-primary");
		}

		// MM/YY input mask for card expiry
		const $expiry = frm.fields_dict["card_expiry"] && frm.fields_dict["card_expiry"].$input;
		if ($expiry && $expiry.length) {
			$expiry.attr("placeholder", "MM/YY").attr("maxlength", "5");
			$expiry.off("input.mmyy").on("input.mmyy", function () {
				let digits_before = this.value.slice(0, this.selectionStart).replace(/\D/g, "").length;
				let raw = this.value.replace(/\D/g, "").slice(0, 4);
				let formatted = raw.length > 2 ? raw.slice(0, 2) + "/" + raw.slice(2) : raw;
				this.value = formatted;
				// map digit count back to position in formatted string (slash adds 1 after 2 digits)
				let new_pos = digits_before > 2 ? digits_before + 1 : digits_before;
				this.setSelectionRange(new_pos, new_pos);
			});
		}

		// Intro: proforma invoice
		if (frm.doc.proforma_invoice) {
			frm.set_intro(
				__("Proforma Invoice: {0}", [
					`<a href="/app/sales-invoice/${frm.doc.proforma_invoice}">${frm.doc.proforma_invoice}</a>`
				]),
				"blue"
			);
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

		apply_direct_bill_rule(frm);
	},

	payment_method(frm) {
		apply_direct_bill_rule(frm);
	},

	// When guest profile is selected, auto-fill contact details + check traces
	guest(frm) {
		if (frm.doc.guest) {
			frappe.db.get_doc("Guest", frm.doc.guest).then((g) => {
				if (!frm.doc.full_name)      frm.set_value("full_name", g.guest_name);
				if (!frm.doc.email_address)  frm.set_value("email_address", g.email);
				if (!frm.doc.phone_number)   frm.set_value("phone_number", g.phone);
				if (!frm.doc.date_of_birth)  frm.set_value("date_of_birth", g.date_of_birth);
				if (!frm.doc.country && g.nationality) frm.set_value("country", g.nationality);
			});
			show_guest_bad_traces_alert(frm.doc.guest);
		}
	},

	room_type(frm) {
		if (frm.doc.room_type && frm.doc.room) {
			frappe.db.get_value("Room", frm.doc.room, "room_type").then((r) => {
				if (r.message && r.message.room_type !== frm.doc.room_type) {
					frm.set_value("room", "");
				}
			});
		}
	},

	check_in_date(frm) { frm.trigger("calculate_days"); },
	check_out_date(frm) { frm.trigger("calculate_days"); },

	calculate_days(frm) {
		if (frm.doc.check_in_date && frm.doc.check_out_date) {
			let days = frappe.datetime.get_day_diff(frm.doc.check_out_date, frm.doc.check_in_date);
			if (days > 0) {
				frm.set_value("days", days);
				recalc_totals(frm);
			}
		}
	},

	color(frm) {
		if (frm.doc.color) {
			frm.page.set_indicator(frm.doc.status || "", frm.doc.color);
		}
	},


	rate_lines_remove(frm) {
		recalc_totals(frm);
	},
});

// ── Stay Rate Line row events ─────────────────────────────────────────────────
frappe.ui.form.on("Stay Rate Line", {
	rate_type(frm, cdt, cdn) {
		if (frm._syncing_rate_type) return;
		const row = locals[cdt][cdn];
		const new_rt = row.rate_type;

		// Propagate this rate_type to every other row in the table
		const others = (frm.doc.rate_lines || []).filter(r => r.name !== row.name && r.rate_type !== new_rt);
		if (others.length) {
			frm._syncing_rate_type = true;
			Promise.all(
				others.map(r => frappe.model.set_value("Stay Rate Line", r.name, "rate_type", new_rt))
			).then(() => {
				frm._syncing_rate_type = false;
				// Re-fetch rates for ALL rows now that rate_type is uniform
				(frm.doc.rate_lines || []).forEach(r => fetch_rate_line(frm, "Stay Rate Line", r.name));
			});
		} else {
			fetch_rate_line(frm, cdt, cdn);
		}
	},
	room_type(frm, cdt, cdn)  { fetch_rate_line(frm, cdt, cdn); },
	rate_column(frm, cdt, cdn){ fetch_rate_line(frm, cdt, cdn); },
	discount1(frm, cdt, cdn)  { apply_line_discounts(frm, cdt, cdn); },
	discount2(frm, cdt, cdn)  { apply_line_discounts(frm, cdt, cdn); },
	discount3(frm, cdt, cdn)  { apply_line_discounts(frm, cdt, cdn); },
	amount(frm)               { recalc_totals(frm); },
});

// ── Totals ────────────────────────────────────────────────────────────────────

function recalc_totals(frm) {
	const rate_lines_total = flt(
		(frm.doc.rate_lines || []).reduce((s, r) => s + (r.amount || 0), 0), 2
	);
	frm.set_value("total_charges", rate_lines_total);

	// Compute tax from first rate_line's Rate Type tax_schedule
	const primary = (frm.doc.rate_lines || []).find(r => r.rate_type);
	if (primary) {
		frappe.db.get_doc("Rate Type", primary.rate_type).then(rate_doc => {
			const tax_amt = compute_tax_from_schedule(rate_doc.tax_schedule || [], rate_lines_total);
			frm.set_value("tax",          tax_amt);
			frm.set_value("total_rental", flt(rate_lines_total + tax_amt, 2));
		});
	} else {
		frm.set_value("tax",          0);
		frm.set_value("total_rental", rate_lines_total);
	}
}

function compute_tax_from_schedule(tax_schedule, net_total) {
	const amounts = [];
	for (const row of tax_schedule) {
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

// ── Rate line helpers ─────────────────────────────────────────────────────────

function apply_line_discounts(frm, cdt, cdn) {
	const row    = locals[cdt][cdn];
	const rate   = row.rate || 0;
	const d1     = row.discount1 || 0;
	const d2     = row.discount2 || 0;
	const d3     = row.discount3 || 0;
	const amount = flt(rate * (1 - d1 / 100) * (1 - d2 / 100) * (1 - d3 / 100), 2);
	frappe.model.set_value(cdt, cdn, "amount", amount).then(() => {
		recalc_totals(frm);
	});
}

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
		const today    = frappe.datetime.get_today();
		const desc     = rate_doc.rate_type_name || rate_doc.name;
		const preferred = row.room_type || frm.doc.rate_room_type || "";
		const fallback  = frm.doc.room_type || "";

		const schedule = rate_doc.rate_schedule || [];
		const in_range = (s) =>
			(!s.from_date || s.from_date <= today) && (!s.to_date || s.to_date >= today);
		const matched = (preferred && schedule.find(s => s.room_type === preferred && in_range(s)))
			|| (fallback && schedule.find(s => s.room_type === fallback && in_range(s)))
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
			apply_line_discounts(frm, cdt, cdn);
		});
	});
}

function resolve_schedule_rate(rate_doc, preferred_rt, fallback_rt, today, adults, children) {
	const schedule = rate_doc.rate_schedule || [];
	const in_range = (row) =>
		(!row.from_date || row.from_date <= today) &&
		(!row.to_date   || row.to_date   >= today);

	const matched = (preferred_rt && schedule.find(r => r.room_type === preferred_rt && in_range(r)))
		|| (fallback_rt && schedule.find(r => r.room_type === fallback_rt && in_range(r)))
		|| schedule.find(r => !r.room_type && in_range(r));

	if (!matched) return rate_doc.base_rate || 0;

	const base = (adults > 1 && matched.double_rate)
		? matched.double_rate
		: (matched.rate || rate_doc.base_rate || 0);
	const child_supplement = (children > 0 && matched.extra_child)
		? matched.extra_child * children : 0;
	return base + child_supplement;
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

function apply_direct_bill_rule(frm) {
	const is_direct_bill = frm.doc.payment_method === "Direct Bill";
	if (is_direct_bill) {
		frm.set_value("guarantee_type", "Company");
		frm.set_df_property("guarantee_type", "read_only", 1);
		frm.set_df_property("guarantee_type", "description", "Direct Bill requires Company guarantee");
	} else {
		frm.set_df_property("guarantee_type", "read_only", 0);
		frm.set_df_property("guarantee_type", "description", "");
	}
}
