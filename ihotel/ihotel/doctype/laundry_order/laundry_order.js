// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Order", {
	refresh(frm) {
		// Status indicator colour
		const colour_map = {
			"Draft": "grey",
			"Collected": "blue",
			"Processing": "orange",
			"Quality Check": "yellow",
			"Ready": "green",
			"Delivered": "darkgreen",
			"Cancelled": "red",
		};
		if (frm.doc.status) {
			frm.page.set_indicator(__(frm.doc.status), colour_map[frm.doc.status] || "grey");
		}

		if (frm.is_new()) return;

		// Workflow status buttons (only on submitted docs)
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Cancelled" && frm.doc.status !== "Delivered") {
			const transitions = {
				"Collected":      "Processing",
				"Processing":     "Quality Check",
				"Quality Check":  "Ready",
				"Ready":          "Delivered",
			};
			const next = transitions[frm.doc.status];
			if (next) {
				frm.add_custom_button(__("→ {0}", [__(next)]), function () {
					_advance_status(frm, next);
				}).addClass("btn-primary");
			}
		}

		// Print tag
		frm.add_custom_button(__("Print Laundry Tag"), function () {
			frappe.route_options = { name: frm.doc.name };
			frappe.utils.print(frm.doctype, frm.docname, "Laundry Tag");
		}, __("Print"));

		// Color all action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");
	},

	customer_type(frm) {
		frm.set_value("customer", "");
		frm.set_value("reservation_id", "");
		frm.set_value("room_number", "");
	},

	reservation_id(frm) {
		if (!frm.doc.reservation_id) return;
		frappe.db.get_doc("Checked In", frm.doc.reservation_id).then(ci => {
			if (ci.room) frm.set_value("room_number", ci.room);
			if (ci.guest) frm.set_value("customer", ci.guest);
			if (ci.profile) frm.set_value("ihotel_profile", ci.profile);
		});
	},

	service_type(frm) {
		frm.trigger("_recalc_total");
	},

	_recalc_total(frm) {
		let total = 0;
		(frm.doc.items || []).forEach(r => { total += flt(r.amount); });
		let surcharge = 0;
		if (frm.doc.service_type) {
			frappe.db.get_value("Laundry Service Type", frm.doc.service_type, "surcharge_percentage")
				.then(v => {
					surcharge = flt(v.message.surcharge_percentage) / 100;
					const grand = total * (1 + surcharge);
					frm.set_value("total_amount", grand);
					frm.set_value("outstanding_amount", grand - flt(frm.doc.paid_amount));
				});
		} else {
			frm.set_value("total_amount", total);
			frm.set_value("outstanding_amount", total - flt(frm.doc.paid_amount));
		}
	},

	paid_amount(frm) {
		frm.set_value("outstanding_amount", flt(frm.doc.total_amount) - flt(frm.doc.paid_amount));
	},
});

frappe.ui.form.on("Laundry Order Item", {
	laundry_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.laundry_item) return;
		frappe.db.get_doc("Laundry Item", row.laundry_item).then(item => {
			const rate = frm.doc.customer_type === "Guest"
				? item.guest_price
				: item.outsider_price;
			frappe.model.set_value(cdt, cdn, "rate", flt(rate));
			frappe.model.set_value(cdt, cdn, "item_name", item.item_name || "");
		});
	},
	quantity(frm, cdt, cdn) {
		_row_amount(cdt, cdn);
		frm.trigger("_recalc_total");
	},
	rate(frm, cdt, cdn) {
		_row_amount(cdt, cdn);
		frm.trigger("_recalc_total");
	},
	items_remove(frm) {
		frm.trigger("_recalc_total");
	},
});

function _row_amount(cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.rate) * flt(row.quantity || 1));
}

function _advance_status(frm, new_status) {
	frappe.confirm(
		__("Mark order as <b>{0}</b>?", [__(new_status)]),
		function () {
			frappe.call({
				method: "frappe.client.set_value",
				args: {
					doctype: "Laundry Order",
					name: frm.docname,
					fieldname: "status",
					value: new_status,
				},
				callback() {
					frm.reload_doc();
					if (new_status === "Delivered") {
						frappe.call({
							method: "ihotel.ihotel.doctype.laundry_order.laundry_order.mark_delivered",
							args: { order_name: frm.docname },
						});
					}
				},
			});
		}
	);
}
