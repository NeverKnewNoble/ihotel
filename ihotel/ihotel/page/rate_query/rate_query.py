# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt


@frappe.whitelist()
def get_rate_query_data(arrival_date, nights, adults=1, children=0):
	nights = cint(nights)
	adults = cint(adults)
	children = cint(children)
	if nights < 1:
		frappe.throw(_("Nights must be at least 1"))

	departure_date = add_days(arrival_date, nights)
	total_guests = adults + children

	# All room types
	room_types = frappe.get_all(
		"Room Type",
		fields=["name", "room_type_name", "rack_rate", "maximum_capacity"],
		order_by="room_type_name",
	)

	# Active rate types
	rate_types = frappe.get_all(
		"Rate Type",
		filters={"is_active": 1},
		fields=[
			"name", "rate_type_name", "rate_code", "pricing_method",
			"base_rate", "minimum_stay_nights", "maximum_stay_nights",
			"includes_breakfast", "refundable", "includes_taxes",
		],
		order_by="rate_type_name",
	)

	# For each room type, count total and occupied rooms
	for rt in room_types:
		total = frappe.db.count("Room", {
			"room_type": rt.name,
			"status": ["!=", "Out of Order"],
		})

		# Rooms with overlapping Reservations
		res_occupied = frappe.db.sql("""
			SELECT COUNT(DISTINCT room) AS cnt
			FROM `tabReservation`
			WHERE room_type = %s
			  AND status != 'cancelled'
			  AND check_in_date < %s
			  AND check_out_date > %s
			  AND room IS NOT NULL AND room != ''
		""", (rt.name, departure_date, arrival_date), as_dict=True)

		# Rooms with overlapping Check Ins
		ci_occupied = frappe.db.sql("""
			SELECT COUNT(DISTINCT room) AS cnt
			FROM `tabChecked In`
			WHERE room_type = %s
			  AND status NOT IN ('Checked Out', 'Cancelled')
			  AND DATE(expected_check_in) < %s
			  AND DATE(expected_check_out) > %s
			  AND room IS NOT NULL AND room != ''
		""", (rt.name, departure_date, arrival_date), as_dict=True)

		res_cnt = res_occupied[0].cnt if res_occupied else 0
		ci_cnt = ci_occupied[0].cnt if ci_occupied else 0
		# Use max in case the same room appears in both (double counted)
		occupied = max(res_cnt, ci_cnt)

		rt.total_rooms = total
		rt.available_rooms = max(0, total - occupied)

		# Capacity check
		over_capacity = (
			total_guests > 0
			and rt.maximum_capacity
			and total_guests > cint(rt.maximum_capacity)
		)
		rt.is_available = rt.available_rooms > 0 and not over_capacity
		rt.over_capacity = over_capacity

	# Build grid
	grid = []
	for rate in rate_types:
		# Stay restriction check
		restriction = ""
		restricted = False
		if rate.minimum_stay_nights and nights < cint(rate.minimum_stay_nights):
			restricted = True
			restriction = _("Min stay: {0} nights").format(rate.minimum_stay_nights)
		elif rate.maximum_stay_nights and nights > cint(rate.maximum_stay_nights):
			restricted = True
			restriction = _("Max stay: {0} nights").format(rate.maximum_stay_nights)

		cells = []
		for rt in room_types:
			# Rate for this cell: use base_rate if set, else rack_rate
			cell_rate = flt(rate.base_rate) if rate.base_rate else flt(rt.rack_rate)

			cell_restriction = restriction
			if not cell_restriction and rt.over_capacity:
				cell_restriction = _("Exceeds room capacity ({0})").format(rt.maximum_capacity)

			cells.append({
				"room_type": rt.name,
				"rate": cell_rate,
				"available": rt.is_available and not restricted,
				"available_rooms": rt.available_rooms,
				"restriction": cell_restriction,
			})

		grid.append({
			"rate_type": rate.name,
			"rate_code": rate.rate_code or rate.name,
			"rate_name": rate.rate_type_name,
			"includes_breakfast": rate.includes_breakfast,
			"refundable": rate.refundable,
			"includes_taxes": rate.includes_taxes,
			"cells": cells,
		})

	return {
		"room_types": room_types,
		"rate_types": rate_types,
		"grid": grid,
		"arrival_date": arrival_date,
		"departure_date": str(departure_date),
		"nights": nights,
		"adults": adults,
		"children": children,
	}


@frappe.whitelist()
def search_guest_profiles(query):
	"""Quick guest profile search for the Rate Query page."""
	if not query or len(query) < 2:
		return []

	results = frappe.db.sql("""
		SELECT name, guest_name, email, phone
		FROM `tabGuest`
		WHERE guest_name LIKE %s
		   OR email LIKE %s
		   OR phone LIKE %s
		ORDER BY guest_name
		LIMIT 10
	""", (f"%{query}%", f"%{query}%", f"%{query}%"), as_dict=True)

	return results
