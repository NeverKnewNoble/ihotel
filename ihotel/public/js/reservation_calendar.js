frappe.views.calendar["Reservation"] = {
	field_map: {
		"start": "check_in_date",
		"end": "check_out_date",
		"id": "name",
		"title": "full_name",
		"color": "color",
		"allDay": 1,
	},
	options: {
		initialDate: frappe.datetime.get_today(),
	},
	filters: [
		{
			"fieldtype": "Select",
			"fieldname": "status",
			"options": "\npending\nconfirmed\ncancelled",
			"label": __("Status"),
		},
	],
};
