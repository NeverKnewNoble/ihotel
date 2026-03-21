# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, now_datetime, add_days, get_datetime


def auto_no_show():
	"""Mark Hotel Stay as No Show if Reserved and check-in was > 24h ago."""
	cutoff = add_days(now_datetime(), -1)
	stays = frappe.get_all(
		"Checked In",
		filters={
			"status": "Reserved",
			"docstatus": 1,
			"expected_check_in": ["<", cutoff],
		},
		pluck="name",
	)
	for stay_name in stays:
		try:
			stay = frappe.get_doc("Checked In", stay_name)
			stay.status = "No Show"
			stay.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.log_error(f"Error marking {stay_name} as No Show")
			frappe.db.rollback()


def late_checkout_alert():
	"""Create Notification Log for stays past expected check-out."""
	now = now_datetime()
	stays = frappe.get_all(
		"Checked In",
		filters={
			"status": "Checked In",
			"docstatus": 1,
			"expected_check_out": ["<", now],
		},
		fields=["name", "guest", "room", "expected_check_out"],
	)
	for stay in stays:
		# Avoid duplicate notifications
		existing = frappe.db.exists("Notification Log", {
			"document_type": "Checked In",
			"document_name": stay.name,
			"subject": ["like", "%late checkout%"],
		})
		if not existing:
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": "Administrator",
				"type": "Alert",
				"document_type": "Checked In",
				"document_name": stay.name,
				"subject": f"Late checkout: {stay.guest or ''} in room {stay.room or ''} "
				           f"(expected {stay.expected_check_out})",
			}).insert(ignore_permissions=True)
	frappe.db.commit()


def auto_generate_housekeeping():
	"""Create daily housekeeping tasks for occupied rooms."""
	today = nowdate()
	occupied_rooms = frappe.get_all(
		"Room",
		filters={"status": "Occupied"},
		pluck="name",
	)
	for room_name in occupied_rooms:
		# Check if a task already exists for today
		existing = frappe.db.exists("Housekeeping Task", {
			"room": room_name,
			"assigned_date": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
		})
		if not existing:
			try:
				frappe.get_doc({
					"doctype": "Housekeeping Task",
					"room": room_name,
					"task_type": "Stay Over Cleaning",
					"status": "Pending",
				}).insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(f"Error creating housekeeping task for room {room_name}")
	frappe.db.commit()


def send_birthday_notifications():
	"""Send birthday emails to guests whose birthday is today and notify staff."""
	from frappe.utils import getdate, nowdate

	# Check settings toggles
	send_email = True
	send_staff_alert = True
	hotel_name = "iHotel"
	try:
		settings = frappe.get_single("iHotel Settings")
		send_email = bool(settings.get("send_birthday_email", 1))
		send_staff_alert = bool(settings.get("send_birthday_staff_alert", 1))
		hotel_name = settings.hotel_name or hotel_name
	except Exception:
		pass

	today = getdate(nowdate())
	month = today.month
	day = today.day

	guests = frappe.db.sql("""
		SELECT name, guest_name, email, marketing_opt_out
		FROM `tabGuest`
		WHERE date_of_birth IS NOT NULL
		AND MONTH(date_of_birth) = %s
		AND DAY(date_of_birth) = %s
	""", (month, day), as_dict=True)

	for guest in guests:
		# --- Staff notification ---
		already_notified = frappe.db.exists("Notification Log", {
			"document_type": "Guest",
			"document_name": guest.name,
			"subject": ["like", f"%Birthday%{today.year}%"],
		})
		if send_staff_alert and not already_notified:
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": "Administrator",
				"type": "Alert",
				"document_type": "Guest",
				"document_name": guest.name,
				"subject": f"Birthday ({today.year}): {guest.guest_name}",
			}).insert(ignore_permissions=True)

		# --- Guest email (only if toggle enabled, has email, and hasn't opted out) ---
		if not send_email or not guest.email or guest.marketing_opt_out:
			continue

		try:
			from ihotel.notifications import _email_wrapper
			content = f"""
<p style="margin:0 0 20px;font-size:16px;color:#212529;">
  Dear <strong>{guest.guest_name}</strong>,
</p>
<p style="margin:0 0 24px;font-size:14px;color:#495057;line-height:1.6;">
  On behalf of the entire team at {hotel_name}, we'd like to wish you a very
  <strong>Happy Birthday!</strong> 🎂
</p>
<p style="margin:0 0 24px;font-size:14px;color:#495057;line-height:1.6;">
  As a valued guest, you are very special to us. We hope this birthday brings you
  joy, happiness, and wonderful memories. We look forward to welcoming you back soon.
</p>
<p style="margin:8px 0 0;font-size:14px;color:#495057;">
  Warm regards,<br>
  <strong>The {hotel_name} Team</strong>
</p>"""
			frappe.sendmail(
				recipients=[guest.email],
				subject=_("Happy Birthday from {0}!").format(hotel_name),
				message=_email_wrapper(hotel_name, content),
				reference_doctype="Guest",
				reference_name=guest.name,
			)
		except Exception:
			frappe.log_error(f"Error sending birthday email to guest {guest.name}")

	frappe.db.commit()


def night_audit_reminder():
	"""Remind System Managers if no Night Audit exists for today by 11 PM."""
	today = nowdate()
	audit_exists = frappe.db.exists("Night Audit", {"audit_date": today})
	if not audit_exists:
		managers = frappe.get_all(
			"Has Role",
			filters={"role": "System Manager", "parenttype": "User"},
			pluck="parent",
		)
		for user in set(managers):
			if not frappe.db.exists("User", {"name": user, "enabled": 1}):
				continue
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": f"Night Audit Reminder: No audit has been performed for {today}",
			}).insert(ignore_permissions=True)
		frappe.db.commit()
