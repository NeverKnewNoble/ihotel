frappe.listview_settings["Checked In"] = {
	onload(listview) {
		listview.sort_selector.wrapper
			.find(".btn-order")
			.prop("disabled", true)
			.attr("title", "")
			.css({ opacity: 0.35, cursor: "not-allowed", "pointer-events": "none" });
	},
};

frappe.views.calendar["Checked In"] = {
	field_map: {
		start: "expected_check_in",
		end: "expected_check_out",
		id: "name",
		title: "guest",
		allDay: 0,
		color: "color",
	},
	style_map: {
		Reserved:     "success",
		"Checked In": "info",
		"Checked Out": "default",
		Cancelled:    "danger",
	},
	get_events_method: "frappe.desk.doctype.event.event.get_events",
	options: {
		eventContent: function (arg) {
			return {
				html: `<div class="ihotel-event-label" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-weight:700;color:#ffffff;text-align:center;padding:2px 4px;white-space:normal;line-height:1.2;">${arg.event.title}</div>`,
			};
		},
	},
};
