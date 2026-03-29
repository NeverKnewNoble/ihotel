frappe.pages["housekeeping-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Housekeeping Board",
		single_column: true,
	});

	page.main.html(`
		<div class="hkb-wrapper">

			<!-- Stats bar -->
			<div class="hkb-stats-bar">
				<div class="hkb-stat" data-status="Available">
					<div class="hkb-stat-dot" style="background:#10b981;"></div>
					<div class="hkb-stat-label">Available</div>
					<div class="hkb-stat-count" data-key="Available">0</div>
				</div>
				<div class="hkb-stat" data-status="Vacant Dirty">
					<div class="hkb-stat-dot" style="background:#fb923c;"></div>
					<div class="hkb-stat-label">Vacant Dirty</div>
					<div class="hkb-stat-count" data-key="Vacant Dirty">0</div>
				</div>
				<div class="hkb-stat" data-status="Occupied Dirty">
					<div class="hkb-stat-dot" style="background:#f97316;"></div>
					<div class="hkb-stat-label">Occupied Dirty</div>
					<div class="hkb-stat-count" data-key="Occupied Dirty">0</div>
				</div>
				<div class="hkb-stat" data-status="Vacant Clean">
					<div class="hkb-stat-dot" style="background:#34d399;"></div>
					<div class="hkb-stat-label">Vacant Clean</div>
					<div class="hkb-stat-count" data-key="Vacant Clean">0</div>
				</div>
				<div class="hkb-stat" data-status="Occupied Clean">
					<div class="hkb-stat-dot" style="background:#60a5fa;"></div>
					<div class="hkb-stat-label">Occupied Clean</div>
					<div class="hkb-stat-count" data-key="Occupied Clean">0</div>
				</div>
				<div class="hkb-stat" data-status="Pickup">
					<div class="hkb-stat-dot" style="background:#a855f7;"></div>
					<div class="hkb-stat-label">Pickup</div>
					<div class="hkb-stat-count" data-key="Pickup">0</div>
				</div>
				<div class="hkb-stat" data-status="Inspected">
					<div class="hkb-stat-dot" style="background:#06b6d4;"></div>
					<div class="hkb-stat-label">Inspected</div>
					<div class="hkb-stat-count" data-key="Inspected">0</div>
				</div>
				<div class="hkb-stat" data-status="Housekeeping">
					<div class="hkb-stat-dot" style="background:#f59e0b;"></div>
					<div class="hkb-stat-label">Housekeeping</div>
					<div class="hkb-stat-count" data-key="Housekeeping">0</div>
				</div>
				<div class="hkb-stat" data-status="Occupied">
					<div class="hkb-stat-dot" style="background:#3b82f6;"></div>
					<div class="hkb-stat-label">Occupied</div>
					<div class="hkb-stat-count" data-key="Occupied">0</div>
				</div>
				<div class="hkb-stat" data-status="Out of Order">
					<div class="hkb-stat-dot" style="background:#ef4444;"></div>
					<div class="hkb-stat-label">Out of Order</div>
					<div class="hkb-stat-count" data-key="Out of Order">0</div>
				</div>
				<div class="hkb-stat" data-status="Out of Service">
					<div class="hkb-stat-dot" style="background:#6b7280;"></div>
					<div class="hkb-stat-label">Out of Service</div>
					<div class="hkb-stat-count" data-key="Out of Service">0</div>
				</div>
			</div>

			<!-- Filter card -->
			<div class="hkb-filter-card">
				<div class="hkb-filter-row">
					<div class="hkb-select-wrap">
						<select class="hkb-filter-floor"><option value="">All Floors</option></select>
					</div>
					<div class="hkb-select-wrap">
						<select class="hkb-filter-type"><option value="">All Room Types</option></select>
					</div>
					<button class="hkb-clear-btn">Clear</button>
					<div class="hkb-bulk-wrap" style="display:none;">
						<select class="hkb-bulk-status">
							<option value="">Change selected to…</option>
							<option>Available</option>
							<option>Vacant Dirty</option>
							<option>Occupied Dirty</option>
							<option>Vacant Clean</option>
							<option>Occupied Clean</option>
							<option>Pickup</option>
							<option>Inspected</option>
							<option>Housekeeping</option>
							<option>Out of Order</option>
							<option>Out of Service</option>
						</select>
						<button class="hkb-bulk-apply btn btn-xs btn-primary">Apply</button>
					</div>
					<div class="hkb-showing"></div>
				</div>
				<div class="hkb-filter-divider"></div>
				<div class="hkb-filter-row hkb-pills-row">
					<div class="hkb-pills">
						<button class="hkb-pill active" data-status="">All <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Available"><span class="hkb-dot" style="background:#10b981;"></span>Available <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Vacant Dirty"><span class="hkb-dot" style="background:#fb923c;"></span>Vacant Dirty <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Occupied Dirty"><span class="hkb-dot" style="background:#f97316;"></span>Occupied Dirty <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Vacant Clean"><span class="hkb-dot" style="background:#34d399;"></span>Vacant Clean <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Occupied Clean"><span class="hkb-dot" style="background:#60a5fa;"></span>Occupied Clean <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Pickup"><span class="hkb-dot" style="background:#a855f7;"></span>Pickup <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Inspected"><span class="hkb-dot" style="background:#06b6d4;"></span>Inspected <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Housekeeping"><span class="hkb-dot" style="background:#f59e0b;"></span>Housekeeping <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Occupied"><span class="hkb-dot" style="background:#3b82f6;"></span>Occupied <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Out of Order"><span class="hkb-dot" style="background:#ef4444;"></span>Out of Order <span class="hkb-pill-count">0</span></button>
						<button class="hkb-pill" data-status="Out of Service"><span class="hkb-dot" style="background:#6b7280;"></span>Out of Service <span class="hkb-pill-count">0</span></button>
					</div>
				</div>
			</div>

			<!-- Grid -->
			<div class="hkb-grid-container">
				<div class="hkb-loading">Loading…</div>
			</div>

		</div>
	`);

	wrapper.hkb = new HKBoard(page);
};

frappe.pages["housekeeping-board"].on_page_show = function (wrapper) {
	if (wrapper.hkb) wrapper.hkb.refresh();
};

class HKBoard {
	constructor(page) {
		this.page = page;
		this.all_rooms = [];
		this.active_status = "";
		this.selected = new Set();

		this.$filter_floor = page.main.find(".hkb-filter-floor");
		this.$filter_type  = page.main.find(".hkb-filter-type");
		this.$pills        = page.main.find(".hkb-pills");
		this.$showing      = page.main.find(".hkb-showing");
		this.$grid         = page.main.find(".hkb-grid-container");
		this.$clear        = page.main.find(".hkb-clear-btn");
		this.$bulk_wrap    = page.main.find(".hkb-bulk-wrap");
		this.$bulk_status  = page.main.find(".hkb-bulk-status");
		this.$bulk_apply   = page.main.find(".hkb-bulk-apply");
		this.$stats        = page.main.find(".hkb-stats-bar");

		this.page.set_secondary_action("Refresh", () => this.refresh());

		this.$filter_floor.on("change", () => this.apply_filters());
		this.$filter_type.on("change", () => this.apply_filters());

		this.$pills.on("click", ".hkb-pill", (e) => {
			this.$pills.find(".hkb-pill").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.active_status = $(e.currentTarget).data("status");
			this.apply_filters();
		});

		this.$stats.on("click", ".hkb-stat", (e) => {
			const s = $(e.currentTarget).data("status");
			this.$pills.find(".hkb-pill").removeClass("active");
			this.$pills.find(`[data-status="${s}"]`).addClass("active");
			this.active_status = s;
			this.apply_filters();
		});

		this.$clear.on("click", () => {
			this.$filter_floor.val("");
			this.$filter_type.val("");
			this.$pills.find(".hkb-pill").removeClass("active");
			this.$pills.find('[data-status=""]').addClass("active");
			this.active_status = "";
			this.selected.clear();
			this.apply_filters();
		});

		this.$bulk_apply.on("click", () => this.bulk_change());

		this.refresh();
	}

	refresh() {
		this.$grid.html('<div class="hkb-loading">Loading…</div>');
		frappe.call({
			method: "ihotel.ihotel.page.housekeeping_board.housekeeping_board.get_hk_board_data",
			callback: (r) => {
				if (r.message) {
					this.all_rooms = r.message;
					this.selected.clear();
					this.populate_dropdowns();
					this.update_stats();
					this.apply_filters();
				}
			},
		});
	}

	populate_dropdowns() {
		const floors = [...new Set(this.all_rooms.map(r => r.floor).filter(Boolean))].sort((a,b) => {
			const na = parseInt(a), nb = parseInt(b);
			return (!isNaN(na) && !isNaN(nb)) ? na - nb : String(a).localeCompare(String(b));
		});
		this.$filter_floor.html('<option value="">All Floors</option>');
		floors.forEach(f => this.$filter_floor.append(
			`<option value="${frappe.utils.escape_html(f)}">Floor ${frappe.utils.escape_html(f)}</option>`
		));

		const types = [...new Set(this.all_rooms.map(r => r.room_type).filter(Boolean))].sort();
		this.$filter_type.html('<option value="">All Room Types</option>');
		types.forEach(t => this.$filter_type.append(
			`<option value="${frappe.utils.escape_html(t)}">${frappe.utils.escape_html(t)}</option>`
		));
	}

	update_stats() {
		const counts = {};
		this.all_rooms.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
		this.page.main.find(".hkb-stat-count").each((_, el) => {
			const key = $(el).data("key");
			$(el).text(counts[key] || 0);
		});
	}

	apply_filters() {
		const floor = this.$filter_floor.val();
		const type  = this.$filter_type.val();

		const pre = this.all_rooms.filter(r => {
			if (floor && String(r.floor) !== String(floor)) return false;
			if (type  && r.room_type !== type) return false;
			return true;
		});

		// Update pill counts
		const counts = {};
		pre.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
		this.$pills.find(".hkb-pill").each((_, el) => {
			const s = $(el).data("status");
			$(el).find(".hkb-pill-count").text(s ? (counts[s] || 0) : pre.length);
		});

		const filtered = this.active_status ? pre.filter(r => r.status === this.active_status) : pre;

		this.$showing.text(
			filtered.length === this.all_rooms.length
				? `${filtered.length} rooms`
				: `${filtered.length} of ${this.all_rooms.length} rooms`
		);

		this.render_cards(filtered);
	}

	render_cards(rooms) {
		if (!rooms.length) {
			this.$grid.html('<div class="hkb-empty">No rooms match the current filters.</div>');
			return;
		}

		const colors = {
			"Available":      "#10b981",
			"Occupied":       "#3b82f6",
			"Vacant Dirty":   "#fb923c",
			"Occupied Dirty": "#f97316",
			"Vacant Clean":   "#34d399",
			"Occupied Clean": "#60a5fa",
			"Pickup":         "#a855f7",
			"Inspected":      "#06b6d4",
			"Housekeeping":   "#f59e0b",
			"Out of Order":   "#ef4444",
			"Out of Service": "#6b7280",
		};

		const status_opts = ["Available","Vacant Dirty","Occupied Dirty","Vacant Clean","Occupied Clean","Pickup","Inspected","Housekeeping","Out of Order","Out of Service"];

		const cards = rooms.map(room => {
			const color = colors[room.status] || "#6b7280";
			const checked = this.selected.has(room.name) ? "checked" : "";
			const guest_html = room.guest
				? `<div class="hkb-guest">${frappe.utils.escape_html(room.guest)}</div>`
				: "";
			const badges = [];
			if (room.do_not_disturb) badges.push(`<span class="hkb-badge hkb-dnd">DND</span>`);
			if (room.make_up_room)   badges.push(`<span class="hkb-badge hkb-mur">MUR</span>`);
			if (room.turndown_requested) badges.push(`<span class="hkb-badge hkb-td">TD</span>`);
			const badges_html = badges.length ? `<div class="hkb-badges">${badges.join("")}</div>` : "";

			const opts = status_opts.map(s =>
				`<option value="${s}" ${s === room.status ? "selected" : ""}>${s}</option>`
			).join("");

			return `
				<div class="hkb-card" data-room="${frappe.utils.escape_html(room.name)}" style="--hkb-color:${color};">
					<div class="hkb-card-header">
						<input type="checkbox" class="hkb-check" ${checked} />
						<div class="hkb-room-num">${frappe.utils.escape_html(room.room_number || room.name)}</div>
						<div class="hkb-status-dot" style="background:${color};"></div>
					</div>
					<div class="hkb-room-type">${frappe.utils.escape_html(room.room_type || "")}</div>
					<div class="hkb-floor">Floor ${frappe.utils.escape_html(room.floor || "—")}</div>
					${guest_html}
					${badges_html}
					<select class="hkb-status-select" title="Change status">${opts}</select>
				</div>`;
		}).join("");

		this.$grid.html(`<div class="hkb-grid">${cards}</div>`);

		// Inline status change
		this.$grid.find(".hkb-status-select").on("change", (e) => {
			const card = $(e.target).closest(".hkb-card");
			const room = card.data("room");
			const status = $(e.target).val();
			this.change_status(room, status, card);
		});

		// Checkbox selection
		this.$grid.find(".hkb-check").on("change", (e) => {
			const room = $(e.target).closest(".hkb-card").data("room");
			if ($(e.target).is(":checked")) {
				this.selected.add(room);
			} else {
				this.selected.delete(room);
			}
			this.$bulk_wrap.toggle(this.selected.size > 0);
		});
	}

	change_status(room, status, $card) {
		frappe.call({
			method: "ihotel.ihotel.page.housekeeping_board.housekeeping_board.update_room_status",
			args: { room, status },
			callback: (r) => {
				if (r.message) {
					// Update in local data
					const idx = this.all_rooms.findIndex(x => x.name === room);
					if (idx >= 0) this.all_rooms[idx].status = status;
					this.update_stats();
					this.apply_filters();
					frappe.show_alert({ message: `Room ${room} → ${status}`, indicator: "green" });
				}
			},
		});
	}

	bulk_change() {
		const status = this.$bulk_status.val();
		if (!status) {
			frappe.msgprint(__("Please select a status to apply."));
			return;
		}
		if (!this.selected.size) return;

		frappe.call({
			method: "ihotel.ihotel.page.housekeeping_board.housekeeping_board.bulk_update_room_status",
			args: { rooms: JSON.stringify([...this.selected]), status },
			callback: (r) => {
				if (r.message) {
					this.selected.clear();
					this.$bulk_wrap.hide();
					this.$bulk_status.val("");
					this.refresh();
					frappe.show_alert({ message: `${r.message.updated} rooms updated to ${status}`, indicator: "green" });
				}
			},
		});
	}
}
