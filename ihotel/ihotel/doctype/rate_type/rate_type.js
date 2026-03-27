// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Rate Type", {
	refresh(frm) {
		frm.add_custom_button(__("Load from ERPXpand Taxes"), function () {
			frappe.call({
				method: "ihotel.ihotel.doctype.rate_type.rate_type.get_erp_tax_accounts",
				callback(r) {
					if (!r.message || !r.message.length) {
						frappe.msgprint(__("No Tax-type accounts found in ERPXpand."));
						return;
					}
					const existing = (frm.doc.tax_schedule || []).map(row => row.tax_account);
					let added = 0;
					for (const acc of r.message) {
						if (existing.includes(acc.name)) continue;
						let row = frappe.model.add_child(frm.doc, "Rate Tax Schedule", "tax_schedule");
						frappe.model.set_value(row.doctype, row.name, "tax_account", acc.name);
						frappe.model.set_value(row.doctype, row.name, "tax_name", acc.account_name);
						frappe.model.set_value(row.doctype, row.name, "charge_type", "On Net Total");
						added++;
					}
					frm.refresh_field("tax_schedule");
					if (added) {
						frappe.show_alert({ message: __("{0} tax account(s) loaded.", [added]), indicator: "green" });
					} else {
						frappe.msgprint(__("All ERPXpand tax accounts are already in the table."));
					}
				},
			});
		}, __("Actions"));

		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");

		frm.trigger("calculate_effective_tax");
	},

	calculate_effective_tax(frm) {
		const today = frappe.datetime.get_today();
		const rows = (frm.doc.tax_schedule || []).filter(row => {
			if (row.from_date && row.from_date > today) return false;
			if (row.to_date   && row.to_date   < today) return false;
			return true;
		});

		const base = 100;
		let running_total = base;
		const row_amounts = [];
		const row_totals  = [];

		for (const row of rows) {
			const rate        = flt(row.rate);
			const charge_type = row.charge_type || "On Net Total";
			let tax_amount    = 0;

			if (charge_type === "On Net Total") {
				tax_amount = (rate / 100) * base;

			} else if (charge_type === "On Previous Row Amount") {
				const idx = _resolve_row_id(row.row_id, row_amounts.length);
				if (idx !== null) tax_amount = (rate / 100) * (row_amounts[idx] || 0);

			} else if (charge_type === "On Previous Row Total") {
				const idx = _resolve_row_id(row.row_id, row_totals.length);
				if (idx !== null) tax_amount = (rate / 100) * (row_totals[idx] || running_total);

			} else if (charge_type === "Actual") {
				tax_amount = rate;
			}

			running_total += tax_amount;
			row_amounts.push(tax_amount);
			row_totals.push(running_total);
		}

		frm.set_value("effective_tax_rate", Math.round((running_total - base) * 10000) / 10000);
	},
});

function _resolve_row_id(row_id, current_count) {
	const idx = parseInt(row_id, 10) - 1;
	if (!isNaN(idx) && idx >= 0 && idx < current_count) return idx;
	// Default: last row
	return current_count > 0 ? current_count - 1 : null;
}

frappe.ui.form.on("Rate Tax Schedule", {
	// Auto-fill tax_name from linked ERPXpand account
	tax_account(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.tax_account && !row.tax_name) {
			frappe.db.get_value("Account", row.tax_account, "account_name").then(r => {
				if (r.message && r.message.account_name) {
					frappe.model.set_value(cdt, cdn, "tax_name", r.message.account_name);
				}
			});
		}
	},

	// Show/hide row_id hint based on charge_type
	charge_type(frm, cdt, cdn) {
		frm.trigger("calculate_effective_tax");
	},

	rate(frm)               { frm.trigger("calculate_effective_tax"); },
	row_id(frm)             { frm.trigger("calculate_effective_tax"); },
	from_date(frm)          { frm.trigger("calculate_effective_tax"); },
	to_date(frm)            { frm.trigger("calculate_effective_tax"); },
	tax_schedule_remove(frm){ frm.trigger("calculate_effective_tax"); },
});
