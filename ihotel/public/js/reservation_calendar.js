// ── Reservation list view ─────────────────────────────────────────────────────
frappe.listview_settings["Reservation"] = {
	onload(listview) {
		// Disable the default sort-order toggle (calendar-oriented list)
		listview.sort_selector.wrapper
			.find(".btn-order")
			.prop("disabled", true)
			.attr("title", "")
			.css({ opacity: 0.35, cursor: "not-allowed", "pointer-events": "none" });

		// Allow converting a selected Reservation row to a Checked In directly from the list
		listview.page.add_action_item(__("Check In Selected"), function () {
			const checked = listview.get_checked_items();
			if (!checked.length) {
				frappe.show_alert({ message: __("Select a reservation row first."), indicator: "orange" }, 4);
				return;
			}
			if (checked.length > 1) {
				frappe.show_alert({ message: __("Please select only one reservation at a time."), indicator: "orange" }, 4);
				return;
			}
			const row = checked[0];
			if (row.hotel_stay) {
				frappe.show_alert({ message: __("This reservation is already checked in."), indicator: "orange" }, 4);
				return;
			}
			if (!row.room) {
				frappe.msgprint({
					title: __("Room Required"),
					message: __("Assign a Room Number on the reservation before checking in."),
					indicator: "red",
				});
				return;
			}
			frappe.call({
				method: "ihotel.ihotel.doctype.reservation.reservation.convert_to_hotel_stay",
				args: { reservation_name: row.name },
				freeze: true,
				freeze_message: __("Checking in guest…"),
				callback(r) {
					if (r.message) {
						frappe.show_alert({
							message: __("Guest checked in. Stay: {0}", [r.message]),
							indicator: "green",
						}, 6);
						listview.refresh();
					}
				},
			});
		});
	},
};

// ── Reservation calendar field map and options ────────────────────────────────
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
