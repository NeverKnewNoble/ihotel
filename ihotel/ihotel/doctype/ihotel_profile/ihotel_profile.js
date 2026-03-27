// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("iHotel Profile", {
	refresh(frm) {
		// Outstanding balance indicator
		if (frm.doc.outstanding_balance > 0) {
			frm.set_intro(
				__("Outstanding Balance: {0}", [
					frappe.format(frm.doc.outstanding_balance, { fieldtype: "Currency" })
				]),
				"red"
			);
		}

		if (frm.is_new()) return;

		// Mark All Paid button
		if (frm.doc.payments && frm.doc.payments.length > 0) {
			let has_pending = frm.doc.payments.some(
				(p) => p.payment_status === "Pending payment"
			);
			if (has_pending) {
				frm.add_custom_button(__("Mark All Paid"), function () {
					frm.doc.payments.forEach((row) => {
						if (row.payment_status === "Pending payment") {
							frappe.model.set_value(
								row.doctype,
								row.name,
								"payment_status",
								"Paid"
							);
						}
					});
					frm.dirty();
					frm.save();
				}).addClass("btn-primary");
			}
		}

		// Settle button
		if (
			frm.doc.status === "Open" &&
			frm.doc.outstanding_balance !== undefined &&
			frm.doc.outstanding_balance <= 0
		) {
			frm.add_custom_button(__("Settle"), function () {
				frm.set_value("status", "Settled");
				frm.save();
			}).addClass("btn-primary");
		}
	},
});

// ─── Payment Items: per-row Print button ──────────────────────────────────

frappe.ui.form.on("Payment Items", {
	print_payment(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		print_payment_receipt(frm, row);
	},
});

// ─── Folio Charge: per-row Print and Scan buttons ─────────────────────────

frappe.ui.form.on("Folio Charge", {
	print_charge(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		print_single_charge(frm, row);
	},

	scan_charge(frm, cdt, cdn) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save before attaching a scan."));
			return;
		}
		new frappe.ui.FileUploader({
			doctype: frm.doctype,
			docname: frm.docname,
			frm: frm,
			folder: "Home/Attachments",
			allow_multiple: false,
			restrictions: {
				allowed_file_types: ["image/*", ".pdf"],
			},
			on_success(file_doc) {
				frappe.show_alert(
					{
						message: __("Scan attached: {0}", [file_doc.file_name]),
						indicator: "green",
					},
					5
				);
				frm.reload_doc();
			},
		});
	},
});

// ─── Print: single payment receipt ────────────────────────────────────────

function print_payment_receipt(frm, row) {
	let hotel_name = frappe.sys_defaults.company || "Hotel";
	let amount_fmt = frappe.format(row.rate, { fieldtype: "Currency" });
	let date_fmt = frappe.datetime.str_to_user(row.date);

	let html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Payment Receipt</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; max-width: 380px; margin: 30px auto; padding: 20px; color: #111; }
  h1 { text-align: center; font-size: 1.1em; letter-spacing: 2px; margin-bottom: 4px; }
  .subtitle { text-align: center; font-size: 0.78em; color: #555; margin-bottom: 16px; }
  .dashed { border-top: 1px dashed #999; margin: 10px 0; }
  .row { display: flex; justify-content: space-between; font-size: 0.85em; margin: 5px 0; }
  .row.big { font-size: 1.05em; font-weight: bold; margin-top: 8px; }
  .label { color: #555; }
  .status-badge { display: inline-block; padding: 2px 8px; border: 1px solid #333; border-radius: 3px; font-size: 0.78em; }
  .footer { text-align: center; font-size: 0.75em; color: #777; margin-top: 16px; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
  <h1>${hotel_name}</h1>
  <div class="subtitle">PAYMENT RECEIPT</div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Guest</span><span>${frm.doc.guest_name || ""}</span></div>
  <div class="row"><span class="label">Room</span><span>${frm.doc.room || ""}</span></div>
  <div class="row"><span class="label">Profile</span><span>${frm.doc.name}</span></div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Date</span><span>${date_fmt}</span></div>
  <div class="row"><span class="label">Method</span><span>${row.payment_method || ""}</span></div>
  ${row.detail ? `<div class="row"><span class="label">Description</span><span>${row.detail}</span></div>` : ""}
  <div class="dashed"></div>
  <div class="row big"><span>AMOUNT PAID</span><span>${amount_fmt}</span></div>
  <div class="dashed"></div>
  <div class="row">
    <span class="label">Status</span>
    <span class="status-badge">${row.payment_status || ""}</span>
  </div>
  <div class="footer">
    <p>Printed: ${frappe.datetime.now_datetime()}</p>
    <p style="margin-top:4px;">Thank you — please retain this receipt</p>
  </div>
</body>
</html>`;

	let w = window.open("", "_blank", "width=480,height=640,toolbar=0,menubar=0");
	if (!w) {
		frappe.msgprint(__("Please allow popups to print receipts."));
		return;
	}
	w.document.write(html);
	w.document.close();
	w.focus();
	setTimeout(() => w.print(), 400);
}

// ─── Print: single charge slip ────────────────────────────────────────────

function print_single_charge(frm, row) {
	let hotel_name = frappe.sys_defaults.company || "Hotel";
	let amount_fmt = frappe.format(row.amount, { fieldtype: "Currency" });
	let rate_fmt = frappe.format(row.rate, { fieldtype: "Currency" });
	let date_fmt = frappe.datetime.str_to_user(row.charge_date);

	let html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Charge Slip</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; max-width: 380px; margin: 30px auto; padding: 20px; color: #111; }
  h1 { text-align: center; font-size: 1.1em; letter-spacing: 2px; margin-bottom: 4px; }
  .subtitle { text-align: center; font-size: 0.78em; color: #555; margin-bottom: 16px; }
  .dashed { border-top: 1px dashed #999; margin: 10px 0; }
  .row { display: flex; justify-content: space-between; font-size: 0.85em; margin: 5px 0; }
  .row.big { font-size: 1.05em; font-weight: bold; margin-top: 8px; }
  .label { color: #555; }
  .sig { margin-top: 24px; font-size: 0.8em; color: #888; }
  .footer { text-align: center; font-size: 0.75em; color: #777; margin-top: 16px; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
  <h1>${hotel_name}</h1>
  <div class="subtitle">CHARGE SLIP</div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Guest</span><span>${frm.doc.guest_name || ""}</span></div>
  <div class="row"><span class="label">Room</span><span>${frm.doc.room || ""}</span></div>
  <div class="row"><span class="label">Profile</span><span>${frm.doc.name}</span></div>
  <div class="dashed"></div>
  <div class="row"><span class="label">Date</span><span>${date_fmt}</span></div>
  <div class="row"><span class="label">Charge Type</span><span>${row.charge_type || ""}</span></div>
  ${row.description ? `<div class="row"><span class="label">Description</span><span>${row.description}</span></div>` : ""}
  <div class="row"><span class="label">Qty</span><span>${row.quantity || 1}</span></div>
  <div class="row"><span class="label">Rate</span><span>${rate_fmt}</span></div>
  <div class="dashed"></div>
  <div class="row big"><span>AMOUNT</span><span>${amount_fmt}</span></div>
  <div class="dashed"></div>
  <div class="sig">Guest signature: ___________________________</div>
  <div class="footer">
    <p>Printed: ${frappe.datetime.now_datetime()}</p>
  </div>
</body>
</html>`;

	let w = window.open("", "_blank", "width=480,height=640,toolbar=0,menubar=0");
	if (!w) {
		frappe.msgprint(__("Please allow popups to print charge slips."));
		return;
	}
	w.document.write(html);
	w.document.close();
	w.focus();
	setTimeout(() => w.print(), 400);
}
