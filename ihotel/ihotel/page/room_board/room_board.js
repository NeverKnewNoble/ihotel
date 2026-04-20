frappe.pages["room_board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Room Board",
		single_column: true,
	});

	page.main.html(`
		<div class="rb-wrapper">

			<!-- Filter card -->
			<div class="rb-filter-card">

				<!-- Row 1: Search + dropdowns -->
				<div class="rb-filter-row">
					<div class="rb-search-wrap">
						<svg class="rb-search-icon" viewBox="0 0 24 24" fill="none"
							stroke="currentColor" stroke-width="2"
							stroke-linecap="round" stroke-linejoin="round">
							<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
						</svg>
						<input type="text" class="rb-search" placeholder="Search room number or guest…" autocomplete="off" />
					</div>
					<div class="rb-select-wrap">
						<svg class="rb-select-icon" viewBox="0 0 24 24" fill="none"
							stroke="currentColor" stroke-width="2"
							stroke-linecap="round" stroke-linejoin="round">
							<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
							<polyline points="9 22 9 12 15 12 15 22"/>
						</svg>
						<select class="rb-filter-type">
							<option value="">All Room Types</option>
						</select>
					</div>
					<div class="rb-select-wrap">
						<svg class="rb-select-icon" viewBox="0 0 24 24" fill="none"
							stroke="currentColor" stroke-width="2"
							stroke-linecap="round" stroke-linejoin="round">
							<line x1="8" y1="6" x2="21" y2="6"/>
							<line x1="8" y1="12" x2="21" y2="12"/>
							<line x1="8" y1="18" x2="21" y2="18"/>
							<line x1="3" y1="6" x2="3.01" y2="6"/>
							<line x1="3" y1="12" x2="3.01" y2="12"/>
							<line x1="3" y1="18" x2="3.01" y2="18"/>
						</svg>
						<select class="rb-filter-floor">
							<option value="">All Floors</option>
						</select>
					</div>
					<button class="rb-clear-btn" title="Clear filters">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
							stroke-linecap="round" stroke-linejoin="round">
							<line x1="18" y1="6" x2="6" y2="18"/>
							<line x1="6" y1="6" x2="18" y2="18"/>
						</svg>
						Clear
					</button>
				</div>

				<div class="rb-filter-divider"></div>

				<!-- Row 2: Status pills -->
				<div class="rb-filter-row rb-pills-row">
					<div class="rb-status-pills">
						<button class="rb-pill active" data-status="">
							All <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Available">
							<span class="rb-dot" style="background:#10b981;"></span>
							Available <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Occupied">
							<span class="rb-dot" style="background:#3b82f6;"></span>
							Occupied <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Vacant Dirty">
							<span class="rb-dot" style="background:#fb923c;"></span>
							Vacant Dirty <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Occupied Dirty">
							<span class="rb-dot" style="background:#f97316;"></span>
							Occ. Dirty <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Vacant Clean">
							<span class="rb-dot" style="background:#34d399;"></span>
							Vacant Clean <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Occupied Clean">
							<span class="rb-dot" style="background:#60a5fa;"></span>
							Occ. Clean <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Dirty">
							<span class="rb-dot" style="background:#f97316;"></span>
							Dirty <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Pickup">
							<span class="rb-dot" style="background:#a855f7;"></span>
							Pickup <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Inspected">
							<span class="rb-dot" style="background:#06b6d4;"></span>
							Inspected <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Housekeeping">
							<span class="rb-dot" style="background:#f59e0b;"></span>
							Housekeeping <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Out of Order">
							<span class="rb-dot" style="background:#ef4444;"></span>
							Out of Order <span class="rb-pill-count">0</span>
						</button>
						<button class="rb-pill" data-status="Out of Service">
							<span class="rb-dot" style="background:#6b7280;"></span>
							OOS <span class="rb-pill-count">0</span>
						</button>
					</div>
					<div class="rb-showing-count"></div>
				</div>

			</div>

			<!-- Grid -->
			<div class="rb-grid-container">
				<div class="rb-loading">Loading…</div>
			</div>

			<!-- Status Legend -->
			<div class="rb-legend">
				<div class="rb-legend-title">Status Legend</div>
				<div class="rb-legend-grid">
					<div class="rb-legend-item"><span class="rb-dot" style="background:#10b981;"></span><span><b>Available</b> — Clean &amp; ready for check-in</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#3b82f6;"></span><span><b>Occupied</b> — Guest currently in room</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#fb923c;"></span><span><b>Vacant Dirty</b> — Checked out, awaiting cleaning</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#f97316;"></span><span><b>Occupied Dirty</b> — Occupied, needs overnight cleaning</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#34d399;"></span><span><b>Vacant Clean</b> — Cleaned, pending inspection</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#60a5fa;"></span><span><b>Occupied Clean</b> — Occupied and cleaned</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#f97316;"></span><span><b>Dirty</b> — Needs cleaning</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#a855f7;"></span><span><b>Pickup</b> — Cleaning in progress</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#06b6d4;"></span><span><b>Inspected</b> — Cleaned &amp; inspector-approved</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#f59e0b;"></span><span><b>Housekeeping</b> — Scheduled maintenance clean</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#ef4444;"></span><span><b>Out of Order</b> — Cannot be sold (maintenance)</span></div>
					<div class="rb-legend-item"><span class="rb-dot" style="background:#6b7280;"></span><span><b>Out of Service</b> — Temporarily removed from inventory</span></div>
				</div>
			</div>

		</div>
	`);

	wrapper.room_board = new RoomBoard(page);
};

frappe.pages["room_board"].on_page_show = function (wrapper) {
	if (wrapper.room_board) {
		wrapper.room_board.refresh();
	}
};

// Statuses where a room is ready to accept a walk-in
const CHECK_IN_READY = new Set(["Available", "Inspected", "Pickup", "Vacant Clean", "Vacant Dirty"]);

class RoomBoard {
	constructor(page) {
		this.page = page;
		this.all_rooms = [];
		this.room_map  = {};   // name → room object, for dialog lookup
		this.active_status = "";

		this.$search       = page.main.find(".rb-search");
		this.$filter_type  = page.main.find(".rb-filter-type");
		this.$filter_floor = page.main.find(".rb-filter-floor");
		this.$pills        = page.main.find(".rb-status-pills");
		this.$showing      = page.main.find(".rb-showing-count");
		this.$grid         = page.main.find(".rb-grid-container");
		this.$clear        = page.main.find(".rb-clear-btn");

		this.page.set_secondary_action("Refresh", () => this.refresh());

		this.$search.on("input", () => this.apply_filters());
		this.$filter_type.on("change", () => this.apply_filters());
		this.$filter_floor.on("change", () => this.apply_filters());

		this.$pills.on("click", ".rb-pill", (e) => {
			this.$pills.find(".rb-pill").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.active_status = $(e.currentTarget).data("status");
			this.apply_filters();
		});

		this.$clear.on("click", () => {
			this.$search.val("");
			this.$filter_type.val("");
			this.$filter_floor.val("");
			this.$pills.find(".rb-pill").removeClass("active");
			this.$pills.find('[data-status=""]').addClass("active");
			this.active_status = "";
			this.apply_filters();
		});

		// Card navigation (skip when clicking the check-in button)
		this.$grid.on("click", ".rb-card[data-href]", (e) => {
			if ($(e.target).closest(".rb-checkin-btn").length) return;
			window.location.href = $(e.currentTarget).data("href");
		});

		// Check-in button — first ask whether it's a walk-in or from a reservation
		this.$grid.on("click", ".rb-checkin-btn", (e) => {
			e.stopPropagation();
			const room_name = $(e.currentTarget).data("room");
			this.show_checkin_mode_picker(this.room_map[room_name]);
		});

		this.refresh();
	}

	refresh() {
		this.$grid.html('<div class="rb-loading">Loading…</div>');
		frappe.call({
			method: "ihotel.ihotel.page.room_board.room_board.get_room_board_data",
			callback: (r) => {
				if (r.message) {
					this.all_rooms = r.message;
					this.room_map  = Object.fromEntries(r.message.map(rm => [rm.name, rm]));
					this.populate_dropdowns();
					this.apply_filters();
				}
			},
		});
	}

	populate_dropdowns() {
		const types = [...new Set(this.all_rooms.map(r => r.room_type).filter(Boolean))].sort();
		this.$filter_type.html('<option value="">All Room Types</option>');
		types.forEach(t => this.$filter_type.append(
			`<option value="${frappe.utils.escape_html(t)}">${frappe.utils.escape_html(t)}</option>`
		));

		const floors = [...new Set(this.all_rooms.map(r => r.floor).filter(Boolean))].sort((a, b) => {
			const na = parseInt(a), nb = parseInt(b);
			return (!isNaN(na) && !isNaN(nb)) ? na - nb : String(a).localeCompare(String(b));
		});
		this.$filter_floor.html('<option value="">All Floors</option>');
		floors.forEach(f => this.$filter_floor.append(
			`<option value="${frappe.utils.escape_html(f)}">Floor ${frappe.utils.escape_html(f)}</option>`
		));
	}

	apply_filters() {
		const search = this.$search.val().trim().toLowerCase();
		const type   = this.$filter_type.val();
		const floor  = this.$filter_floor.val();

		// Pre-status: apply search + type + floor only
		const pre = this.all_rooms.filter(room => {
			if (type  && room.room_type !== type) return false;
			if (floor && String(room.floor) !== String(floor)) return false;
			if (search) {
				const hay = [room.room_number, room.room_type, room.floor, room.guest, room.status]
					.filter(Boolean).join(" ").toLowerCase();
				if (!hay.includes(search)) return false;
			}
			return true;
		});

		// Update pill counts from pre-status set
		this.update_pill_counts(pre);

		// Apply status filter
		const filtered = this.active_status
			? pre.filter(r => r.status === this.active_status)
			: pre;

		this.$showing.text(
			filtered.length === this.all_rooms.length
				? `${filtered.length} rooms`
				: `${filtered.length} of ${this.all_rooms.length} rooms`
		);

		this.render_cards(filtered);
	}

	update_pill_counts(rooms) {
		const counts = {};
		rooms.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });

		this.$pills.find(".rb-pill").each((_, el) => {
			const s = $(el).data("status");
			const n = s ? (counts[s] || 0) : rooms.length;
			$(el).find(".rb-pill-count").text(n);
		});
	}

	render_cards(rooms) {
		if (!rooms.length) {
			this.$grid.html('<div class="rb-empty">No rooms match the current filters.</div>');
			return;
		}

		const status_colors = {
			"Available":      "#10b981",
			"Occupied":       "#3b82f6",
			"Vacant Dirty":   "#fb923c",
			"Occupied Dirty": "#f97316",
			"Vacant Clean":   "#34d399",
			"Occupied Clean": "#60a5fa",
			"Dirty":          "#f97316",
			"Pickup":         "#a855f7",
			"Inspected":      "#06b6d4",
			"Housekeeping":   "#f59e0b",
			"Out of Order":   "#ef4444",
			"Out of Service": "#6b7280",
		};

		const cards = rooms.map(room => {
			const color = status_colors[room.status] || "#6b7280";
			const href  = room.stay
				? `/app/checked-in/${encodeURIComponent(room.stay)}`
				: `/app/room/${encodeURIComponent(room.name)}`;

			const guest_html = room.guest
				? `<div class="rb-guest">${frappe.utils.escape_html(room.guest)}</div>`
				: "";
			const checkout_html = room.check_out
				? `<div class="rb-checkout">Out: ${frappe.datetime.str_to_user(room.check_out)}</div>`
				: "";
			const checkin_btn = CHECK_IN_READY.has(room.status)
				? `<button class="rb-checkin-btn" data-room="${frappe.utils.escape_html(room.name)}">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
							stroke-linecap="round" stroke-linejoin="round">
							<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
							<polyline points="10 17 15 12 10 7"/>
							<line x1="15" y1="12" x2="3" y2="12"/>
						</svg>
						Check In
					</button>`
				: "";

			const badges = [
				room.do_not_disturb ? `<span class="rb-badge rb-badge-dnd">DND</span>` : "",
				room.make_up_room   ? `<span class="rb-badge rb-badge-mur">MUR</span>` : "",
			].filter(Boolean).join("");
			const badges_html = badges ? `<div class="rb-badges">${badges}</div>` : "";

			return `
				<div class="rb-card" data-href="${href}"
					style="--rb-status-color:${color}; cursor:pointer;">
					<div class="rb-card-top">
						<div class="rb-room-number">${frappe.utils.escape_html(room.room_number || room.name)}</div>
						<div class="rb-status-dot-sm" style="background:${color};"></div>
					</div>
					<div class="rb-room-type">${frappe.utils.escape_html(room.room_type || "")}</div>
					<div class="rb-floor">Floor ${frappe.utils.escape_html(room.floor || "—")}</div>
					<div class="rb-status-label" style="color:${color};">${frappe.utils.escape_html(room.status)}</div>
					${guest_html}
					${checkout_html}
					${badges_html}
					${checkin_btn}
				</div>`;
		}).join("");

		this.$grid.html(`<div class="rb-grid">${cards}</div>`);
	}

	show_checkin_mode_picker(room) {
		const d = new frappe.ui.Dialog({
			title: `Check In — Room ${frappe.utils.escape_html(room.room_number || room.name)}`,
			fields: [{ fieldtype: "HTML", fieldname: "mode_picker" }],
			primary_action_label: __("Continue"),
			primary_action: () => {
				const mode = d.$wrapper.find('input[name="rb-ci-mode"]:checked').val();
				d.hide();
				if (mode === "reservation") {
					this.show_reservation_check_in_dialog(room);
				} else {
					this.show_check_in_dialog(room);
				}
			},
		});
		d.fields_dict.mode_picker.$wrapper.html(`
			<div class="rb-mode-picker" style="padding:4px 0 8px 0;">
				<label style="display:block; padding:10px 12px; border:1px solid var(--border-color); border-radius:6px; margin-bottom:8px; cursor:pointer;">
					<input type="radio" name="rb-ci-mode" value="walkin" checked style="margin-right:8px;">
					<strong>${__("Walk-in / New Check-in")}</strong>
					<div style="color: var(--text-muted); font-size: 0.85em; margin-left:22px;">
						${__("Create a new stay for a guest without a reservation.")}
					</div>
				</label>
				<label style="display:block; padding:10px 12px; border:1px solid var(--border-color); border-radius:6px; cursor:pointer;">
					<input type="radio" name="rb-ci-mode" value="reservation" style="margin-right:8px;">
					<strong>${__("From existing Reservation")}</strong>
					<div style="color: var(--text-muted); font-size: 0.85em; margin-left:22px;">
						${__("Convert a Reservation into a checked-in stay for this room.")}
					</div>
				</label>
			</div>
		`);
		d.show();
	}

	show_reservation_check_in_dialog(room) {
		const target_room = room.name;
		const d = new frappe.ui.Dialog({
			title: __("Check In from Reservation — Room {0}", [room.room_number || room.name]),
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
								d.set_value("guest_name", (r.message || {}).guest_name || "");
							},
						});
					},
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
			primary_action: (values) => {
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
					args: { reservation_name: values.reservation, override_room: target_room },
					freeze: true,
					freeze_message: __("Converting reservation to check-in…"),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("Guest checked in successfully."),
								indicator: "green",
							}, 5);
							frappe.set_route("Form", "Checked In", r.message);
						}
					},
				});
			},
		});
		d.show();
	}

	show_check_in_dialog(room) {
		const rack_rate = room.rack_rate || 0;

		const d = new frappe.ui.Dialog({
			title: `Check In — Room ${frappe.utils.escape_html(room.room_number || room.name)}`,
			fields: [
				// ── Guest & Room ──────────────────────────────────────────
				{
					fieldtype: "Section Break",
					label: "Guest & Room",
				},
				{
					fieldtype: "Link",
					fieldname: "guest",
					label: "Guest",
					options: "Guest",
					reqd: 1,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Data",
					fieldname: "room_display",
					label: "Room",
					default: `${room.room_number || room.name}  (${room.room_type || ""}, Floor ${room.floor || "—"})`,
					read_only: 1,
				},

				// ── Stay Dates ────────────────────────────────────────────
				{
					fieldtype: "Section Break",
					label: "Stay Dates",
				},
				{
					fieldtype: "Datetime",
					fieldname: "expected_check_in",
					label: "Check In",
					reqd: 1,
					default: frappe.datetime.now_datetime(),
					onchange: function () {
						recalc_nights(d);
						resolve_rate(d, room);
					},
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Datetime",
					fieldname: "expected_check_out",
					label: "Check Out",
					reqd: 1,
					onchange: function () {
						recalc_nights(d);
						resolve_rate(d, room);
					},
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Int",
					fieldname: "nights",
					label: "Nights",
					read_only: 1,
					default: 0,
				},

				// ── Occupants ─────────────────────────────────────────────
				{
					fieldtype: "Section Break",
					label: "Occupants",
				},
				{
					fieldtype: "Int",
					fieldname: "adults",
					label: "Adults",
					default: 1,
					reqd: 1,
					onchange: function () {
						resolve_rate(d, room);
					},
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Int",
					fieldname: "children",
					label: "Children",
					default: 0,
				},

				// ── Rate ──────────────────────────────────────────────────
				{
					fieldtype: "Section Break",
					label: "Rate",
				},
				{
					fieldtype: "Link",
					fieldname: "rate_type",
					label: "Rate Type",
					options: "Rate Type",
					reqd: 1,
					onchange: function () {
						resolve_rate(d, room);
					},
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Currency",
					fieldname: "room_rate",
					label: "Room Rate / Night",
					reqd: 1,
					default: rack_rate || 0,
					description: rack_rate
						? `Rack rate: ${format_currency(rack_rate)}`
						: "",
				},
				{
					fieldtype: "HTML",
					fieldname: "rate_info",
					options: "",
				},
				// Hidden fields populated by resolve_rate so the backend can build a full rate_line
				// (rate_type + rate_column + description) and compute tax from the tax schedule.
				{ fieldtype: "Data", fieldname: "rate_column",      hidden: 1 },
				{ fieldtype: "Data", fieldname: "rate_description", hidden: 1 },

				// ── Other ─────────────────────────────────────────────────
				{
					fieldtype: "Section Break",
					label: "Other",
				},
				{
					fieldtype: "Link",
					fieldname: "business_source",
					label: "Business Source",
					options: "Business Source Category",
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Currency",
					fieldname: "deposit_amount",
					label: "Deposit",
					default: 0,
				},
			],
			primary_action_label: "Check In",
			primary_action(values) {
				frappe.call({
					method: "ihotel.ihotel.page.room_board.room_board.quick_check_in",
					args: {
						room: room.name,
						guest: values.guest,
						expected_check_in: values.expected_check_in,
						expected_check_out: values.expected_check_out,
						rate_type: values.rate_type,
						room_rate: values.room_rate,
						rate_column: values.rate_column || null,
						rate_description: values.rate_description || null,
						adults: values.adults || 1,
						children: values.children || 0,
						business_source: values.business_source || null,
						deposit_amount: values.deposit_amount || 0,
					},
					btn: d.get_primary_btn(),
					callback(r) {
						if (r.message) {
							d.hide();
							frappe.show_alert({
								message: __("Checked In: {0}", [r.message]),
								indicator: "green",
							});
							frappe.set_route(`/app/checked-in/${encodeURIComponent(r.message)}`);
						}
					},
				});
			},
		});

		d.show();
	}
}

// ─── Dialog helpers ───────────────────────────────────────────────────────

function format_currency(val) {
	return frappe.format(val, { fieldtype: "Currency" });
}

function recalc_nights(d) {
	const ci = d.get_value("expected_check_in");
	const co = d.get_value("expected_check_out");
	if (!ci || !co) return;
	const diff = frappe.datetime.get_day_diff(co.split(" ")[0], ci.split(" ")[0]);
	if (diff > 0) d.set_value("nights", diff);
}

function resolve_rate(d, room) {
	const rate_type = d.get_value("rate_type");

	if (!rate_type) {
		d.fields_dict.rate_info.wrapper.innerHTML = "";
		return;
	}

	const check_in_dt = d.get_value("expected_check_in");
	const check_date  = check_in_dt ? check_in_dt.split(" ")[0] : frappe.datetime.get_today();
	const adults      = d.get_value("adults") || 1;

	frappe.db.get_doc("Rate Type", rate_type).then(rate => {
		// Find the first matching schedule row (by room_type + date range), then pick
		// the per-night rate column based on occupancy — same logic as the Checked In form.
		let matched = null;
		if (rate.rate_schedule && rate.rate_schedule.length) {
			for (const row of rate.rate_schedule) {
				const type_match = !row.room_type || row.room_type === room.room_type;
				const in_range   = (!row.from_date || row.from_date <= check_date) &&
				                   (!row.to_date   || row.to_date   >= check_date);
				if (type_match && in_range) {
					matched = row;
					break;
				}
			}
		}

		let resolved = null;
		let rate_column = "Single / Base Rate";
		if (matched) {
			if (adults > 1 && matched.double_rate) {
				resolved = matched.double_rate;
				rate_column = "Double Rate";
			} else {
				resolved = matched.rate || rate.base_rate || 0;
			}
		}
		if (!resolved && rate.base_rate) resolved = rate.base_rate;

		// Per Person pricing multiplies by adult count
		if (resolved && rate.pricing_method === "Per Person") {
			resolved = resolved * adults;
		}

		if (resolved) d.set_value("room_rate", resolved);
		d.set_value("rate_column", rate_column);
		d.set_value("rate_description", rate.rate_type_name || rate.name);

		// Build info badge
		const badges = [];
		if (rate.includes_breakfast) badges.push(`<span class="badge badge-info" style="margin-right:4px;">Breakfast incl.</span>`);
		if (rate.includes_taxes)     badges.push(`<span class="badge badge-info" style="margin-right:4px;">Tax incl.</span>`);
		if (rate.minimum_stay_nights) badges.push(`<span class="badge badge-warning" style="margin-right:4px;">Min ${rate.minimum_stay_nights} nights</span>`);
		if (rate.pricing_method)     badges.push(`<span class="badge badge-default" style="margin-right:4px;">${rate.pricing_method}</span>`);

		const sell_msg = rate.sell_message
			? `<div style="margin-top:6px; color: var(--text-muted); font-size: 0.85em; font-style: italic;">${frappe.utils.escape_html(rate.sell_message)}</div>`
			: "";

		d.fields_dict.rate_info.wrapper.innerHTML = `
			<div style="padding: 6px 0 2px 0;">
				${badges.join("")}
				${sell_msg}
			</div>`;
	});
}
