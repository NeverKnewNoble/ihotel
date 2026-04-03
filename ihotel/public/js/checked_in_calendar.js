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
		eventDidMount: function(info) {
			// Use FullCalendar's own string (already in user timezone) rather than
			// converting the JS Date object, which would apply browser-local offset.
			const fmtDate = (s) => {
				if (!s) return "";
				// startStr for non-allDay events includes time: "2026-04-03T14:00:00+05:30"
				// Pass the date+time portion to str_to_user for proper locale formatting.
				const local = s.slice(0, 16).replace("T", " ");
				return frappe.datetime.str_to_user(local);
			};
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
			"options": "\nReserved\nChecked In\nChecked Out\nNo Show\nCancelled",
			"label": __("Status"),
		},
	],
};
