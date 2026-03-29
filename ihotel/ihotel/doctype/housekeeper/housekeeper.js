// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Housekeeper", {
	employee(frm) {
		if (!frm.doc.employee) {
			frm.set_value("phone", "");
			frm.set_value("email", "");
			return;
		}

		frappe.db.get_value("Employee", frm.doc.employee,
			["cell_number", "prefered_email", "company_email", "personal_email"]
		).then(r => {
			if (!r.message) return;
			const emp = r.message;
			frm.set_value("phone", emp.cell_number || "");
			frm.set_value("email",
				emp.prefered_email || emp.company_email || emp.personal_email || ""
			);
		});
	},
});
