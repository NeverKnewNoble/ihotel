# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, today


class RoomOutofOrder(Document):
	def validate(self):
		if self.from_date and self.to_date:
			if getdate(self.from_date) > getdate(self.to_date):
				frappe.throw(_("From Date must be before To Date."))

		if self.room and self.status == "Out of Order":
			active_stay = frappe.db.exists("Checked In", {
				"room": self.room,
				"status": ["in", ["Reserved", "Checked In"]],
				"docstatus": 1,
			})
			if active_stay:
				frappe.throw(_(
					"Room {0} has an active guest stay and cannot be placed Out of Order."
				).format(self.room))

	def on_update(self):
		# Keep room status aligned immediately when an active OOO/OOS record is created or edited.
		if self.docstatus in (0, 1):
			self._apply_status_if_active_period()

	def on_submit(self):
		self._apply_status_if_active_period()

	def on_cancel(self):
		today_date = getdate(today())
		if getdate(self.from_date) <= today_date <= getdate(self.to_date):
			self._set_room_status(self.return_status or "Available")

	def _apply_status_if_active_period(self):
		today_date = getdate(today())
		if getdate(self.from_date) <= today_date <= getdate(self.to_date):
			self._set_room_status(self.status)

	def _set_room_status(self, status):
		room = frappe.get_doc("Room", self.room)
		room.status = status
		room.save(ignore_permissions=True)
