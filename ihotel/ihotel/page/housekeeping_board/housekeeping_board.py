import frappe
from frappe.utils import today


ALLOWED_ROOM_STATUSES = [
	"Available",
	"Vacant Dirty",
	"Occupied Dirty",
	"Vacant Clean",
	"Occupied Clean",
	"Pickup",
	"Inspected",
	"Housekeeping",
	"Out of Order",
	"Out of Service",
]

OOO_STATUSES = {"Out of Order", "Out of Service"}


@frappe.whitelist()
def get_hk_board_data():
	"""Return all rooms with HK status, active guest info, and DND/MUR flags."""
	rooms = frappe.get_all(
		"Room",
		fields=["name", "room_number", "room_type", "floor", "status"],
		order_by="room_number asc",
	)

	for room in rooms:
		room["guest"] = None
		room["stay"] = None
		room["do_not_disturb"] = 0
		room["make_up_room"] = 0
		room["turndown_requested"] = 0

		stay = frappe.db.get_value(
			"Checked In",
			filters={
				"room": room["name"],
				"status": ["in", ["Reserved", "Checked In"]],
				"docstatus": 1,
			},
			fieldname=["name", "guest", "do_not_disturb", "make_up_room", "turndown_requested"],
			as_dict=True,
		)
		if stay:
			room["stay"] = stay.name
			room["guest"] = stay.guest
			room["do_not_disturb"] = stay.do_not_disturb or 0
			room["make_up_room"] = stay.make_up_room or 0
			room["turndown_requested"] = stay.turndown_requested or 0

	return rooms


@frappe.whitelist()
def update_room_status(room, status):
	"""Update a room's housekeeping status directly from the board."""
	if status not in ALLOWED_ROOM_STATUSES:
		frappe.throw(frappe._("Invalid status: {0}").format(status))

	# For OOO/OOS transitions from the board, keep an auditable document trail.
	if status in OOO_STATUSES:
		_create_or_reuse_active_ooo(room=room, status=status)

	doc = frappe.get_doc("Room", room)
	doc.status = status
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def bulk_update_room_status(rooms, status):
	"""Update status for multiple rooms at once."""
	import json
	if isinstance(rooms, str):
		rooms = json.loads(rooms)

	if status not in ALLOWED_ROOM_STATUSES:
		frappe.throw(frappe._("Invalid status: {0}").format(status))

	for room_name in rooms:
		if status in OOO_STATUSES:
			_create_or_reuse_active_ooo(room=room_name, status=status)

		doc = frappe.get_doc("Room", room_name)
		doc.status = status
		doc.save(ignore_permissions=True)

	return {"updated": len(rooms)}


def _create_or_reuse_active_ooo(room, status):
	"""Create and submit an active Room Out of Order record if one does not already exist."""
	active_ooo = frappe.db.exists(
		"Room Out of Order",
		{
			"room": room,
			"status": status,
			"docstatus": 1,
			"from_date": ["<=", today()],
			"to_date": [">=", today()],
		},
	)
	if active_ooo:
		return active_ooo

	ooo_doc = frappe.get_doc(
		{
			"doctype": "Room Out of Order",
			"room": room,
			"status": status,
			"from_date": today(),
			"to_date": today(),
			"return_status": "Available",
			"reason": "Marked from Housekeeping Board",
		}
	)
	ooo_doc.insert(ignore_permissions=True)
	ooo_doc.submit()
	return ooo_doc.name
