import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import flt, getdate


def _parse_filters(filters):
	"""Accept a filters arg as dict or JSON string; return a dict."""
	if not filters:
		return {}
	if isinstance(filters, str):
		try:
			return json.loads(filters)
		except Exception:
			return {}
	return dict(filters)


def _require_company(filters):
	company = filters.get("company")
	if not company:
		frappe.throw(_("Company is required to generate a Trial Balance."))
	return company


@frappe.whitelist()
def get_trial_balance_data(filters=None):
	"""Trial balance over ERPNext GL Entry, scoped to a company and period.

	Filters dict / JSON:
		company       (required)  — ERPNext Company
		from_date     (optional)  — default: 1st of current month
		to_date       (optional)  — default: today
		finance_book  (optional)
		account_type  (optional)  — filter output to one root_type

	Returns a list of per-account rows (both leaf and group accounts) with
	debit / credit columns, plus totals. Group accounts aggregate their
	descendants via the nested-set convention on tabAccount (lft / rgt).
	"""
	filters = _parse_filters(filters)
	company = _require_company(filters)

	from_date = filters.get("from_date") or getdate(
		datetime.now().replace(day=1)
	).strftime("%Y-%m-%d")
	to_date = filters.get("to_date") or getdate().strftime("%Y-%m-%d")
	finance_book = filters.get("finance_book")
	account_type_filter = filters.get("account_type")

	# Only leaf accounts — the user doesn't want group-rollup rows in the
	# Trial Balance output. Totals are computed from leaves either way.
	accounts = frappe.db.sql(
		"""
		SELECT name, account_name, account_number, root_type, is_group,
		       lft, rgt, parent_account
		FROM `tabAccount`
		WHERE company = %(company)s AND is_group = 0
		ORDER BY lft
		""",
		{"company": company},
		as_dict=True,
	)

	empty_response = {
		"trial_balance": [],
		"total_debit": 0.0,
		"total_credit": 0.0,
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"is_balanced": True,
	}
	if not accounts:
		return empty_response

	gl_args = {
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
	}
	gl_sql = """
		SELECT account, SUM(debit) AS debit, SUM(credit) AS credit
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND is_cancelled = 0
	"""
	if finance_book:
		gl_sql += " AND finance_book = %(finance_book)s"
		gl_args["finance_book"] = finance_book
	gl_sql += " GROUP BY account"

	leaf_totals = {
		row.account: (flt(row.debit), flt(row.credit))
		for row in frappe.db.sql(gl_sql, gl_args, as_dict=True)
	}

	trial_balance = []
	total_debit = 0.0
	total_credit = 0.0

	for a in accounts:
		debit, credit = leaf_totals.get(a.name, (0.0, 0.0))

		if account_type_filter and a.root_type != account_type_filter:
			continue

		if abs(debit) < 0.005 and abs(credit) < 0.005:
			continue

		trial_balance.append({
			"account": a.name,
			"account_number": a.account_number or "",
			"account_name": a.account_name,
			"root_type": a.root_type or "",
			"is_group": False,
			"debit": round(debit, 2),
			"credit": round(credit, 2),
		})

		total_debit += debit
		total_credit += credit

	return {
		"trial_balance": trial_balance,
		"total_debit": round(total_debit, 2),
		"total_credit": round(total_credit, 2),
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"is_balanced": abs(total_debit - total_credit) < 0.01,
	}


@frappe.whitelist()
def get_account_filter_options(company=None):
	"""Return company-scoped leaf accounts and distinct root types for UI filters."""
	if not company:
		return {"accounts": [], "account_types": []}

	accounts = frappe.db.sql(
		"""
		SELECT name, account_name, account_number, root_type
		FROM `tabAccount`
		WHERE company = %s AND is_group = 0
		ORDER BY account_number
		""",
		(company,),
		as_dict=True,
	)
	root_types = frappe.db.sql(
		"""
		SELECT DISTINCT root_type FROM `tabAccount`
		WHERE company = %s AND root_type IS NOT NULL AND root_type != ''
		ORDER BY root_type
		""",
		(company,),
		as_dict=True,
	)
	return {
		"accounts": accounts,
		"account_types": [r.root_type for r in root_types],
	}


def _csv_safe_cell(value):
	"""Escape a CSV cell: quote, escape embedded quotes, and neutralise formula injection."""
	s = "" if value is None else str(value)
	if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
		s = "'" + s
	s = s.replace('"', '""')
	return '"' + s + '"'


@frappe.whitelist()
def export_trial_balance(filters=None):
	"""Render the Trial Balance as CSV, injection-safe."""
	data = get_trial_balance_data(filters)

	lines = [
		",".join(
			_csv_safe_cell(h)
			for h in ("Account Number", "Account Name", "Root Type", "Debit", "Credit")
		)
	]
	for row in data["trial_balance"]:
		lines.append(",".join([
			_csv_safe_cell(row["account_number"]),
			_csv_safe_cell(row["account_name"]),
			_csv_safe_cell(row["root_type"]),
			_csv_safe_cell(f"{row['debit']:.2f}"),
			_csv_safe_cell(f"{row['credit']:.2f}"),
		]))
	lines.append(",".join([
		_csv_safe_cell(""),
		_csv_safe_cell(""),
		_csv_safe_cell("TOTAL"),
		_csv_safe_cell(f"{data['total_debit']:.2f}"),
		_csv_safe_cell(f"{data['total_credit']:.2f}"),
	]))
	return "\n".join(lines) + "\n"
