import frappe


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
	allowed = ["Available", "Vacant Dirty", "Occupied Dirty", "Vacant Clean", "Occupied Clean", "Dirty", "Pickup", "Inspected", "Housekeeping", "Out of Order", "Out of Service"]
	if status not in allowed:
		frappe.throw(frappe._("Invalid status: {0}").format(status))

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

	allowed = ["Available", "Vacant Dirty", "Occupied Dirty", "Vacant Clean", "Occupied Clean", "Dirty", "Pickup", "Inspected", "Housekeeping", "Out of Order", "Out of Service"]
	if status not in allowed:
		frappe.throw(frappe._("Invalid status: {0}").format(status))

	for room_name in rooms:
		doc = frappe.get_doc("Room", room_name)
		doc.status = status
		doc.save(ignore_permissions=True)

	return {"updated": len(rooms)}
