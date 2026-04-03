frappe.views.calendar["Reservation"] = {
	field_map: {
		"start": "check_in_date",
		"end": "check_out_date",
		"id": "name",
		"title": "full_name",
		"subject": "full_name",
		"color": "color",
		"allDay": 1,
	},
	options: {
		initialDate: frappe.datetime.get_today(),
		eventDidMount: function(info) {
			// Use FullCalendar's own string (already in user timezone) rather than
			// converting the JS Date object, which would apply browser-local offset.
			const fmtDate = (s) => s ? frappe.datetime.str_to_user(s.slice(0, 10)) : "";
			const startStr = fmtDate(info.event.startStr);
			const endStr   = fmtDate(info.event.endStr);
			$(info.el).attr("title",
				`${info.event.title}\nCheck-in: ${startStr}\nCheck-out: ${endStr}`
			);
		},
	},
	filters: [
		{
			"fieldtype": "Select",
			"fieldname": "status",
			"options": "\npending\nconfirmed\nchecked_in\ncancelled",
			"label": __("Status"),
		},
	],
};
