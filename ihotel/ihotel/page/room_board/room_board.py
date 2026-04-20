import frappe
from frappe import _
from frappe.utils import now_datetime, flt


@frappe.whitelist()
def get_room_board_data():
	"""Return all rooms with current status, guest info, stay info, and rack rate."""
	rooms = frappe.get_all(
		"Room",
		fields=["name", "room_number", "room_type", "floor", "status"],
		order_by="room_number asc",
	)

	# Fetch rack rates from Room Type in one query
	rack_rates = {}
	if rooms:
		room_types = list({r["room_type"] for r in rooms if r["room_type"]})
		if room_types:
			rates = frappe.get_all(
				"Room Type",
				filters={"name": ["in", room_types]},
				fields=["name", "rack_rate"],
			)
			rack_rates = {r.name: r.rack_rate for r in rates}

	for room in rooms:
		room["guest"] = None
		room["stay"] = None
		room["check_out"] = None
		room["do_not_disturb"] = 0
		room["make_up_room"] = 0
		room["rack_rate"] = rack_rates.get(room["room_type"], 0)

		if room["status"] in ("Occupied", "Reserved"):
			stay = frappe.db.get_value(
				"Checked In",
				filters={
					"room": room["name"],
					"status": ["in", ["Reserved", "Checked In"]],
					"docstatus": 1,
				},
				fieldname=["name", "guest", "expected_check_out", "do_not_disturb", "make_up_room"],
				as_dict=True,
			)
			if stay:
				room["stay"] = stay.name
				room["guest"] = stay.guest
				room["check_out"] = stay.expected_check_out
				room["do_not_disturb"] = stay.do_not_disturb
				room["make_up_room"] = stay.make_up_room

	return rooms


@frappe.whitelist()
def quick_check_in(
	room, guest, expected_check_in, expected_check_out,
	rate_type, room_rate, rate_column=None, rate_description=None,
	adults=1, children=0, business_source=None, deposit_amount=0
):
	"""Create and submit a Checked In document directly from the Room Board.

	Builds a rate_lines row so Checked In.calculate_total_amount computes tax
	and totals from the Rate Type's tax_schedule — matching the behavior of
	creating a Checked In record via the DocType form.
	"""
	room_doc = frappe.get_doc("Room", room)
	rate_val = flt(room_rate)

	rate_line = {
		"rate_type":   rate_type,
		"room_type":   room_doc.room_type,
		"rate_column": rate_column or "Single / Base Rate",
		"description": rate_description or rate_type,
		"rate":        rate_val,
		"amount":      rate_val,
	}

	doc = frappe.get_doc({
		"doctype": "Checked In",
		"guest": guest,
		"room": room,
		"room_type": room_doc.room_type,
		"expected_check_in": expected_check_in,
		"actual_check_in": now_datetime(),
		"expected_check_out": expected_check_out,
		"status": "Checked In",
		"adults": int(adults or 1),
		"children": int(children or 0),
		"business_source": business_source or None,
		"deposit_amount": flt(deposit_amount or 0),
		"rate_lines": [rate_line],
	})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name
