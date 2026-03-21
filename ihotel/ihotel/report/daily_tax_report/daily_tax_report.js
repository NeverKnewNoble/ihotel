// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

frappe.query_reports["Daily Tax Report"] = {
	filters: [
		{
			fieldname: "date",
			label: __("Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "rate_type",
			label: __("Rate Type"),
			fieldtype: "Link",
			options: "Rate Type",
		},
		{
			fieldname: "room_type",
			label: __("Room Type"),
			fieldtype: "Link",
			options: "Room Type",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Highlight the Grand Total column
		if (column.fieldname === "grand_total" && data && data.grand_total > 0) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
