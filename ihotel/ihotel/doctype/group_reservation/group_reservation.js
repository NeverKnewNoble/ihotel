// Copyright (c) 2026, Noble and contributors
// For license information, please see license.txt

// Filter the Assigned Room dropdown in rooming-list rows to rooms of the
// row's Room Type (falling back to the group's Default Room Type).
frappe.ui.form.on("Group Room Assignment", {
	room_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// Clear stale room when the type changes
		if (row.room) {
			frappe.model.set_value(cdt, cdn, "room", null);
		}
	},
});

frappe.ui.form.on("Group Reservation", {
	refresh(frm) {
		// Group reservations should only link to Guest profiles representing
		// an entity that can hold a group block — Company or Partnership.
		frm.set_query("group_name", function() {
			return {
				filters: {
					guest_type: ["in", ["Company", "Partnership"]],
				},
			};
		});

		// Filter rooming-list "Assigned Room" by the row's Room Type
		// (or fall back to the group's Default Room Type).
		frm.set_query("room", "rooming_list", function(doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			const rt = row.room_type || frm.doc.room_type;
			const filters = { status: ["in", ["Available", "Vacant Dirty"]] };
			if (rt) filters.room_type = rt;
			return { filters };
		});

		// Excel upload / download for the rooming list grid
		setup_rooming_list_excel_buttons(frm);

		// Status workflow buttons (draft only)
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			if (frm.doc.status === "Tentative") {
				frm.add_custom_button(__("Confirm Reservation"), function() {
					frm.set_value("status", "Confirmed");
					frm.save();
				}).addClass("btn-primary");
			}

			if (!["Cancelled"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Cancel"), function() {
					frappe.prompt(
						{ fieldtype: "Small Text", fieldname: "reason", label: __("Cancellation Reason"), reqd: 1 },
						function(values) {
							frm.set_value("status", "Cancelled");
							frm.set_value("cancellation_reason", values.reason);
							frm.save();
						},
						__("Cancel Group Reservation"), __("Confirm Cancellation")
					);
				}, __("Actions"));
			}
		}

		// Generate individual reservations (submitted docs, not cancelled)
		if (frm.doc.docstatus === 1 && !["Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Generate Reservations"), function() {
				frappe.confirm(
					__("This will create individual Reservation records for each room in this group. Continue?"),
					function() {
						frappe.call({
							method: "ihotel.ihotel.doctype.group_reservation.group_reservation.generate_reservations",
							args: { group_reservation_name: frm.doc.name },
							callback(r) {
								if (r.message && r.message.length) {
									frm.reload_doc();
								}
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		// Color all custom action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");

		// Show linked reservations count
		if (!frm.is_new()) {
			frappe.call({
				method: "frappe.client.get_count",
				args: {
					doctype: "Reservation",
					filters: { group_reservation: frm.doc.name },
				},
				callback(r) {
					if (r.message && r.message > 0) {
						frm.set_intro(
							__("{0} reservation(s) linked to this group. ", [r.message]) +
							`<a href="/app/reservation?group_reservation=${encodeURIComponent(frm.doc.name)}">View Reservations</a>`,
							"blue"
						);
					}
				},
			});
		}
	},

	group_name(frm) {
		if (!frm.doc.group_name) {
			clear_group_contact_fields(frm);
			return;
		}

		frappe.call({
			method: "ihotel.ihotel.doctype.group_reservation.group_reservation.get_group_party_details",
			args: {
				group_name: frm.doc.group_name,
			},
			callback(r) {
				if (!r.message) return;

				const details = r.message;
				frm.set_value("full_name", details.full_name || "");
				frm.set_value("company", details.company || "");
				frm.set_value("email", details.email || "");
				frm.set_value("phone_number", details.phone_number || "");
				frm.set_value("address", details.address || "");
				frm.set_value("city", details.city || "");
				frm.set_value("state", details.state || "");
				frm.set_value("country", details.country || "");
				frm.set_value("zip_code", details.zip_code || "");
			},
		});
	},

	check_in_date(frm) { frm.trigger("calculate"); },
	check_out_date(frm) { frm.trigger("calculate"); },

	no_of_rooms(frm) {
		frm.trigger("calculate");
		ensure_rooming_list_rows(frm);
	},

	rate_per_night(frm) { frm.trigger("calculate"); },

	room_type(frm) {
		// Cascade the group's Default Room Type to any rooming-list rows that
		// don't already have a room_type set.
		const default_rt = frm.doc.room_type;
		if (!default_rt || !frm.doc.rooming_list) return;
		let touched = 0;
		frm.doc.rooming_list.forEach((row) => {
			if (!row.room_type) {
				row.room_type = default_rt;
				touched++;
			}
		});
		if (touched) frm.refresh_field("rooming_list");
	},

	rate_type(frm) {
		if (!frm.doc.rate_type) {
			frm.set_value("rate_per_night", 0);
			return;
		}
		frappe.db.get_doc("Rate Type", frm.doc.rate_type).then((rate) => {
			let resolved = parseFloat(rate.base_rate) || 0;
			// Fall back to the first rate_schedule row matching the group's room_type
			if (!resolved && Array.isArray(rate.rate_schedule) && rate.rate_schedule.length) {
				const match = rate.rate_schedule.find(
					(r) => !frm.doc.room_type || r.room_type === frm.doc.room_type
				) || rate.rate_schedule[0];
				resolved = parseFloat(match && match.rate) || 0;
			}
			frm.set_value("rate_per_night", resolved);
			if (!resolved) {
				frappe.show_alert({
					message: __("Rate Type '{0}' has no Base Rate or Rate Schedule entry. Please set one on the Rate Type.",
						[frm.doc.rate_type]),
					indicator: "orange",
				}, 7);
			}
		});
	},

	deposit_percent(frm) { recalc_deposit(frm); },
	deposit_amount(frm) { recalc_deposit(frm); },

	calculate(frm) {
		const { check_in_date, check_out_date, no_of_rooms, rate_per_night } = frm.doc;
		if (check_in_date && check_out_date) {
			const nights = frappe.datetime.get_day_diff(check_out_date, check_in_date);
			if (nights > 0) {
				frm.doc.days = nights;
				frm.refresh_field("days");
				if (no_of_rooms && rate_per_night) {
					frm.doc.total_room_revenue = nights * (no_of_rooms || 0) * (rate_per_night || 0);
					frm.refresh_field("total_room_revenue");
					recalc_deposit(frm);
				}
			}
		}
	},
});

// --- helpers ---------------------------------------------------------------

function ensure_rooming_list_rows(frm) {
	// Auto-add empty rows up to no_of_rooms; do not remove existing rows.
	const target = parseInt(frm.doc.no_of_rooms, 10) || 0;
	const current = (frm.doc.rooming_list || []).length;
	if (target <= current) return;

	const default_rt = frm.doc.room_type || "";
	for (let i = current; i < target; i++) {
		const row = frm.add_child("rooming_list");
		if (default_rt) row.room_type = default_rt;
		row.adults = row.adults || 1;
	}
	frm.refresh_field("rooming_list");
}

function recalc_deposit(frm) {
	const pct = parseFloat(frm.doc.deposit_percent || 0);
	const rev = parseFloat(frm.doc.total_room_revenue || 0);
	frm.doc.deposit_required = Math.round((rev * pct / 100) * 100) / 100;
	frm.doc.deposit_balance  = Math.round((frm.doc.deposit_required - parseFloat(frm.doc.deposit_amount || 0)) * 100) / 100;
	frm.refresh_field("deposit_required");
	frm.refresh_field("deposit_balance");
}

// ---------------------------------------------------------------------------
// Rooming List — Excel template download + bulk upload
// ---------------------------------------------------------------------------
function setup_rooming_list_excel_buttons(frm) {
	const grid = frm.fields_dict.rooming_list && frm.fields_dict.rooming_list.grid;
	if (!grid || !grid.wrapper) return;
	// Avoid duplicating buttons on every refresh
	const $wrap = grid.wrapper;
	if ($wrap.find(".ih-rooming-excel-bar").length) return;

	const $bar = $(`
		<div class="ih-rooming-excel-bar" style="display:flex; gap:8px; justify-content:flex-end; padding:6px 2px 2px;">
			<button type="button" class="btn btn-xs btn-default ih-rl-download">
				<i class="fa fa-download"></i> ${__("Download Template")}
			</button>
			<button type="button" class="btn btn-xs btn-primary ih-rl-upload">
				<i class="fa fa-upload"></i> ${__("Upload Excel")}
			</button>
		</div>
	`);
	$wrap.append($bar);

	$bar.find(".ih-rl-download").on("click", function() {
		const url = "/api/method/ihotel.ihotel.doctype.group_reservation.group_reservation.download_rooming_list_template";
		window.open(url + "?group_reservation_name=" + encodeURIComponent(frm.doc.name || ""), "_blank");
	});

	$bar.find(".ih-rl-upload").on("click", function() {
		if (frm.is_new()) {
			frappe.msgprint(__("Save the group reservation before uploading a rooming list."));
			return;
		}
		new frappe.ui.FileUploader({
			doctype: frm.doctype,
			docname: frm.doc.name,
			folder: "Home/Attachments",
			allow_multiple: false,
			restrictions: {
				allowed_file_types: [".xlsx", ".xls"],
			},
			on_success(file_doc) {
				frappe.call({
					method: "ihotel.ihotel.doctype.group_reservation.group_reservation.upload_rooming_list",
					args: {
						group_reservation_name: frm.doc.name,
						file_url: file_doc.file_url,
					},
					freeze: true,
					freeze_message: __("Importing rooming list..."),
					callback(r) {
						if (!r.message) return;
						const m = r.message;
						frappe.msgprint({
							title: __("Rooming List Import"),
							indicator: m.warnings.length ? "orange" : "green",
							message: `
								<p>${__("Imported {0} of {1} row(s).", [m.imported, m.total])}</p>
								${m.warnings.length ? `
									<p><b>${__("Skipped rows:")}</b></p>
									<ul style="padding-left:18px;">
										${m.warnings.map(w => `<li>${frappe.utils.escape_html(w)}</li>`).join("")}
									</ul>` : ""}
							`,
						});
						frm.reload_doc();
					},
				});
			},
		});
	});
}

function clear_group_contact_fields(frm) {
	frm.set_value("full_name", "");
	frm.set_value("company", "");
	frm.set_value("email", "");
	frm.set_value("phone_number", "");
	frm.set_value("address", "");
	frm.set_value("city", "");
	frm.set_value("state", "");
	frm.set_value("country", "");
	frm.set_value("zip_code", "");
}
