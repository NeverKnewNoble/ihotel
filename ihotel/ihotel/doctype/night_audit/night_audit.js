// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Night Audit", {
	refresh(frm) {
		// Auto-set performed_by to current logged-in user for new docs.
		if (frm.is_new() && !frm.doc.performed_by && frappe.session.user) {
			frm.set_value("performed_by", frappe.session.user);
		}

		// Calculate metrics on form load (for new and existing forms)
		if (frm.doc.audit_date) {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
				}
			});
		}

		// Trial Balance button — navigates to the Trial Balance page pre-filled
		// with the audit date as a single-day range.
		if (!frm.is_new() && frm.doc.audit_date) {
			frm.add_custom_button(__("Trial Balance"), function() {
				frappe.route_options = {
					from_date: frm.doc.audit_date,
					to_date: frm.doc.audit_date,
				};
				frappe.set_route("trial_balance");
			}).addClass("btn-primary");
		}

		// Add button to refresh/calculate metrics
		frm.add_custom_button(__("Refresh Metrics"), function() {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
					frappe.show_alert({
						message: __("Metrics refreshed successfully"),
						indicator: "green"
					});
				}
			});
		}).addClass("btn-primary");

		// Reload Transactions / Verify All buttons (only for unsubmitted audits)
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Reload Transactions"), function() {
				frappe.call({
					method: "ihotel.ihotel.doctype.night_audit.night_audit.load_day_transactions",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Loading transactions for {0}...", [frm.doc.audit_date]),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("Loaded {0} charges and {1} payments",
									[r.message.charges_count, r.message.payments_count]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			});

			const is_verifier = (frappe.user_roles || []).some(
				r => ["Night Auditor", "System Manager", "Administrator"].includes(r)
			);
			if (is_verifier) {
				frm.add_custom_button(__("Verify All"), function() {
					frappe.confirm(
						__("Mark every charge and payment as verified?"),
						() => {
							frappe.call({
								method: "ihotel.ihotel.doctype.night_audit.night_audit.verify_all",
								args: { name: frm.doc.name },
								callback: (r) => {
									if (r.message) {
										frappe.show_alert({
											message: __("Verified {0} charges, {1} payments",
												[r.message.verified_charges, r.message.verified_payments]),
											indicator: "green",
										});
										frm.reload_doc();
									}
								},
							});
						}
					);
				});
			}
		}

		// Hide the verified column from non-verifier users (they can still read but not edit).
		const verifier = (frappe.user_roles || []).some(
			r => ["Night Auditor", "System Manager", "Administrator"].includes(r)
		);
		if (!verifier) {
			["charges", "payments"].forEach((tbl) => {
				const grid = frm.fields_dict[tbl] && frm.fields_dict[tbl].grid;
				if (grid) {
					grid.update_docfield_property("verified", "read_only", 1);
				}
			});
		}
	},

	audit_date(frm) {
		// Recalculate metrics when audit date changes
		if (frm.doc.audit_date) {
			frm.call("calculate_metrics").then((r) => {
				if (r.message) {
					frm.set_value("total_rooms", r.message.total_rooms);
					frm.set_value("occupied_rooms", r.message.occupied_rooms);
					frm.set_value("occupancy_rate", r.message.occupancy_rate);
					frm.set_value("total_revenue", r.message.total_revenue);
				}
			});

			// Auto-snapshot folio transactions for the new date once the doc has a name
			if (!frm.is_new() && frm.doc.docstatus === 0) {
				frappe.call({
					method: "ihotel.ihotel.doctype.night_audit.night_audit.load_day_transactions",
					args: { name: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			}
		}
	}
});

function print_trial_balance(data) {
	const hotel = frappe.sys_defaults.company || "Hotel";
	const fmt = (n) => frappe.format(n || 0, { fieldtype: "Currency" });
	const pct = (n) => (n || 0).toFixed(1) + "%";
	const esc = (s) => frappe.utils.escape_html(s || "—");

	// ── Section I: Charges / Guest Ledger ────────────────────────────────────
	const charge_rows = (data.charges || []).map(r => `
		<tr>
			<td>${esc(r.charge_type)}</td>
			<td class="num">${fmt(r.total)}</td>
		</tr>`).join("");

	// ── Section II: Collections (Cash + Card) ────────────────────────────────
	const collection_rows = (data.collections || []).map(r => `
		<tr>
			<td>${esc(r.payment_method)}</td>
			<td class="num">${fmt(r.total)}</td>
		</tr>`).join("");

	const comp_rows = (data.complimentary || []).map(r => `
		<tr class="comp-row">
			<td>${esc(r.payment_method)}</td>
			<td class="num">${fmt(r.total)}</td>
		</tr>`).join("");

	const total_all_collections = (data.total_collections || 0) + (data.total_complimentary || 0);

	// ── Section III: City Ledger ──────────────────────────────────────────────
	const city_rows = (data.city_ledger || []).map(r => `
		<tr>
			<td>${esc(r.payment_method)}</td>
			<td class="num">${fmt(r.total)}</td>
		</tr>`).join("");

	// ── Outstanding open folios ───────────────────────────────────────────────
	const outstanding_rows = (data.outstanding_folios || []).map(r => `
		<tr>
			<td>${esc(r.room)} — ${esc(r.guest)}</td>
			<td class="num">${fmt(r.outstanding_balance)}</td>
		</tr>`).join("");

	// ── Balance check ─────────────────────────────────────────────────────────
	const diff = data.balance_difference || 0;
	const diff_class = Math.abs(diff) < 0.01 ? "balanced" : "unbalanced";
	const diff_label = Math.abs(diff) < 0.01
		? "✓ BALANCED"
		: (diff > 0 ? "OUTSTANDING (In-House Charges − Credits)" : "OVERPAYMENT");

	const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Night Audit Trial Balance — ${data.audit_date}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Courier New", monospace;
    color: #191919;
    font-size: 13px;
    line-height: 1.3;
    background: #fff;
    margin: 0;
    padding: 22px;
  }
  .receipt {
    max-width: 620px;
    margin: 0 auto;
  }
  h1 {
    text-align: center;
    font-size: 30px;
    letter-spacing: 4px;
    text-transform: uppercase;
    font-weight: 700;
  }
  .sub {
    text-align: center;
    font-size: 13px;
    letter-spacing: 2px;
    color: #666;
    margin-top: 4px;
  }
  .date {
    text-align: center;
    font-size: 20px;
    font-weight: 700;
    margin-top: 6px;
    margin-bottom: 12px;
  }
  .dashed {
    border-top: 1px dashed #b9b9b9;
    margin: 10px 0;
  }
  table { width: 100%; border-collapse: collapse; margin-bottom: 4px; }
  th {
    text-align: left;
    color: #666;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 4px 0 3px;
    border-bottom: 1px solid #d6d6d6;
  }
  th.num, td.num { text-align: right; }
  td {
    padding: 4px 1px;
    vertical-align: top;
    border-bottom: 1px solid #ececec;
  }
  tr:last-child td { border-bottom: none; }
  .section-header {
    margin: 14px 0 4px;
    padding: 5px 8px;
    background: #f1f1f1;
    border-left: 3px solid #2f2f2f;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .subtotal-row td {
    border-top: 2px solid #9b9b9b;
    border-bottom: none;
    font-weight: 700;
    font-size: 24px;
    padding-top: 8px;
    padding-bottom: 4px;
  }
  .trial-row td {
    border-bottom: none;
    padding: 5px 1px;
    font-size: 30px;
  }
  .trial-row td:first-child { font-size: 17px; }
  .comp-row td { color: #5e5e5e; font-style: italic; }
  .indent td:first-child { padding-left: 28px; }
  .balanced td { color: #0d6b2f; font-weight: 700; }
  .unbalanced td { color: #a52323; font-weight: 700; }
  .stats {
    display: flex;
    margin: 10px 0 12px;
    border: 1px dashed #c0c0c0;
  }
  .stat-item {
    flex: 1;
    text-align: center;
    padding: 10px 6px 8px;
    border-right: 1px dashed #c0c0c0;
  }
  .stat-item:last-child { border-right: none; }
  .stat-value {
    font-weight: 700;
    font-size: 26px;
    margin-bottom: 2px;
  }
  .stat-label {
    color: #5f5f5f;
    font-size: 11px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
  }
  .footer {
    text-align: center;
    font-size: 11px;
    color: #8a8a8a;
    margin-top: 16px;
  }
  .note {
    font-size: 11px;
    color: #737373;
    margin-top: 4px;
    font-style: italic;
  }
  @media print {
    body { margin: 0; padding: 14px; }
    .section-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>
  <div class="receipt">
  <h1>${esc(hotel)}</h1>
  <div class="sub">Night Audit — Trial Balance</div>
  <div class="date">${frappe.datetime.str_to_user(data.audit_date)}</div>

  <div class="stats">
    <div class="stat-item">
      <div class="stat-value">${data.occupied_rooms} / ${data.total_rooms}</div>
      <div class="stat-label">Rooms Occupied</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">${pct(data.occupancy_rate)}</div>
      <div class="stat-label">Occupancy</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">${fmt(data.adr)}</div>
      <div class="stat-label">ADR</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">${fmt(data.revpar)}</div>
      <div class="stat-label">RevPAR</div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════ -->
  <!-- SECTION I — CHARGES (GUEST LEDGER)                        -->
  <!-- ══════════════════════════════════════════════════════════ -->
  <div class="section-header">Section I &mdash; Charges (Guest Ledger)</div>
  <table>
    <thead><tr><th>Charge Type</th><th class="num">Amount</th></tr></thead>
    <tbody>
      ${charge_rows || '<tr><td colspan="2" style="color:#aaa; padding:4px 0;">No charges posted for this date</td></tr>'}
      <tr class="subtotal-row">
        <td>Guest Ledger Total</td>
        <td class="num">${fmt(data.total_charges)}</td>
      </tr>
    </tbody>
  </table>

  <!-- ══════════════════════════════════════════════════════════ -->
  <!-- SECTION II — COLLECTIONS                                  -->
  <!-- ══════════════════════════════════════════════════════════ -->
  <div class="section-header">Section II &mdash; Collections</div>
  <table>
    <thead><tr><th>Payment Method</th><th class="num">Amount</th></tr></thead>
    <tbody>
      ${collection_rows || '<tr><td colspan="2" style="color:#aaa; padding:4px 0;">No cash / card payments today</td></tr>'}
      ${comp_rows}
      <tr class="subtotal-row">
        <td>Collections Total</td>
        <td class="num">${fmt(total_all_collections)}</td>
      </tr>
    </tbody>
  </table>

  <!-- ══════════════════════════════════════════════════════════ -->
  <!-- SECTION III — CITY LEDGER                                 -->
  <!-- ══════════════════════════════════════════════════════════ -->
  <div class="section-header">Section III &mdash; City Ledger</div>
  <table>
    <thead><tr><th>Account</th><th class="num">Amount</th></tr></thead>
    <tbody>
      ${city_rows || '<tr><td colspan="2" style="color:#aaa; padding:4px 0;">No city ledger transfers today</td></tr>'}
      <tr class="subtotal-row">
        <td>City Ledger Total</td>
        <td class="num">${fmt(data.total_city_ledger)}</td>
      </tr>
    </tbody>
  </table>

  <!-- ══════════════════════════════════════════════════════════ -->
  <!-- TRIAL BALANCE RECONCILIATION                              -->
  <!-- ══════════════════════════════════════════════════════════ -->
  <div class="section-header">Trial Balance</div>
  <table>
    <tbody>
      <tr>
        <td>Guest Ledger Total (Charges)</td>
        <td class="num">${fmt(data.total_charges)}</td>
      </tr>
      <tr class="indent">
        <td>Less: Collections</td>
        <td class="num">(${fmt(total_all_collections)})</td>
      </tr>
      <tr class="indent">
        <td>Less: City Ledger</td>
        <td class="num">(${fmt(data.total_city_ledger)})</td>
      </tr>
      <tr class="${diff_class} trial-row">
        <td>${diff_label}</td>
        <td class="num">${fmt(Math.abs(diff))}</td>
      </tr>
    </tbody>
  </table>

  ${(data.outstanding_folios || []).length > 0 ? `
  <!-- Outstanding open folios for reference -->
  <div class="dashed"></div>
  <div class="section-header" style="background:#fff8e1; border-left-color:#b45309;">Open Folio Balances (In-House Guests)</div>
  <table>
    <thead><tr><th>Room — Guest</th><th class="num">Outstanding</th></tr></thead>
    <tbody>
      ${outstanding_rows}
      <tr class="subtotal-row">
        <td>Total Open Balances</td>
        <td class="num">${fmt(data.total_outstanding)}</td>
      </tr>
    </tbody>
  </table>
  <p class="note">These balances represent in-house guests whose charges have not yet been fully settled.</p>
  ` : ""}

  <div class="footer">
    <p>Printed: ${frappe.datetime.now_datetime()}</p>
  </div>
  </div>
</body>
</html>`;

	const w = window.open("", "_blank", "width=680,height=900,toolbar=0,menubar=0");
	if (!w) { frappe.msgprint(__("Please allow popups to print.")); return; }
	w.document.write(html);
	w.document.close();
	w.focus();
	setTimeout(() => w.print(), 400);
}
