frappe.views.calendar["Checked In"] = {
	field_map: {
		start: "expected_check_in",
		end: "expected_check_out",
		id: "name",
		title: "guest",
		allDay: 0,
	},
	style_map: {
		Reserved:    "success",
		"Checked In": "info",
		"Checked Out": "default",
		Cancelled:   "danger",
	},
	get_events_method: "frappe.desk.doctype.event.event.get_events",
};
