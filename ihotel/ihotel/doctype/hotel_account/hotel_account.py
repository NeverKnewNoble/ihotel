# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


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
