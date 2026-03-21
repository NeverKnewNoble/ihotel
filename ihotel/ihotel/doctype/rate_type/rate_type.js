// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

const TAX_FIELDS = [
	{ apply: "apply_vat",          rate: "vat_rate" },
	{ apply: "apply_nhil",         rate: "nhil_rate" },
	{ apply: "apply_getfund",      rate: "getfund_rate" },
	{ apply: "apply_covid_levy",   rate: "covid_levy_rate" },
	{ apply: "apply_tourism_levy", rate: "tourism_levy_rate" },
];

frappe.ui.form.on("Rate Type", {
	refresh(frm) {
		frm.trigger("calculate_effective_tax");
	},

	// Recalculate whenever any toggle or rate field changes
	apply_vat:          frm => frm.trigger("calculate_effective_tax"),
	vat_rate:           frm => frm.trigger("calculate_effective_tax"),
	apply_nhil:         frm => frm.trigger("calculate_effective_tax"),
	nhil_rate:          frm => frm.trigger("calculate_effective_tax"),
	apply_getfund:      frm => frm.trigger("calculate_effective_tax"),
	getfund_rate:       frm => frm.trigger("calculate_effective_tax"),
	apply_covid_levy:   frm => frm.trigger("calculate_effective_tax"),
	covid_levy_rate:    frm => frm.trigger("calculate_effective_tax"),
	apply_tourism_levy: frm => frm.trigger("calculate_effective_tax"),
	tourism_levy_rate:  frm => frm.trigger("calculate_effective_tax"),

	calculate_effective_tax(frm) {
		let total = 0;

		// Sum standard Ghana taxes
		for (const { apply, rate } of TAX_FIELDS) {
			if (frm.doc[apply]) {
				total += flt(frm.doc[rate]);
			}
		}

		// Sum additional custom taxes
		if (frm.doc.additional_taxes && frm.doc.additional_taxes.length) {
			for (const row of frm.doc.additional_taxes) {
				total += flt(row.tax_rate);
			}
		}

		frm.set_value("effective_tax_rate", total);
	},
});

// Recalculate when custom tax rows change
frappe.ui.form.on("Rate Tax", {
	tax_rate(frm) { frm.trigger("calculate_effective_tax"); },
	additional_taxes_remove(frm) { frm.trigger("calculate_effective_tax"); },
});
