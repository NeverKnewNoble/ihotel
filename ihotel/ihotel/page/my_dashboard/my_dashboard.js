function format_currency(value) {
	const symbol = frappe.boot.sysdefaults.currency_symbol || frappe.boot.sysdefaults.currency || "";
	const num = parseFloat(value) || 0;
	return symbol + " " + num.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

frappe.pages["my-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Dashboard",
		single_column: true,
	});

	page.main.html('<div class="ihotel-dash"><div class="ih-loading">' +
		'<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
		'<path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Loading dashboard...</div></div>');

	wrapper.dashboard = new IHotelDashboard(page);
};

frappe.pages["my-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.dashboard) {
		wrapper.dashboard.refresh();
	}
};

class IHotelDashboard {
	constructor(page) {
		this.page = page;
		this.container = page.main.find(".ihotel-dash");
		this.chart = null;
		this.selected_date = frappe.datetime.nowdate();
		this.refresh();
	}

	refresh() {
		frappe.call({
			method: "ihotel.ihotel.page.my_dashboard.my_dashboard.get_dashboard_data",
			args: { selected_date: this.selected_date },
			callback: (r) => {
				if (r.message) {
					this.data = r.message;
					this.render();
				}
			},
			error: () => {
				this.container.html('<div class="ih-empty">Failed to load dashboard data.</div>');
			},
		});
	}

	render() {
		const d = this.data;
		const today_iso = frappe.datetime.nowdate();

		this.container.html(`
			<!-- Header -->
			<div class="ih-header">
				<div class="ih-header-left">
					<h2>${frappe.utils.escape_html(d.hotel_name)}</h2>
					<div class="ih-date">
						<input type="date" class="ih-date-input"
							value="${this.selected_date}" max="${today_iso}" />
					</div>
				</div>
				<button class="ih-refresh-btn" data-action="refresh">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
						stroke-linecap="round" stroke-linejoin="round">
						<polyline points="23 4 23 10 17 10"/>
						<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
					</svg>
					Refresh
				</button>
			</div>

			<!-- KPI Cards -->
			<div class="ih-kpi-grid">
				${this.kpi_card("Occupancy", d.occupancy_rate + "%",
					d.occupied_rooms + " of " + d.total_rooms + " rooms", "blue",
					'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>')}
				${this.kpi_card("In-House", d.in_house_count,
					"Guests currently checked in", "teal",
					'<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>')}
				${this.kpi_card("Tonight's Revenue", format_currency(d.todays_revenue),
					"Nightly room rates, in-house stays", "green",
					'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>')}
				${this.kpi_card("Arrivals Today", d.arrivals_today,
					d.departures_today + " departure(s) expected", "amber",
					'<path d="M16 3h5v5"/><path d="M4 20L21 3"/><path d="M21 16v5h-5"/><path d="M15 15l6 6"/><path d="M4 4l5 5"/>')}
				${this.kpi_card("ADR", format_currency(d.adr),
					"Average Daily Rate (in-house)", "teal",
					'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>')}
				${this.kpi_card("RevPAR", format_currency(d.revpar),
					"Revenue Per Available Room", "blue",
					'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>')}
			</div>

			<!-- Room Status + Operations -->
			<div class="ih-section-grid">
				<!-- Room Status -->
				<div class="ih-card">
					<div class="ih-card-header">
						<div class="ih-card-title">Room Status</div>
						<a class="ih-card-link" href="/app/room">View All Rooms</a>
					</div>
					<div class="ih-card-body">
						<div id="ih-room-chart" class="ih-chart-container"></div>
						<div class="ih-status-bars" style="margin-top: 16px;">
							${this.status_bar("Available",      d.room_status.Available,           d.total_rooms, "available")}
							${this.status_bar("Occupied",       d.room_status.Occupied,            d.total_rooms, "occupied")}
							${this.status_bar("DND",            d.room_status.DND,                 d.total_rooms, "dnd")}
							${this.status_bar("Vacant Dirty",   d.room_status["Vacant Dirty"],     d.total_rooms, "vacant-dirty")}
							${this.status_bar("Occupied Dirty", d.room_status["Occupied Dirty"],   d.total_rooms, "occupied-dirty")}
							${this.status_bar("Out of Order",   d.room_status["Out of Order"],     d.total_rooms, "out-of-order")}
						</div>
					</div>
				</div>

				<!-- Operations Summary -->
				<div class="ih-card">
					<div class="ih-card-header">
						<div class="ih-card-title">Operations</div>
					</div>
					<div class="ih-card-body">
						<!-- Housekeeping -->
						<div class="ih-ops-section">
							<div class="ih-ops-title">
								<svg viewBox="0 0 24 24" fill="none" stroke="var(--ih-amber)" stroke-width="2"
									stroke-linecap="round" stroke-linejoin="round">
									<path d="M9 11l3 3L22 4"/>
									<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
								</svg>
								Housekeeping
							</div>
							<div class="ih-ops-items">
								${this.ops_item("Pending",     d.housekeeping.Pending,        "pending")}
								${this.ops_item("In Progress", d.housekeeping["In Progress"],  "in-progress")}
								${this.ops_item("Completed",   d.housekeeping.Completed,       "completed")}
							</div>
						</div>
						<!-- Maintenance -->
						<div class="ih-ops-section">
							<div class="ih-ops-title">
								<svg viewBox="0 0 24 24" fill="none" stroke="var(--ih-red)" stroke-width="2"
									stroke-linecap="round" stroke-linejoin="round">
									<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
								</svg>
								Maintenance
							</div>
							<div class="ih-ops-items">
								${this.ops_item("Open",        d.maintenance.Open,            "open")}
								${this.ops_item("In Progress", d.maintenance["In Progress"],   "in-progress")}
								${this.ops_item("Resolved",    d.maintenance.Resolved,         "resolved")}
								${this.ops_item("Closed",      d.maintenance.Closed,           "closed")}
							</div>
							${d.critical_maintenance > 0 ? `
							<div class="ih-critical">
								<svg viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
									<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
								</svg>
								<span>${d.critical_maintenance} critical request${d.critical_maintenance !== 1 ? "s" : ""} need attention</span>
							</div>` : ""}
						</div>
					</div>
				</div>
			</div>

			<!-- Active Stays -->
			<div class="ih-section-full">
				<div class="ih-card">
					<div class="ih-card-header">
						<div class="ih-card-title">Active Stays</div>
						<a class="ih-card-link" href="/app/checked-in?status=%5B%22in%22%2C%5B%22Reserved%22%2C%22Checked%20In%22%5D%5D&docstatus=1">View All</a>
					</div>
					<div class="ih-card-body" style="padding: 0;">
						${this.render_stays_table(d.active_stays)}
					</div>
				</div>
			</div>

			<!-- Recent Night Audits -->
			<div class="ih-section-full">
				<div class="ih-card">
					<div class="ih-card-header">
						<div class="ih-card-title">Recent Night Audits</div>
						<a class="ih-card-link" href="/app/night-audit">View All</a>
					</div>
					<div class="ih-card-body" style="padding: 0;">
						${this.render_audits_table(d.recent_audits)}
					</div>
				</div>
			</div>
		`);

		// Bind refresh
		this.container.find('[data-action="refresh"]').on("click", () => {
			const btn = this.container.find('[data-action="refresh"]');
			btn.addClass("spinning");
			this.refresh();
			setTimeout(() => btn.removeClass("spinning"), 800);
		});

		// Bind date selector
		this.container.find('.ih-date-input').on("change", (e) => {
			const val = e.target.value;
			if (val) {
				this.selected_date = val;
				this.refresh();
			}
		});

		// Render donut chart
		this.render_room_chart(d);
	}

	// --- KPI card helper ---
	kpi_card(label, value, sub, color, icon_svg) {
		return `
		<div class="ih-kpi-card">
			<div class="ih-kpi-icon ${color}">
				<svg viewBox="0 0 24 24" stroke-width="2"
					stroke-linecap="round" stroke-linejoin="round">
					${icon_svg}
				</svg>
			</div>
			<div class="ih-kpi-content">
				<div class="ih-kpi-label">${label}</div>
				<div class="ih-kpi-value">${value}</div>
				<div class="ih-kpi-sub">${sub}</div>
			</div>
		</div>`;
	}

	// --- Status bar helper ---
	status_bar(label, count, total, cls) {
		const pct = total > 0 ? Math.round((count / total) * 100) : 0;
		return `
		<div class="ih-status-row">
			<div class="ih-status-dot ${cls}"></div>
			<div class="ih-status-label">${label}</div>
			<div class="ih-status-count">${count}</div>
			<div class="ih-status-bar-track">
				<div class="ih-status-bar-fill ${cls}" style="width: ${pct}%"></div>
			</div>
		</div>`;
	}

	// --- Operations item helper ---
	ops_item(label, count, cls) {
		return `
		<div class="ih-ops-item">
			<div class="ih-ops-item-label">${label}</div>
			<div class="ih-ops-item-count ${cls}">${count}</div>
		</div>`;
	}

	// --- Active stays table ---
	render_stays_table(stays) {
		if (!stays || !stays.length) {
			return '<div class="ih-empty">No active stays</div>';
		}
		let rows = stays.map((s) => {
			const badge_cls = s.status === "Checked In" ? "checked" : "reserved";
			const checkin  = s.expected_check_in  ? frappe.datetime.str_to_user(s.expected_check_in)  : "-";
			const checkout = s.expected_check_out ? frappe.datetime.str_to_user(s.expected_check_out) : "-";
			return `<tr>
				<td><a href="/app/checked-in/${encodeURIComponent(s.name)}">${frappe.utils.escape_html(s.guest || s.name)}</a></td>
				<td>${frappe.utils.escape_html(s.room || "-")}</td>
				<td>${frappe.utils.escape_html(s.room_type || "-")}</td>
				<td><span class="ih-badge ${badge_cls}">${s.status}</span></td>
				<td>${checkin}</td>
				<td>${checkout}</td>
				<td>${s.nights || "-"}</td>
				<td>${format_currency(s.room_rate)}</td>
			</tr>`;
		}).join("");

		return `<table class="ih-table">
			<thead><tr>
				<th>Guest</th><th>Room</th><th>Room Type</th><th>Status</th>
				<th>Check-in</th><th>Check-out</th><th>Nights</th><th>Rate</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
	}

	// --- Night audits table ---
	render_audits_table(audits) {
		if (!audits || !audits.length) {
			return '<div class="ih-empty">No night audits yet</div>';
		}
		let rows = audits.map((a) => {
			const date = a.audit_date ? frappe.datetime.str_to_user(a.audit_date) : "-";
			return `<tr>
				<td><a href="/app/night-audit/${encodeURIComponent(a.name)}">${date}</a></td>
				<td>${a.occupied_rooms || 0} / ${a.total_rooms || 0}</td>
				<td>${(a.occupancy_rate || 0).toFixed(1)}%</td>
				<td>${format_currency(a.total_revenue)}</td>
				<td>${format_currency(a.adr)}</td>
				<td>${format_currency(a.revpar)}</td>
			</tr>`;
		}).join("");

		return `<table class="ih-table">
			<thead><tr>
				<th>Date</th><th>Rooms (Occ/Total)</th>
				<th>Occupancy</th><th>Revenue</th><th>ADR</th><th>RevPAR</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
	}

	// --- Room status donut chart ---
	render_room_chart(d) {
		const chart_el = document.getElementById("ih-room-chart");
		if (!chart_el) return;

		const rs = d.room_status;
		const vals = [rs.Available, rs.Occupied, rs.DND, rs["Vacant Dirty"], rs["Occupied Dirty"], rs["Out of Order"]];
		if (!vals.some(v => v > 0)) {
			chart_el.innerHTML = '<div class="ih-empty">No room data</div>';
			return;
		}

		this.chart = new frappe.Chart(chart_el, {
			data: {
				labels: ["Available", "Occupied", "DND", "Vacant Dirty", "Occupied Dirty", "Out of Order"],
				datasets: [{ values: vals }],
			},
			type: "donut",
			height: 220,
			colors: ["#10b981", "#3b82f6", "#a855f7", "#fb923c", "#f97316", "#ef4444"],
		});
	}
}
