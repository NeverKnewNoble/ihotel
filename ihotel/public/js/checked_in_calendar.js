// ── Shared helper: open a dialog to pick a Reservation and convert it ───────────
// Reused by both the Checked In list view and the Checked In calendar view.
function _show_check_in_from_reservation_dialog(on_success) {
	const d = new frappe.ui.Dialog({
		title: __("Check In from Reservation"),
		fields: [
			{
				fieldtype: "Link",
				fieldname: "reservation",
				label: __("Reservation"),
				options: "Reservation",
				reqd: 1,
				change() {
					const reservation = d.get_value("reservation");
					if (!reservation) {
						d.set_value("guest_name", "");
						return;
					}
					frappe.call({
						method: "ihotel.ihotel.doctype.reservation.reservation.get_reservation_guest_for_check_in",
						args: { reservation_name: reservation },
						callback(r) {
							const payload = r.message || {};
							d.set_value("guest_name", payload.guest_name || "");
						},
					});
				},
				// Supports search by reservation code or guest name while keeping
				// the same eligibility rules used for front-desk check-in.
				get_query() {
					return {
						query: "ihotel.ihotel.doctype.reservation.reservation.search_reservations_for_check_in",
					};
				},
			},
			{
				fieldtype: "Data",
				fieldname: "guest_name",
				label: __("Guest Name"),
				read_only: 1,
			},
		],
		primary_action_label: __("Check In"),
		primary_action(values) {
			if (!values.guest_name) {
				frappe.msgprint({
					title: __("Guest Not Found"),
					message: __("Enter a valid reservation code to load and verify the guest name before check-in."),
					indicator: "red",
				});
				return;
			}
			d.hide();
			frappe.call({
				method: "ihotel.ihotel.doctype.reservation.reservation.convert_to_hotel_stay",
				args: { reservation_name: values.reservation },
				freeze: true,
				freeze_message: __("Converting reservation to check-in…"),
				callback(r) {
					if (r.message) {
						frappe.show_alert({
							message: __("Guest checked in successfully."),
							indicator: "green",
						}, 5);
						if (on_success) {
							on_success(r.message);
						} else {
							frappe.set_route("Form", "Checked In", r.message);
						}
					}
				},
			});
		},
	});
	d.show();
}

// ── Checked In list view ──────────────────────────────────────────────────────
frappe.listview_settings["Checked In"] = {
	onload(listview) {
		// Disable the default sort-order toggle (irrelevant for stay management)
		listview.sort_selector.wrapper
			.find(".btn-order")
			.prop("disabled", true)
			.attr("title", "")
			.css({ opacity: 0.35, cursor: "not-allowed", "pointer-events": "none" });

		// Let front desk convert a Reservation into a Checked In directly from this list
		listview.page.add_inner_button(__("Check in from Reservation"), function () {
			_show_check_in_from_reservation_dialog(function () {
				listview.refresh();
			});
		});
	},
};

// ── Checked In calendar view ──────────────────────────────────────────────────
// Frappe's CalendarView overrides setup_view() with an empty stub, so
// listview_settings.onload never fires for the calendar route.
// We patch CalendarView.prototype.render once — guarded by doctype — so the
// "Check in from Reservation" button is added after the calendar renders.
(function _patch_calendar_view_for_checked_in() {
	const _orig_render = frappe.views.CalendarView.prototype.render;

	frappe.views.CalendarView.prototype.render = function () {
		_orig_render.call(this);

		if (this.doctype !== "Checked In" || this._ihotel_btn_added) return;
		this._ihotel_btn_added = true;

		const me = this;
		this.page.add_inner_button(__("Check in from Reservation"), function () {
			_show_check_in_from_reservation_dialog(function () {
				me.calendar && me.calendar.refresh();
			});
		});
	};
}());

// ── Checked In calendar field map and options ─────────────────────────────────
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
