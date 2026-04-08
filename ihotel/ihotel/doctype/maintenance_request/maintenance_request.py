# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, add_days, add_months, add_years


class MaintenanceRequest(Document):
	def before_save(self):
		# Keep previous assignee so we can notify only on actual assignment changes.
		self._old_assigned_to = None
		if not self.is_new():
			self._old_assigned_to = frappe.db.get_value("Maintenance Request", self.name, "assigned_to")

	def before_insert(self):
		# Server-side fallback to always capture reporter for new records.
		if not self.reported_by:
			self.reported_by = frappe.session.user

	def validate(self):
		self.update_room_on_priority()
		self.calculate_next_due_date()

	def on_update(self):
		self.sync_room_status()
		self.notify_assignee_if_changed()

	def notify_assignee_if_changed(self):
		if not self.assigned_to:
			return
		if self.assigned_to == getattr(self, "_old_assigned_to", None):
			return
		self._send_assignment_notification()

	def _send_assignment_notification(self):
		subject = _("Maintenance Request Assigned — {0}").format(self.name)
		message = _(
			"You have been assigned Maintenance Request <b>{0}</b>.<br><br>"
			"<b>Room:</b> {1}<br>"
			"<b>Priority:</b> {2}<br>"
			"<b>Status:</b> {3}<br>"
			"<b>Description:</b> {4}"
		).format(
			self.name,
			frappe.utils.escape_html(self.room or _("(not set)")),
			frappe.utils.escape_html(self.priority or _("(not set)")),
			frappe.utils.escape_html(self.status or _("Open")),
			frappe.utils.escape_html(self.description or _("(no description)")),
		)

		# In-app bell notification
		frappe.get_doc({
			"doctype": "Notification Log",
			"subject": subject,
			"email_content": message,
			"for_user": self.assigned_to,
			"type": "Alert",
			"document_type": "Maintenance Request",
			"document_name": self.name,
			"from_user": frappe.session.user,
		}).insert(ignore_permissions=True)
		# Notification Log already triggers the red-dot indicator via "notification".
		# This extra event is only for a quick toast popup in desk.
		frappe.publish_realtime(
			"ihotel_new_notification",
			{"subject": subject, "document_type": "Maintenance Request", "document_name": self.name},
			user=self.assigned_to,
			after_commit=True,
		)

	def update_room_on_priority(self):
		if self.room and self.priority in ("Critical", "High") and self.status == "Open":
			room = frappe.get_doc("Room", self.room)
			if room.status not in ("Out of Order",):
				room.status = "Out of Order"
				room.save(ignore_permissions=True)

	def calculate_next_due_date(self):
		if self.maintenance_type != "Preventive" or not self.recurrence or self.recurrence == "None":
			return
		if not self.scheduled_date:
			return
		base = getdate(self.scheduled_date)
		if self.recurrence == "Weekly":
			self.next_due_date = add_days(base, 7)
		elif self.recurrence == "Monthly":
			self.next_due_date = add_months(base, 1)
		elif self.recurrence == "Quarterly":
			self.next_due_date = add_months(base, 3)
		elif self.recurrence == "Yearly":
			self.next_due_date = add_years(base, 1)

	def sync_room_status(self):
		if not self.room:
			return
		if self.status in ("Resolved", "Closed"):
			other_open = frappe.db.exists("Maintenance Request", {
				"room": self.room,
				"status": ["not in", ["Resolved", "Closed"]],
				"name": ["!=", self.name],
			})
			if not other_open:
				active_stay = frappe.db.exists("Checked In", {
					"room": self.room,
					"status": ["in", ["Reserved", "Checked In"]],
					"docstatus": 1,
				})
				room = frappe.get_doc("Room", self.room)
				if active_stay:
					if room.status != "Occupied":
						room.status = "Occupied"
						room.save(ignore_permissions=True)
				else:
					if room.status == "Out of Order":
						room.status = "Available"
						room.save(ignore_permissions=True)


@frappe.whitelist()
def create_ooo_from_request(maintenance_request_name, from_date, to_date, reason=None):
	"""Create a Room Out of Order record linked to this maintenance request."""
	mr = frappe.get_doc("Maintenance Request", maintenance_request_name)

	if not mr.room:
		frappe.throw(_("Maintenance Request has no room assigned."))

	if mr.linked_ooo:
		frappe.throw(_("This request already has a linked OOO record: {0}").format(mr.linked_ooo))

	ooo = frappe.get_doc({
		"doctype": "Room Out of Order",
		"room": mr.room,
		"status": "Out of Order",
		"from_date": from_date,
		"to_date": to_date,
		"reason": reason or mr.description or "",
		"return_status": "Available",
	})
	ooo.insert(ignore_permissions=True)
	ooo.submit()

	mr.db_set("linked_ooo", ooo.name)

	frappe.msgprint(
		_("Room Out of Order {0} created and linked.").format(ooo.name),
		indicator="green",
		alert=True,
	)
	return ooo.name
