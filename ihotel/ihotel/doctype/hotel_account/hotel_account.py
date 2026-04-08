# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


def parse_folio_charge_types(value):
    """Split stored Folio charge type list (comma or newline separated)."""
    if not value:
        return []
    return [t.strip() for t in str(value).replace("\n", ",").split(",") if t.strip()]


def resolve_hotel_account_for_charge_type(charge_type):
    """First non-group Hotel Account whose Folio charge types include this charge_type."""
    if not charge_type:
        return None
    rows = frappe.db.sql(
        """
        SELECT name, folio_charge_types FROM `tabHotel Account`
        WHERE IFNULL(is_group, 0) = 0
        """,
        as_dict=True,
    )
    for row in rows:
        if charge_type in parse_folio_charge_types(row.folio_charge_types):
            return row.name
    return None


class HotelAccount(Document):
    def validate(self):
        self.validate_parent()
        self.validate_code_unique()

    def validate_parent(self):
        if self.parent_account and self.parent_account == self.name:
            frappe.throw(_("An account cannot be its own parent."))
        if self.parent_account:
            parent = frappe.get_doc("Hotel Account", self.parent_account)
            if not parent.is_group:
                frappe.throw(_("Parent account {0} must be a group account.").format(self.parent_account))

    def validate_code_unique(self):
        if not self.account_code:
            return
        existing = frappe.db.exists(
            "Hotel Account",
            {"account_code": self.account_code, "name": ["!=", self.name or ""]}
        )
        if existing:
            frappe.throw(_("Account Code {0} is already used by account {1}.").format(
                self.account_code, existing
            ))
