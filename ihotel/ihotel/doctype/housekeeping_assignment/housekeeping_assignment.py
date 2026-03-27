# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today


class HousekeepingAssignment(Document):

	def validate(self):
		self._sync_status()

	def _sync_status(self):
		"""Auto-update overall status based on room statuses."""
		rows = self.rooms or []
		if not rows:
			return
		statuses = [r.task_status for r in rows]
		if all(s == "Completed" for s in statuses):
			self.status = "Completed"
		elif any(s in ("In Progress", "Completed") for s in statuses):
			self.status = "In Progress"
		else:
			self.status = "Open"

	def on_update(self):
		# Auto-send notification on first save if not yet sent
		if not self.notification_sent and self.rooms:
			self.send_notification()


@frappe.whitelist()
def get_dirty_rooms():
	"""Return all rooms currently with status Dirty."""
	rooms = frappe.get_all(
		"Room",
		filters={"status": "Dirty"},
		fields=["name", "room_number", "floor", "room_type"],
		order_by="floor asc, room_number asc",
	)
	return rooms


@frappe.whitelist()
def send_notification(assignment_name):
	"""Send in-app + email notification to the housekeeper."""
	doc = frappe.get_doc("Housekeeping Assignment", assignment_name)
	hk = frappe.get_doc("Housekeeper", doc.housekeeper)

	if not hk.user and not hk.email:
		frappe.throw(_("Housekeeper has no User Account or Email configured."))

	room_list = ", ".join([r.room for r in doc.rooms]) if doc.rooms else _("(none)")
	subject = _("Room Cleaning Assignment — {0}").format(doc.date)
	message = _(
		"Hello {0},<br><br>"
		"You have been assigned the following rooms to clean on <b>{1}</b>:<br><br>"
		"<b>{2}</b><br><br>"
		"{3}"
		"Please update each room's status as you complete the cleaning.<br><br>"
		"Thank you."
	).format(
		hk.employee_name,
		doc.date,
		room_list,
		(f"<i>Instructions: {frappe.utils.escape_html(doc.notes)}</i><br><br>" if doc.notes else ""),
	)

	# In-app notification
	if hk.user:
		notification = frappe.get_doc({
			"doctype": "Notification Log",
			"subject": subject,
			"email_content": message,
			"for_user": hk.user,
			"type": "Alert",
			"document_type": "Housekeeping Assignment",
			"document_name": doc.name,
			"from_user": frappe.session.user,
		})
		notification.insert(ignore_permissions=True)
		frappe.publish_realtime("notification_bell", {}, user=hk.user)

	# Email notification
	target_email = hk.email or (frappe.db.get_value("User", hk.user, "email") if hk.user else None)
	if target_email:
		frappe.sendmail(
			recipients=[target_email],
			subject=subject,
			message=message,
		)

	frappe.db.set_value("Housekeeping Assignment", assignment_name, "notification_sent", 1)
	return True
