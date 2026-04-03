// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Laundry Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Load Items from ERPXpand"), function () {
			if (!frm.doc.laundry_item_group) {
				frappe.msgprint(__("Please set a Laundry Item Group first."));
				return;
			}
			frappe.confirm(
				__("Load all active ERPXpand items under <b>{0}</b> as Laundry Items?", [frm.doc.laundry_item_group]),
				function () {
					frappe.call({
						method: "ihotel.ihotel.doctype.laundry_settings.laundry_settings.load_items_from_erpxpand",
						args: { item_group: frm.doc.laundry_item_group },
						callback(r) {
							if (r.message !== undefined) {
								frappe.show_alert({
									message: __("{0} item(s) loaded, {1} already existed.", [r.message.added, r.message.skipped]),
									indicator: "green",
								});
							}
						},
					});
				}
			);
		}, __("Actions"));

		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");
	},
});
