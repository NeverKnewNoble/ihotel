import frappe
from frappe.utils import today


@frappe.whitelist()
def get_turndown_data():
	"""
	Return guests who need turndown tonight:
	  1. Confirmed Reservations arriving today (primary focus)
	  2. Checked In guests with status Reserved or Checked In

	Turndown Status:
	  Completed    — a Housekeeping Task (Turndown, Completed) exists for the room today
	  Requested    — turndown_requested = 1 on the doc
	  Not Required — all others
	"""
	today_date = today()
	rows = []

	# ── 1. Confirmed Reservations arriving today ─────────────────────────────
	reservations = frappe.get_all(
		"Reservation",
		filters={"status": "confirmed", "check_in_date": today_date},
		fields=["name", "full_name", "room", "room_type", "turndown_requested", "turndown_reason"],
		order_by="room asc",
	)
	for res in reservations:
		room = (
			frappe.db.get_value("Room", res.room, ["room_number", "floor", "room_type"], as_dict=True)
			if res.room
			else None
		)
		rows.append({
			"source": "Reservation",
			"source_doc": res.name,
			"guest": res.full_name or res.name,
			"room": res.room or "",
			"room_number": room.room_number if room else (res.room or ""),
			"floor": room.floor if room else "",
			"room_type": room.room_type if room else (res.room_type or ""),
			"turndown_requested": int(res.turndown_requested or 0),
			"turndown_reason": res.turndown_reason or "",
		})

	# ── 2. Checked In guests (Reserved or Checked In status) ─────────────────
	stays = frappe.get_all(
		"Checked In",
		filters={"status": ["in", ["Reserved", "Checked In"]], "docstatus": 1},
		fields=["name", "guest", "room", "turndown_requested"],
		order_by="room asc",
	)
	for stay in stays:
		room = (
			frappe.db.get_value("Room", stay.room, ["room_number", "floor", "room_type"], as_dict=True)
			if stay.room
			else None
		)
		rows.append({
			"source": "Checked In",
			"source_doc": stay.name,
			"guest": stay.guest or "",
			"room": stay.room or "",
			"room_number": room.room_number if room else (stay.room or ""),
			"floor": room.floor if room else "",
			"room_type": room.room_type if room else "",
			"turndown_requested": int(stay.turndown_requested or 0),
			"turndown_reason": "",
		})

	# ── Completed turndown tasks for today ───────────────────────────────────
	completed_tasks = frappe.get_all(
		"Housekeeping Task",
		filters={
			"task_type": "Turndown",
			"status": "Completed",
			"assigned_date": [">=", today_date + " 00:00:00"],
		},
		fields=["room"],
	)
	completed_rooms = {t.room for t in completed_tasks}

	result = []
	for row in rows:
		if row["room"] in completed_rooms:
			row["turndown_status"] = "Completed"
		elif row["turndown_requested"]:
			row["turndown_status"] = "Requested"
		else:
			row["turndown_status"] = "Not Required"
		result.append(row)

	return result


@frappe.whitelist()
def toggle_turndown(doctype, docname, value):
	"""Toggle turndown_requested on a Reservation or Checked In document."""
	value = int(value)
	if doctype == "Reservation":
		frappe.db.set_value("Reservation", docname, "turndown_requested", value)
	elif doctype == "Checked In":
		frappe.db.set_value("Checked In", docname, "turndown_requested", value, update_modified=False)
	frappe.db.commit()
	return value
