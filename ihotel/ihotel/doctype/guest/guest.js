// Copyright (c) 2025, Noble and contributors
// For license information, please see license.txt

frappe.ui.form.on("Guest", {
	refresh(frm) {
		// Restricted guest warning banner
		if (frm.doc.restricted) {
			frm.set_intro(
				__("⚠ Restricted Guest: {0}", [frm.doc.restriction_note || "No reason provided"]),
				"red"
			);
		}

		// VIP indicator
		if (frm.doc.vip_type) {
			frm.set_indicator_formatter &&
				frm.page.set_indicator(__(frm.doc.vip_type), "orange");
		}

		render_id_scan_preview(frm);

		// Scan ID button — always visible so staff can scan on new records too
		frm.add_custom_button(__("Scan ID Document"), function () {
			show_scan_dialog(frm);
		}).addClass("btn-primary");

		if (frm.is_new()) return;

		// View Stay History button
		frm.add_custom_button(__("Stay History"), function () {
			frappe.set_route("query-report", "Guest History", {
				guest: frm.doc.name,
			});
		}, __("View"));

		// New Checked In button
		frm.add_custom_button(__("New Checked In"), function () {
			frappe.new_doc("Checked In", { guest: frm.doc.name });
		}, __("View"));

		// Show Retry Sync button when the ERPXpand customer sync previously failed
		if (frm.doc.sync_status === "Failed") {
			frm.add_custom_button(__("Retry ERP Sync"), function () {
				frappe.call({
					method: "ihotel.ihotel.doctype.guest.guest.retry_customer_sync",
					args: { guest_name: frm.doc.name },
					callback(r) {
						frm.reload_doc();
					},
				});
			}).addClass("btn-warning");

			// Dashboard alert so the failure is impossible to miss
			let err_msg = __("ERP Customer sync failed.");
			if (frm.doc.sync_error) err_msg += " " + frm.doc.sync_error;
			frm.dashboard.add_comment(err_msg, "red", true);
		}

		// Color all custom action buttons
		frm.page.custom_actions.find("button")
			.removeClass("btn-default btn-secondary").addClass("btn-primary");

		// Load stay statistics into the Stats tab
		frappe.call({
			method: "ihotel.ihotel.doctype.guest.guest.get_guest_stats",
			args: { guest_name: frm.doc.name },
			callback(r) {
				if (r.message) {
					const s = r.message;
					// skip_dirty_trigger: stats are read-only rollups — must not leave the form "Not Saved"
					frm.set_value("total_stays", s.total_stays || 0, null, true);
					frm.set_value("total_nights", s.total_nights || 0, null, true);
					frm.set_value("total_revenue", s.total_revenue || 0, null, true);
					frm.set_value("last_stay_date", s.last_stay_date || null, null, true);
				}
			},
		});
	},

	id_scan(frm)      { render_id_scan_preview(frm); },
	id_scan_back(frm) { render_id_scan_preview(frm); },

	// Live duplicate check when phone is entered
	phone(frm) { check_duplicate_guest(frm); },

	// Live duplicate check when email is entered
	email(frm) { check_duplicate_guest(frm); },
});

// ─── Duplicate detection helper ───────────────────────────────────────────────

let _dup_check_timer = null;

function check_duplicate_guest(frm) {
	// Debounce: wait for the user to finish typing before querying
	clearTimeout(_dup_check_timer);
	_dup_check_timer = setTimeout(() => {
		const phone = frm.doc.phone;
		const email = frm.doc.email;
		if (!phone && !email) return;

		frappe.call({
			method: "ihotel.ihotel.doctype.guest.guest.get_duplicate_candidates",
			args: {
				phone: phone || null,
				email: email || null,
				exclude_name: frm.is_new() ? null : frm.doc.name,
			},
			callback(r) {
				const matches = r.message || [];
				if (!matches.length) return;
				const names = matches.map(m =>
					`<a href="/app/guest/${encodeURIComponent(m.name)}" target="_blank">${frappe.utils.escape_html(m.guest_name)}</a>`
				).join(", ");
				frappe.show_alert({
					message: __("Possible duplicate guest(s): {0}", [names]),
					indicator: "orange",
				}, 8);
			},
		});
	}, 800);
}

// ─── Scan dialog ──────────────────────────────────────────────────────────────

function show_scan_dialog(frm) {
	const has_front = !!frm.doc.id_scan;
	const has_back  = !!frm.doc.id_scan_back;

	const d = new frappe.ui.Dialog({
		title: __("Scan ID Document"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<div style="margin-bottom: 12px; color: var(--text-muted); font-size: 0.88em; line-height: 1.5;">
						Place the document on the scanner, then choose which side to capture.
						Accepted formats: <b>JPG, PNG, PDF</b>.
					</div>`,
			},
			{
				fieldtype: "Select",
				fieldname: "side",
				label: "Document Side",
				options: [
					{ value: "front", label: `Front / Data Page${has_front ? "  ✓" : ""}` },
					{ value: "back",  label: `Back / Signature Page${has_back ? "  ✓" : ""}` },
				],
				default: "front",
			},
		],
		primary_action_label: __("Open Scanner / Browse"),
		primary_action(values) {
			d.hide();
			const fieldname = values.side === "front" ? "id_scan" : "id_scan_back";
			open_scanner(frm, fieldname, values.side);
		},
	});

	d.show();
}

function open_scanner(frm, fieldname, side_label) {
	const label = side_label === "front" ? __("Front") : __("Back");

	// Save first if new so we have a docname to attach to
	const do_upload = () => {
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
				frm.set_value(fieldname, file_doc.file_url);
				frm.save().then(() => {
					render_id_scan_preview(frm);
					frappe.show_alert({
						message: __("ID {0} scan saved", [label]),
						indicator: "green",
					}, 4);
				});
			},
		});
	};

	if (frm.is_new()) {
		frm.save().then(do_upload);
	} else {
		do_upload();
	}
}

// ─── Preview panel ────────────────────────────────────────────────────────────

function render_id_scan_preview(frm) {
	const $wrapper = frm.fields_dict.id_scan_preview &&
		frm.fields_dict.id_scan_preview.$wrapper;
	if (!$wrapper) return;

	const front = frm.doc.id_scan;
	const back  = frm.doc.id_scan_back;

	if (!front && !back) {
		$wrapper.html(`
			<div style="
				border: 2px dashed var(--border-color);
				border-radius: 8px;
				padding: 28px 16px;
				text-align: center;
				color: var(--text-muted);
				font-size: 0.88em;
			">
				<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36"
					viewBox="0 0 24 24" fill="none" stroke="currentColor"
					stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
					style="margin-bottom: 8px; opacity: 0.4;">
					<rect x="2" y="7" width="20" height="14" rx="2"/>
					<path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
					<line x1="12" y1="12" x2="12" y2="16"/>
					<line x1="10" y1="14" x2="14" y2="14"/>
				</svg>
				<div>No ID scan on file — click <b>Scan ID Document</b> to add one</div>
			</div>`);
		return;
	}

	const make_card = (url, title) => {
		if (!url) {
			return `
				<div style="
					flex: 1; border: 2px dashed var(--border-color);
					border-radius: 8px; padding: 24px 12px;
					text-align: center; color: var(--text-muted);
					font-size: 0.82em; min-height: 120px;
					display: flex; align-items: center; justify-content: center;
				">
					<div>
						<div style="font-weight:600; margin-bottom: 4px;">${title}</div>
						<div>Not scanned yet</div>
					</div>
				</div>`;
		}

		const is_pdf = url.toLowerCase().endsWith(".pdf");
		const preview = is_pdf
			? `<div style="padding: 20px 0; font-size: 0.85em;">
					<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
						viewBox="0 0 24 24" fill="none" stroke="currentColor"
						stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
						style="display:block; margin: 0 auto 6px;">
						<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
						<polyline points="14 2 14 8 20 8"/>
					</svg>
					PDF Document
				</div>`
			: `<img src="${url}" alt="${title}"
				style="width:100%; max-height:180px; object-fit:cover;
					border-radius: 6px 6px 0 0; display:block;" />`;

		return `
			<div style="flex:1; border:1px solid var(--border-color);
				border-radius:8px; overflow:hidden; background:var(--card-bg);">
				${preview}
				<div style="padding: 8px 10px; border-top:1px solid var(--border-color);
					display:flex; justify-content:space-between; align-items:center;
					font-size:0.82em;">
					<span style="font-weight:600; color:var(--text-color);">${title}</span>
					<a href="${url}" target="_blank"
						style="color:var(--primary); text-decoration:none; white-space:nowrap;">
						View ↗
					</a>
				</div>
			</div>`;
	};

	$wrapper.html(`
		<div style="display:flex; gap:12px; margin-bottom: 4px;">
			${make_card(front, __("Front / Data Page"))}
			${make_card(back,  __("Back / Signature Page"))}
		</div>`);
}
