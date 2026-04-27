frappe.pages["trial_balance"].on_page_load = function (wrapper) {
	wrapper.trial_balance = new TrialBalance(wrapper);
};

frappe.pages["trial_balance"].on_page_show = function (wrapper) {
	if (wrapper.trial_balance) {
		wrapper.trial_balance.refresh();
	}
};

class TrialBalance {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Trial Balance"),
			single_column: true,
		});

		this.wrapper = wrapper;
		this.current_data = null;
		this.$root = this.page.main;

		this.make();
		this.bind_events();
		this.load_initial_data();
	}

	refresh() {
		this.load_trial_balance();
	}

	make() {
		const icon = (paths) =>
			'<span class="tb-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="16" height="16">' +
			paths +
			"</svg></span>";
		const icPrint =
			icon('<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>');
		const icDownload = icon('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>');
		const icRefresh = icon('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>');
		const icLoader =
			'<svg class="tb-spinner" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke-width="3" fill="none" stroke-dasharray="32" stroke-dashoffset="12" stroke-linecap="round"/></svg>';

		this.$root.html(`
<div class="trial-balance-container tb-surface">
    <div class="tb-page-header">
        <div class="tb-page-header__titles">
            <h1>` + __("Trial Balance") + `</h1>
            <p class="tb-page-header__sub">` + __("Hotel accounts for the selected period") + `</p>
        </div>
        <div class="tb-header-actions tb-btn-toolbar">
            <button type="button" class="tb-btn tb-btn--secondary" data-tb-action="print">
                ` + icPrint + __("Print") + `
            </button>
            <button type="button" class="tb-btn tb-btn--secondary" data-tb-action="export">
                ` + icDownload + __("Export") + `
            </button>
            <button type="button" class="tb-btn tb-btn--secondary" data-tb-action="refresh">
                ` + icRefresh + __("Refresh") + `
            </button>
        </div>
    </div>

    <div class="tb-filters-section">
        <div class="row">
            <div class="col-md-3">
                <label>` + __("From Date") + `</label>
                <input type="date" class="form-control tb-from-date">
            </div>
            <div class="col-md-3">
                <label>` + __("To Date") + `</label>
                <input type="date" class="form-control tb-to-date">
            </div>
            <div class="col-md-3">
                <label>` + __("Account Type") + `</label>
                <select class="form-control tb-account-type">
                    <option value="">` + __("All Account Types") + `</option>
                </select>
            </div>
            <div class="col-md-3">
                <label>&nbsp;</label>
                <div class="tb-btn-toolbar">
                    <button type="button" class="tb-btn tb-btn--primary" data-tb-action="apply-filters">
                        ` + __("Apply Filters") + `
                    </button>
                    <button type="button" class="tb-btn tb-btn--secondary" data-tb-action="clear-filters">
                        ` + __("Clear") + `
                    </button>
                </div>
            </div>
        </div>
    </div>

    <div class="tb-summary-section">
        <div class="row">
            <div class="col-md-3">
				<div class="tb-stat-card tb-stat-card--debit">
                    <h4>` + __("Total Debit") + `</h4>
                    <div class="amount tb-total-debit">$0.00</div>
                </div>
            </div>
            <div class="col-md-3">
				<div class="tb-stat-card tb-stat-card--credit">
                    <h4>` + __("Total Credit") + `</h4>
                    <div class="amount tb-total-credit">$0.00</div>
                </div>
            </div>
            <div class="col-md-3">
				<div class="tb-stat-card tb-stat-card--diff">
                    <h4>` + __("Difference") + `</h4>
                    <div class="amount tb-difference">$0.00</div>
                </div>
            </div>
            <div class="col-md-3">
				<div class="tb-stat-card tb-stat-card--status">
                    <h4>` + __("Status") + `</h4>
                    <div class="status tb-balance-status">
                        <span class="tb-pill tb-pill--muted">` + __("Loading...") + `</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="tb-table-section">
        <div class="table-responsive">
            <table class="table table-bordered trial-balance-table">
                <thead>
                    <tr>
                        <th>` + __("Account Code") + `</th>
                        <th>` + __("Account Name") + `</th>
                        <th>` + __("Account Type") + `</th>
                        <th class="text-right">` + __("Debit") + `</th>
                        <th class="text-right">` + __("Credit") + `</th>
                    </tr>
                </thead>
                <tbody class="tb-trial-balance-tbody">
                    <tr>
                        <td colspan="5" class="tb-text-center">
                            <div class="tb-loading-spinner">
                                ` + icLoader + `
                                <span>` + __("Loading trial balance...") + `</span>
                            </div>
                        </td>
                    </tr>
                </tbody>
                <tfoot>
                    <tr class="total-row">
                        <th colspan="3">` + __("TOTAL") + `</th>
                        <th class="text-right tb-footer-total-debit">$0.00</th>
                        <th class="text-right tb-footer-total-credit">$0.00</th>
                    </tr>
                </tfoot>
            </table>
        </div>
    </div>
</div>`);

		const today = new Date();
		const first_day = new Date(today.getFullYear(), today.getMonth(), 1);
		this.$root.find(".tb-from-date").val(first_day.toISOString().split("T")[0]);
		this.$root.find(".tb-to-date").val(today.toISOString().split("T")[0]);

		// Honour frappe.route_options when navigated from another page
		// (e.g. the Night Audit form passes audit_date as from/to).
		const opts = frappe.route_options || {};
		if (opts.from_date) this.$root.find(".tb-from-date").val(opts.from_date);
		if (opts.to_date)   this.$root.find(".tb-to-date").val(opts.to_date);
		if (opts.from_date || opts.to_date) frappe.route_options = null;
	}

	bind_events() {
		const me = this;
		this.$root.on("click", "[data-tb-action]", function () {
			const action = $(this).data("tb-action");
			if (action === "apply-filters") me.load_trial_balance();
			else if (action === "clear-filters") me.clear_filters();
			else if (action === "print") me.print_trial_balance();
			else if (action === "export") me.export_trial_balance();
			else if (action === "refresh") me.load_trial_balance();
		});
		this.$root.on("keypress", ".tb-from-date, .tb-to-date", function (e) {
			if (e.which === 13) me.load_trial_balance();
		});
	}

	load_initial_data() {
		const me = this;
		frappe.call({
			method: "ihotel.ihotel.page.trial_balance.trial_balance.get_account_filter_options",
			callback: function (r) {
				if (r.message && r.message.account_types) {
					const select = me.$root.find(".tb-account-type");
					r.message.account_types.forEach(function (type) {
						select.append($("<option>").val(type).text(type));
					});
				}
			},
		});
		this.load_trial_balance();
	}

	get_filters() {
		return {
			from_date: this.$root.find(".tb-from-date").val(),
			to_date: this.$root.find(".tb-to-date").val(),
			account_type: this.$root.find(".tb-account-type").val(),
		};
	}

	load_trial_balance() {
		const me = this;
		this.show_loading();
		frappe.call({
			method: "ihotel.ihotel.page.trial_balance.trial_balance.get_trial_balance_data",
			args: {
				filters: JSON.stringify(this.get_filters()),
			},
			callback: function (r) {
				if (r.message) {
					me.current_data = r.message;
					me.render_trial_balance(r.message);
				} else {
					me.show_error(__("Failed to load trial balance data"));
				}
			},
			error: function () {
				me.show_error(__("Error loading trial balance data"));
			},
		});
	}

	render_trial_balance(data) {
		const me = this;
		this.$root.find(".tb-total-debit").text(this.format_currency(data.total_debit));
		this.$root.find(".tb-total-credit").text(this.format_currency(data.total_credit));
		const difference = Math.abs(data.total_debit - data.total_credit);
		this.$root.find(".tb-difference").text(this.format_currency(difference));

		const status_el = this.$root.find(".tb-balance-status");
		status_el.empty();
		if (data.is_balanced) {
			status_el.append('<span class="tb-pill tb-pill--success">' + __("Balanced") + "</span>");
		} else {
			status_el.append('<span class="tb-pill tb-pill--danger">' + __("Out of Balance") + "</span>");
		}

		const tbody = this.$root.find(".tb-trial-balance-tbody");
		tbody.empty();
		if (data.trial_balance.length === 0) {
			tbody.append(
				'<tr><td colspan="5" class="tb-text-center">' + __("No data found for selected period") + "</td></tr>"
			);
			return;
		}

		data.trial_balance.forEach(function (row) {
			const tr = $("<tr>");
			if (row.is_group) tr.addClass("group-account");
			tr.append("<td>" + (row.account_code || "") + "</td>");
			tr.append("<td>" + row.account_name + "</td>");
			tr.append("<td>" + row.account_type + "</td>");
			tr.append('<td class="text-right">' + me.format_currency(row.debit) + "</td>");
			tr.append('<td class="text-right">' + me.format_currency(row.credit) + "</td>");
			tbody.append(tr);
		});

		this.$root.find(".tb-footer-total-debit").text(this.format_currency(data.total_debit));
		this.$root.find(".tb-footer-total-credit").text(this.format_currency(data.total_credit));
	}

	show_loading() {
		const tbody = this.$root.find(".tb-trial-balance-tbody");
		const spin =
			'<svg class="tb-spinner" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke-width="3" fill="none" stroke-dasharray="32" stroke-dashoffset="12" stroke-linecap="round"/></svg>';
		tbody.empty();
		tbody.append(
			'<tr><td colspan="5" class="tb-text-center"><div class="tb-loading-spinner">' +
				spin +
				"<span>" +
				__("Loading...") +
				"</span></div></td></tr>"
		);
	}

	show_error(message) {
		const tbody = this.$root.find(".tb-trial-balance-tbody");
		tbody.empty();
		tbody.append(
			'<tr><td colspan="5" class="tb-text-center tb-text-danger">' + message + "</td></tr>"
		);
	}

	clear_filters() {
		const today = new Date();
		const first_day = new Date(today.getFullYear(), today.getMonth(), 1);
		this.$root.find(".tb-from-date").val(first_day.toISOString().split("T")[0]);
		this.$root.find(".tb-to-date").val(today.toISOString().split("T")[0]);
		this.$root.find(".tb-account-type").val("");
		this.load_trial_balance();
	}

	print_trial_balance() {
		if (!this.current_data) {
			frappe.msgprint(__("No data to print"));
			return;
		}
		let print_content = `
            <html>
                <head>
                    <title>${__("Trial Balance")}</title>
                    <style>
                        body { font-family: Arial, sans-serif; margin: 20px; }
                        h2 { text-align: center; margin-bottom: 20px; }
                        .print-header { margin-bottom: 30px; }
                        .print-date-range, .print-generated { margin-bottom: 10px; }
                        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
                        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                        th { background-color: #f5f5f5; font-weight: bold; }
                        .text-right { text-align: right; }
                        .group-account { font-weight: bold; background-color: #f9f9f9; }
                        .total-row { font-weight: bold; background-color: #f0f0f0; }
                    </style>
                </head>
                <body>
                    <div class="print-header">
                        <h2>${__("Trial Balance")}</h2>
                        <div class="print-date-range">
                            <strong>${__("Period")}:</strong> ${this.current_data.from_date} to ${this.current_data.to_date}
                        </div>
                        <div class="print-generated">
                            <strong>${__("Generated on")}:</strong> ${new Date().toLocaleString()}
                        </div>
                    </div>
                    <table class="print-table">
                        <thead>
                            <tr>
                                <th>${__("Account Code")}</th>
                                <th>${__("Account Name")}</th>
                                <th>${__("Account Type")}</th>
                                <th class="text-right">${__("Debit")}</th>
                                <th class="text-right">${__("Credit")}</th>
                            </tr>
                        </thead>
                        <tbody>`;

		const me = this;
		this.current_data.trial_balance.forEach(function (row) {
			print_content += `
                <tr${row.is_group ? ' class="group-account"' : ""}>
                    <td>${row.account_code || ""}</td>
                    <td>${row.account_name}</td>
                    <td>${row.account_type}</td>
                    <td class="text-right">${me.format_currency(row.debit)}</td>
                    <td class="text-right">${me.format_currency(row.credit)}</td>
                </tr>`;
		});

		print_content += `
                        </tbody>
                        <tfoot>
                            <tr class="total-row">
                                <th colspan="3">${__("TOTAL")}</th>
                                <th class="text-right">${this.format_currency(this.current_data.total_debit)}</th>
                                <th class="text-right">${this.format_currency(this.current_data.total_credit)}</th>
                            </tr>
                        </tfoot>
                    </table>
                </body>
            </html>`;

		const print_window = window.open("", "_blank");
		print_window.document.write(print_content);
		print_window.document.close();
		print_window.print();
	}

	export_trial_balance() {
		if (!this.current_data) {
			frappe.msgprint(__("No data to export"));
			return;
		}
		const me = this;
		frappe.call({
			method: "ihotel.ihotel.page.trial_balance.trial_balance.export_trial_balance",
			args: {
				filters: JSON.stringify(this.get_filters()),
			},
			callback: function (r) {
				if (r.message) {
					const blob = new Blob([r.message], { type: "text/csv" });
					const url = window.URL.createObjectURL(blob);
					const a = document.createElement("a");
					a.href = url;
					a.download =
						"trial_balance_" + me.get_filters().from_date + "_to_" + me.get_filters().to_date + ".csv";
					document.body.appendChild(a);
					a.click();
					document.body.removeChild(a);
					window.URL.revokeObjectURL(url);
					frappe.show_alert(__("Trial Balance exported successfully"));
				}
			},
		});
	}

	format_currency(amount) {
		return frappe.format(amount == null || amount === "" ? 0 : amount, { fieldtype: "Currency" }, { only_value: true });
	}
}
