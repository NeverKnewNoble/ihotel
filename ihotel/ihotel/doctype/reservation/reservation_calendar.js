frappe.listview_settings["Reservation"] = {
	onload(listview) {
		listview.sort_selector.wrapper
			.find(".btn-order")
			.prop("disabled", true)
			.attr("title", "")
			.css({ opacity: 0.35, cursor: "not-allowed", "pointer-events": "none" });
	},
};

frappe.views.calendar["Reservation"] = {
	field_map: {
		start: "check_in_date",
		end: "check_out_date",
		id: "name",
		title: "full_name",
		allDay: 0,
		color: "color",
	},
	style_map: {
		pending:   "warning",
		confirmed: "success",
		cancelled: "danger",
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
