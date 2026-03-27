// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Order Item", {
	laundry_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.laundry_item) return;
		frappe.db.get_doc("Laundry Item", row.laundry_item).then(item => {
			const rate = frm.doc.customer_type === "Guest"
				? item.guest_price
				: item.outsider_price;
			frappe.model.set_value(cdt, cdn, "rate", rate || 0);
			frappe.model.set_value(cdt, cdn, "item_name", item.item_name || "");
		});
	},
	quantity(frm, cdt, cdn) {
		_calc_row_amount(cdt, cdn);
	},
	rate(frm, cdt, cdn) {
		_calc_row_amount(cdt, cdn);
	},
});

function _calc_row_amount(cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.rate) * flt(row.quantity || 1));
}
