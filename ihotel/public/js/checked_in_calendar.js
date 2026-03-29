frappe.views.calendar["Checked In"] = {
	field_map: {
		"start": "expected_check_in",
		"end":   "expected_check_out",
		"id":    "name",
		"title": "guest",
		"color": "color",
		"allDay": 0,
	},
	options: {
		initialDate: frappe.datetime.get_today(),
	},
	filters: [
		{
			"fieldtype": "Select",
			"fieldname": "status",
			"options": "\nReserved\nChecked In\nChecked Out\nNo Show\nCancelled",
			"label": __("Status"),
		},
	],
};
