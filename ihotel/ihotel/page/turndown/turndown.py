import frappe
from frappe.utils import today, nowdate


@frappe.whitelist()
def get_turndown_data():
	"""
	Return all currently checked-in guests with their turndown status for today.

	Status:
	- Requested   — turndown_requested=1 on Check In, no completed HK task yet
	- Completed   — a Housekeeping Task of type Turndown exists, status=Completed, today
	- Not Required — all others (checked in, turndown not requested)
	"""
	today_date = today()

	# All checked-in stays
	stays = frappe.get_all(
		"Checked In",
		filters={"status": "Checked In", "docstatus": 1},
		fields=["name", "guest", "room", "turndown_requested"],
		order_by="room asc",
	)

	# All completed turndown tasks for today
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
	for stay in stays:
		if stay.room in completed_rooms:
			turndown_status = "Completed"
		elif stay.turndown_requested:
			turndown_status = "Requested"
		else:
			turndown_status = "Not Required"

		# Get room details
		room = frappe.db.get_value("Room", stay.room, ["room_number", "floor", "room_type"], as_dict=True)

		result.append({
			"stay": stay.name,
			"guest": stay.guest,
			"room": stay.room,
			"room_number": room.room_number if room else stay.room,
			"floor": room.floor if room else "",
			"room_type": room.room_type if room else "",
			"turndown_status": turndown_status,
			"turndown_requested": stay.turndown_requested,
		})

	return result
