# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class FolioCharge(Document):
	def validate(self):
		self.amount = round(flt(self.rate) * flt(self.quantity or 1), 2)
