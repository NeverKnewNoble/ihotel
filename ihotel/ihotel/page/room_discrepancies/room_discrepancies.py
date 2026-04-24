import frappe


@frappe.whitelist()
def get_discrepancies():
	"""
	Detect Skip and Sleep discrepancies between Front Office and Housekeeping.

	Skip: Room HK status is clean/available BUT Check In says Checked In
	      (HK thinks vacant, FO thinks occupied)
	Sleep: Room status is Occupied BUT no active Check In exists
	       (HK thinks occupied, FO thinks vacant)
	"""
	rooms = frappe.get_all(
		"Room",
		fields=["name", "room_number", "room_type", "floor", "status"],
		order_by="room_number asc",
	)

	# Get all active (checked-in) stays mapped by room
	active_stays = frappe.db.get_all(
		"Checked In",
		filters={"status": "Checked In", "docstatus": 1},
		fields=["name", "room", "guest"],
	)
	active_by_room = {s.room: s for s in active_stays}

	discrepancies = []
	clean_statuses = {"Available"}

	for room in rooms:
		stay = active_by_room.get(room["name"])
		hk_status = room["status"]

		if stay and hk_status in clean_statuses:
			# SKIP — FO says Checked In, HK says room is clean/available
			discrepancies.append({
				"type": "Skip",
				"room": room["name"],
				"room_number": room["room_number"],
				"room_type": room["room_type"],
				"floor": room["floor"],
				"hk_status": hk_status,
				"fo_status": "Checked In",
				"guest": stay.guest,
				"stay": stay.name,
				"description": "FO shows guest checked in but room appears clean/vacant in Housekeeping.",
			})
		elif not stay and hk_status == "Occupied":
			# SLEEP — HK says occupied, FO has no active stay
			discrepancies.append({
				"type": "Sleep",
				"room": room["name"],
				"room_number": room["room_number"],
				"room_type": room["room_type"],
				"floor": room["floor"],
				"hk_status": "Occupied",
				"fo_status": "No Active Stay",
				"guest": None,
				"stay": None,
				"description": "Room shows Occupied in Housekeeping but no active Check In found.",
			})

	return discrepancies
