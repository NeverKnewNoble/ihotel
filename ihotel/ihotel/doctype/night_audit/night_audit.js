// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Night Audit", {
	refresh(frm) {
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

		// Trial Balance button
		if (!frm.is_new() && frm.doc.audit_date) {
			frm.add_custom_button(__("Trial Balance"), function() {
				frm.call("get_trial_balance").then(r => {
					if (r.message) {
						print_trial_balance(r.message);
					}
				});
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
		}
	}
});

function print_trial_balance(data) {
	const hotel = frappe.sys_defaults.company || "Hotel";
	const fmt = (n) => frappe.format(n || 0, { fieldtype: "Currency" });
	const pct = (n) => (n || 0).toFixed(1) + "%";

	const revenue_rows = (data.revenue || []).map(r => `
		<tr>
			<td>${frappe.utils.escape_html(r.charge_type || "—")}</td>
			<td class="num">${fmt(r.total)}</td>
		</tr>`).join("");

	const payment_rows = (data.payments || []).map(p => `
		<tr>
			<td>${frappe.utils.escape_html(p.payment_method || "—")}</td>
			<td class="num">${fmt(p.total)}</td>
		</tr>`).join("");

	const net_class = data.net_balance < 0 ? "neg" : "";

	const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Night Audit Trial Balance — ${data.audit_date}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; max-width: 560px; margin: 30px auto; padding: 24px; color: #111; font-size: 13px; }
  h1  { text-align: center; font-size: 1.1em; letter-spacing: 2px; }
  .sub { text-align: center; font-size: 0.82em; color: #555; margin-bottom: 4px; }
  .date { text-align: center; font-size: 0.9em; font-weight: bold; margin-bottom: 16px; }
  .dashed { border-top: 1px dashed #999; margin: 10px 0; }
  .solid  { border-top: 2px solid #333; margin: 6px 0; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 0.78em; letter-spacing: 0.08em; text-transform: uppercase; color: #555; padding: 4px 0; }
  th.num, td.num { text-align: right; }
  td { padding: 3px 0; }
  .section-title { font-weight: bold; font-size: 0.85em; letter-spacing: 0.06em; text-transform: uppercase; margin: 14px 0 4px; }
  .total-row td { font-weight: bold; border-top: 1px solid #333; padding-top: 5px; }
  .net-row td { font-size: 1em; font-weight: bold; }
  .neg { color: #dc2626; }
  .stats { display: flex; gap: 24px; justify-content: center; margin: 12px 0; font-size: 0.82em; }
  .stat-item { text-align: center; }
  .stat-value { font-weight: bold; font-size: 1.1em; }
  .footer { text-align: center; font-size: 0.75em; color: #777; margin-top: 20px; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
  <h1>${hotel}</h1>
  <div class="sub">NIGHT AUDIT — TRIAL BALANCE</div>
  <div class="date">${frappe.datetime.str_to_user(data.audit_date)}</div>

  <div class="dashed"></div>
  <div class="stats">
    <div class="stat-item"><div class="stat-value">${data.occupied_rooms}</div><div>Occupied</div></div>
    <div class="stat-item"><div class="stat-value">${data.total_rooms}</div><div>Total Rooms</div></div>
    <div class="stat-item"><div class="stat-value">${pct(data.occupancy_rate)}</div><div>Occupancy</div></div>
  </div>
  <div class="dashed"></div>

  <div class="section-title">Revenue</div>
  <table>
    <thead><tr><th>Charge Type</th><th class="num">Amount</th></tr></thead>
    <tbody>
      ${revenue_rows || '<tr><td colspan="2" style="color:#999;">No charges posted</td></tr>'}
      <tr class="total-row"><td>Total Revenue</td><td class="num">${fmt(data.total_revenue)}</td></tr>
    </tbody>
  </table>

  <div class="dashed"></div>

  <div class="section-title">Payments Collected</div>
  <table>
    <thead><tr><th>Payment Method</th><th class="num">Amount</th></tr></thead>
    <tbody>
      ${payment_rows || '<tr><td colspan="2" style="color:#999;">No payments posted</td></tr>'}
      <tr class="total-row"><td>Total Payments</td><td class="num">${fmt(data.total_payments)}</td></tr>
    </tbody>
  </table>

  <div class="solid"></div>
  <table>
    <tbody>
      <tr class="net-row ${net_class}">
        <td>Net Balance (Revenue − Payments)</td>
        <td class="num">${fmt(data.net_balance)}</td>
      </tr>
    </tbody>
  </table>

  <div class="footer">
    <p>Printed: ${frappe.datetime.now_datetime()}</p>
  </div>
</body>
</html>`;

	const w = window.open("", "_blank", "width=640,height=800,toolbar=0,menubar=0");
	if (!w) { frappe.msgprint(__("Please allow popups to print.")); return; }
	w.document.write(html);
	w.document.close();
	w.focus();
	setTimeout(() => w.print(), 400);
}
