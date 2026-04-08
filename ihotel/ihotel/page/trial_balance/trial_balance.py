import frappe
from frappe.utils import getdate, flt, formatdate
from datetime import datetime, timedelta
import json

from ihotel.ihotel.doctype.hotel_account.hotel_account import parse_folio_charge_types

@frappe.whitelist()
def get_trial_balance_data(filters=None):
    """Get trial balance data based on filters"""
    if not filters:
        filters = {}
    
    try:
        filters = json.loads(filters) if isinstance(filters, str) else filters
    except:
        filters = {}
    
    # Get date range
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    
    if not from_date:
        from_date = getdate(datetime.now().replace(day=1)).strftime('%Y-%m-%d')
    if not to_date:
        to_date = getdate().strftime('%Y-%m-%d')
    
    # Get all hotel accounts
    accounts = frappe.db.sql("""
        SELECT name, account_name, account_code, account_type, is_group, parent_account
        FROM `tabHotel Account`
        ORDER BY account_code ASC
    """, as_dict=True)
    
    trial_balance = []
    total_debit = 0
    total_credit = 0
    
    for account in accounts:
        if account.is_group:
            # Get summary for group accounts
            debit, credit = get_account_balance(account.name, from_date, to_date, is_group=True)
        else:
            # Get balance for leaf accounts
            debit, credit = get_account_balance(account.name, from_date, to_date)
        
        if debit > 0 or credit > 0:
            trial_balance.append({
                'account_code': account.account_code or '',
                'account_name': account.account_name,
                'account_type': account.account_type,
                'debit': round(debit, 2),
                'credit': round(credit, 2),
                'is_group': account.is_group
            })
            total_debit += debit
            total_credit += credit
    
    return {
        'trial_balance': trial_balance,
        'total_debit': round(total_debit, 2),
        'total_credit': round(total_credit, 2),
        'from_date': from_date,
        'to_date': to_date,
        'is_balanced': abs(total_debit - total_credit) < 0.01
    }

def _folio_amount_for_hotel_account(account_name, from_date, to_date):
    """
    Sum Folio Charge amounts for this Hotel Account.
    Folio rows live on iHotel Profile; join through Checked In (submitted stays only).
    Match: explicit fc.hotel_account, OR empty hotel_account + charge_type listed on the Hotel Account.
    """
    types_csv = frappe.db.get_value("Hotel Account", account_name, "folio_charge_types")
    types = parse_folio_charge_types(types_csv)

    base = """
        FROM `tabFolio Charge` fc
        INNER JOIN `tabiHotel Profile` p ON p.name = fc.parent
        INNER JOIN `tabChecked In` ci ON ci.name = p.hotel_stay AND ci.docstatus = 1
        WHERE fc.charge_date BETWEEN %s AND %s
    """

    if types:
        placeholders = ", ".join(["%s"] * len(types))
        sql = f"""
            SELECT COALESCE(SUM(fc.amount), 0) AS total
            {base}
            AND (
                fc.hotel_account = %s
                OR (
                    IFNULL(fc.hotel_account, '') = ''
                    AND fc.charge_type IN ({placeholders})
                )
            )
        """
        params = tuple([from_date, to_date, account_name, *types])
    else:
        sql = f"""
            SELECT COALESCE(SUM(fc.amount), 0) AS total
            {base}
            AND fc.hotel_account = %s
        """
        params = (from_date, to_date, account_name)

    row = frappe.db.sql(sql, params, as_dict=True)
    return flt(row[0].total if row else 0)


def _debit_credit_from_amount(account_type, amount):
    """Map signed folio total to trial balance debit/credit columns by Hotel Account classification."""
    amt = flt(amount)
    if not amt:
        return 0.0, 0.0
    if account_type == "Revenue":
        return 0.0, amt
    if account_type in ("Expense", "Asset"):
        return amt, 0.0
    if account_type in ("Liability", "Equity"):
        return 0.0, amt
    # Payment, City Ledger, blank — treat as debit-like for folio charges
    return amt, 0.0


def get_account_balance(account_name, from_date, to_date, is_group=False):
    """Calculate debit and credit balance for an account"""
    if is_group:
        child_accounts = frappe.db.sql(
            """
            WITH RECURSIVE subs AS (
                SELECT name FROM `tabHotel Account` WHERE parent_account = %s
                UNION ALL
                SELECT a.name FROM `tabHotel Account` a
                INNER JOIN subs s ON a.parent_account = s.name
            )
            SELECT name FROM subs
            """,
            (account_name,),
            as_dict=True,
        )

        total_debit = 0.0
        total_credit = 0.0

        for child in child_accounts:
            child_debit, child_credit = get_account_balance(child.name, from_date, to_date)
            total_debit += child_debit
            total_credit += child_credit

        return total_debit, total_credit

    account_type = frappe.db.get_value("Hotel Account", account_name, "account_type")
    gross = _folio_amount_for_hotel_account(account_name, from_date, to_date)
    return _debit_credit_from_amount(account_type, gross)

@frappe.whitelist()
def get_account_filter_options():
    """Get account options for filters"""
    accounts = frappe.db.sql("""
        SELECT name, account_name, account_type
        FROM `tabHotel Account`
        WHERE is_group = 0
        ORDER BY account_code ASC
    """, as_dict=True)
    
    account_types = frappe.db.sql("""
        SELECT DISTINCT account_type FROM `tabHotel Account` ORDER BY account_type
    """, as_dict=True)
    
    return {
        'accounts': accounts,
        'account_types': [a.account_type for a in account_types]
    }

@frappe.whitelist()
def export_trial_balance(filters=None):
    """Export trial balance to CSV format"""
    data = get_trial_balance_data(filters)
    
    csv_content = "Account Code,Account Name,Account Type,Debit,Credit\n"
    
    for entry in data['trial_balance']:
        csv_content += f"{entry['account_code']},{entry['account_name']},{entry['account_type']},{entry['debit']},{entry['credit']}\n"
    
    csv_content += f",,TOTAL,{data['total_debit']},{data['total_credit']}\n"
    
    return csv_content
