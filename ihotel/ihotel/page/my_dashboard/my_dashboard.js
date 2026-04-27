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
				${this.kpi_card("Arrivals Today", d.arrivals_today,
					"Expected check-ins", "amber",
					'<path d="M19 12H5M12 5l-7 7 7 7"/>')}
				${this.kpi_card("Departures Today", d.departures_today,
					"Expected check-outs", "orange",
					'<path d="M5 12h14M12 5l7 7-7 7"/>')}
				${this.kpi_card("Tonight's Revenue", format_currency(d.todays_revenue),
					"Nightly room rates, in-house stays", "green",
					'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>')}
				${this.kpi_card("ADR", format_currency(d.adr),
					"Average Daily Rate (in-house)", "teal",
					'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>')}
				${this.kpi_card("RevPAR", format_currency(d.revpar),
					"Revenue Per Available Room", "blue",
					'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>')}
			</div>

			<!-- Room Status + Operations -->
			<div class="ih-section-grid ih-ops-grid">
				${this.render_room_status_panel(d)}
				${this.render_operations_panel(d)}
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

		// Donut chart removed — the new Room Status panel uses a stacked
		// capacity bar as its visualization, so render_room_chart is no longer called.
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

	// =========================================================================
	// Room Status Panel — capacity narrative
	// One stacked bar shows how the total inventory is allocated.
	// Below: three operational columns (Sold / Available / Blocked) explaining
	// WHY each room can or can't take a new guest tonight.
	// =========================================================================
	render_room_status_panel(d) {
		const rs = d.room_status || {};
		const total = d.total_rooms || 0;
		const is_today = d.is_today !== false; // default true if backend didn't send the flag
		const has_audit = !!d.has_audit;

		// Per-status breakdown is only meaningful for today's live state.
		// For past/future dates we synthesize aggregate buckets from the
		// hero numbers (which DO come from Night Audit when available).
		const live = is_today;

		const sold_count      = live
			? (rs.Occupied || 0) + (rs.DND || 0) + (rs["Occupied Dirty"] || 0)
			: (d.occupied_rooms || 0);
		const blocked_count   = live
			? (rs["Out of Order"] || 0) + (rs["Out of Service"] || 0)
			: 0;
		const available_count = Math.max(0, total - sold_count - blocked_count);

		const pct = (n) => total > 0 ? ((n / total) * 100) : 0;
		const fmt_pct = (n) => pct(n).toFixed(pct(n) < 10 ? 1 : 0) + "%";

		// Stacked capacity bar — full per-status colors when live, simple
		// 3-bucket bar (sold/available/blocked) when historical/future.
		let stack_html;
		if (live) {
			const segments = [
				{ key: "Occupied",        cls: "occupied",        count: rs.Occupied        || 0 },
				{ key: "DND",             cls: "dnd",             count: rs.DND             || 0 },
				{ key: "Occupied Dirty",  cls: "occupied-dirty",  count: rs["Occupied Dirty"] || 0 },
				{ key: "Available",       cls: "available",       count: rs.Available       || 0 },
				{ key: "Vacant Dirty",    cls: "vacant-dirty",    count: rs["Vacant Dirty"] || 0 },
				{ key: "Out of Order",    cls: "out-of-order",    count: rs["Out of Order"] || 0 },
				{ key: "Out of Service",  cls: "out-of-service",  count: rs["Out of Service"] || 0 },
			];
			stack_html = segments.filter(s => s.count > 0).map(s => `
				<div class="ih-cap-seg ih-cap-seg--${s.cls}"
					 style="flex-grow:${s.count};"
					 title="${s.key}: ${s.count} (${fmt_pct(s.count)})"></div>
			`).join("");
		} else {
			const buckets = [
				{ key: "Sold",      cls: "occupied",  count: sold_count },
				{ key: "Available", cls: "available", count: available_count },
				{ key: "Blocked",   cls: "out-of-order", count: blocked_count },
			];
			stack_html = buckets.filter(b => b.count > 0).map(b => `
				<div class="ih-cap-seg ih-cap-seg--${b.cls}"
					 style="flex-grow:${b.count};"
					 title="${b.key}: ${b.count} (${fmt_pct(b.count)})"></div>
			`).join("");
		}

		const row = (label, n, dot_cls) => `
			<div class="ih-rs-row">
				<span class="ih-rs-dot ih-rs-dot--${dot_cls}"></span>
				<span class="ih-rs-label">${label}</span>
				<span class="ih-rs-count">${n}</span>
			</div>`;

		// Date badge in the header so users always know what view they're seeing
		const date_user = d.selected_date ? frappe.datetime.str_to_user(d.selected_date) : "";
		const badge = is_today
			? `<span class="ih-rs-badge ih-rs-badge--live">Live</span>`
			: (has_audit
				? `<span class="ih-rs-badge ih-rs-badge--snap">Snapshot · ${date_user}</span>`
				: `<span class="ih-rs-badge ih-rs-badge--none">No audit · ${date_user}</span>`);

		// Three-group breakdown only renders for today's live data.
		// For historical/future, replace with aggregate Sold / Available / Blocked tiles.
		const groups_html = live ? `
			<div class="ih-rs-groups">
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Sold</span>
						<span class="ih-rs-group-total">
							<strong>${sold_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(sold_count)}</span>
						</span>
					</div>
					${row("Occupied",       rs.Occupied          || 0, "occupied")}
					${row("DND",            rs.DND               || 0, "dnd")}
					${row("Occupied Dirty", rs["Occupied Dirty"] || 0, "occupied-dirty")}
				</div>
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Available</span>
						<span class="ih-rs-group-total">
							<strong>${available_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(available_count)}</span>
						</span>
					</div>
					${row("Available",    rs.Available        || 0, "available")}
					${row("Vacant Dirty", rs["Vacant Dirty"]  || 0, "vacant-dirty")}
				</div>
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Blocked</span>
						<span class="ih-rs-group-total">
							<strong>${blocked_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(blocked_count)}</span>
						</span>
					</div>
					${row("Out of Order",   rs["Out of Order"]   || 0, "out-of-order")}
					${row("Out of Service", rs["Out of Service"] || 0, "out-of-service")}
				</div>
			</div>` : `
			<div class="ih-rs-groups ih-rs-groups--aggregate">
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Sold</span>
						<span class="ih-rs-group-total"><strong>${sold_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(sold_count)}</span></span>
					</div>
				</div>
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Available</span>
						<span class="ih-rs-group-total"><strong>${available_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(available_count)}</span></span>
					</div>
				</div>
				<div class="ih-rs-group">
					<div class="ih-rs-group-head">
						<span class="ih-rs-group-name">Blocked</span>
						<span class="ih-rs-group-total"><strong>${blocked_count}</strong>
							<span class="ih-rs-group-pct">${fmt_pct(blocked_count)}</span></span>
					</div>
				</div>
			</div>
			<div class="ih-rs-note">
				${has_audit
					? "Per-status breakdown isn't snapshotted on Night Audit — showing aggregates from the audit."
					: "No Night Audit was submitted for this date — historical room state isn't available."}
			</div>`;

		return `
		<div class="ih-card ih-room-card">
			<div class="ih-card-header">
				<div class="ih-card-title">Room Status ${badge}</div>
				<a class="ih-card-link" href="/app/room">View All Rooms</a>
			</div>
			<div class="ih-card-body">
				<div class="ih-rs-hero">
					<div class="ih-rs-hero-figure">
						<span class="ih-rs-hero-num">${sold_count}</span>
						<span class="ih-rs-hero-divider">/</span>
						<span class="ih-rs-hero-total">${total}</span>
					</div>
					<div class="ih-rs-hero-meta">
						<span class="ih-rs-hero-label">${is_today ? "Occupied now" : "Occupied"}</span>
						<span class="ih-rs-hero-pct">${(d.occupancy_rate || 0).toFixed(1)}%</span>
					</div>
				</div>

				<div class="ih-cap-bar" role="img" aria-label="Room status distribution">
					${stack_html || `<div class="ih-cap-seg ih-cap-seg--out-of-service" style="flex-grow:1;" title="No data"></div>`}
				</div>

				${groups_html}
			</div>
		</div>`;
	}

	// =========================================================================
	// Operations Panel — action-first ops view
	// Surfaces dimensions the doctype actually has: priority, assignment,
	// task type, category — not just status counts.
	// =========================================================================
	render_operations_panel(d) {
		const hk = d.housekeeping || {};
		const mt = d.maintenance  || {};

		// Backwards-compat: old payload was a flat {Pending, In Progress, Completed} dict
		const hk_status = hk.status || (typeof hk.Pending === "number" ? hk : {});
		const mt_status = mt.status || (typeof mt.Open    === "number" ? mt : {});

		const hk_total  = hk.total != null ? hk.total : Object.values(hk_status).reduce((a,b) => a+b, 0);
		const mt_total  = mt.total != null ? mt.total : Object.values(mt_status).reduce((a,b) => a+b, 0);

		const hk_urgent     = hk.urgent     || 0;
		const hk_high       = hk.high       || 0;
		const hk_unassigned = hk.unassigned || 0;
		const hk_due_today  = hk.due_today  || 0;

		const mt_critical   = mt.critical   || (d.critical_maintenance || 0);
		const mt_high       = mt.high       || 0;
		const mt_unassigned = mt.unassigned || 0;
		const mt_open_today = mt.open_today || ((mt_status["Open"] || 0) + (mt_status["In Progress"] || 0));

		const action_total  = hk_unassigned + mt_unassigned;
		const action_pulse  = (hk_urgent + mt_critical + action_total) > 0;

		const status_row = (label, n, max, cls) => {
			const w = max > 0 ? Math.max(2, (n / max) * 100) : 0;
			return `
			<div class="ih-op-row">
				<span class="ih-op-row-label">${label}</span>
				<div class="ih-op-row-bar"><div class="ih-op-row-bar-fill ih-op-row-bar-fill--${cls}" style="width:${w}%"></div></div>
				<span class="ih-op-row-count">${n}</span>
			</div>`;
		};

		const by_type   = hk.by_type || {};
		const type_max  = Math.max(1, ...Object.values(by_type));
		const type_rows = Object.entries(by_type)
			.sort((a,b) => b[1] - a[1])
			.map(([name, n]) => `
				<div class="ih-op-tt-row">
					<span class="ih-op-tt-name">${frappe.utils.escape_html(name)}</span>
					<div class="ih-op-tt-bar"><div class="ih-op-tt-bar-fill" style="width:${(n/type_max)*100}%"></div></div>
					<span class="ih-op-tt-count">${n}</span>
				</div>`).join("");

		const by_cat = mt.by_category || [];
		const cat_html = by_cat.length ? `
			<div class="ih-op-chips">
				${by_cat.slice(0, 6).map(c => `
					<a class="ih-op-chip" href="/app/maintenance-request?category=${encodeURIComponent(c.category)}">
						<span class="ih-op-chip-name">${frappe.utils.escape_html(c.category)}</span>
						<span class="ih-op-chip-count">${c.count}</span>
					</a>`).join("")}
			</div>` : `<div class="ih-op-empty">No active categories</div>`;

		const action_tile = (kind, count, label, sub, href) => `
			<a class="ih-action-tile ih-action-tile--${kind} ${count > 0 ? 'is-live' : 'is-quiet'}" href="${href}">
				<span class="ih-action-num">${count}</span>
				<span class="ih-action-label">${label}</span>
				<span class="ih-action-sub">${sub}</span>
			</a>`;

		const ic_alert  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
		const ic_broom  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19.4 15L18 14.6 16 19l1.4.4a2 2 0 0 0 2.5-1.4l.4-1.4a2 2 0 0 0-1.4-2.5z"/><path d="M16 19l-3-1-2 4 4-1z"/><path d="M3 21l9-9"/><path d="M14 4l6 6"/></svg>';
		const ic_wrench = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>';

		const alert_msgs = [];
		if (mt_critical > 0)   alert_msgs.push(`${mt_critical} critical maintenance request${mt_critical !== 1 ? 's' : ''}`);
		if (hk_urgent > 0)     alert_msgs.push(`${hk_urgent} urgent housekeeping task${hk_urgent !== 1 ? 's' : ''}`);
		if (action_total > 0)  alert_msgs.push(`${action_total} unassigned`);
		const alert_html = alert_msgs.length ? `
			<div class="ih-op-alert">
				<span class="ih-op-alert-icon">${ic_alert}</span>
				<span>${alert_msgs.join(' · ')} need attention</span>
			</div>` : "";

		const date_user = d.selected_date ? frappe.datetime.str_to_user(d.selected_date) : "";
		const date_label = (d.is_today === false) ? date_user : "today";

		return `
		<div class="ih-card ih-ops-card">
			<div class="ih-card-header">
				<div class="ih-card-title">Operations <span class="ih-rs-badge ih-rs-badge--snap">${date_label}</span></div>
			</div>
			<div class="ih-card-body">
				<div class="ih-op-section">
					<div class="ih-op-section-head">
						<div class="ih-op-section-title">
							<span class="ih-op-section-ic ih-op-section-ic--hk">${ic_broom}</span>
							Housekeeping
						</div>
						<div class="ih-op-section-meta">
							<span><strong>${hk_total}</strong> task${hk_total !== 1 ? 's' : ''}</span>
							<span class="ih-op-meta-pill">${hk_due_today} scheduled</span>
						</div>
					</div>
					<div class="ih-op-rows">
						${status_row('In Progress', hk_status['In Progress'] || 0, hk_total, 'in-progress')}
						${status_row('Completed',   hk_status['Completed']   || 0, hk_total, 'completed')}
					</div>
					<div class="ih-op-tt">
						<div class="ih-op-tt-head">By Task Type</div>
						${type_rows || `<div class="ih-op-empty">No tasks today</div>`}
					</div>
				</div>

				<div class="ih-op-section">
					<div class="ih-op-section-head">
						<div class="ih-op-section-title">
							<span class="ih-op-section-ic ih-op-section-ic--mt">${ic_wrench}</span>
							Maintenance
						</div>
						<div class="ih-op-section-meta">
							<span><strong>${mt_total}</strong> request${mt_total !== 1 ? 's' : ''}</span>
							<span class="ih-op-meta-pill ih-op-meta-pill--warn">${mt_open_today} open</span>
						</div>
					</div>
					<div class="ih-op-rows">
						${status_row('Open',        mt_status['Open']        || 0, mt_total, 'open')}
						${status_row('In Progress', mt_status['In Progress'] || 0, mt_total, 'in-progress')}
						${status_row('Resolved',    mt_status['Resolved']    || 0, mt_total, 'resolved')}
						${status_row('Closed',      mt_status['Closed']      || 0, mt_total, 'closed')}
					</div>
					<div class="ih-op-cats">
						<div class="ih-op-cats-head">Top Categories</div>
						${cat_html}
					</div>
				</div>

				${alert_html}
			</div>
		</div>`;
	}
}
