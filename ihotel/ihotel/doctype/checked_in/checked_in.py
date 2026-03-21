# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime, timedelta
from frappe.utils import get_datetime

@frappe.whitelist()
def create_folio(checked_in_name):
	"""Manually create a folio for a submitted Checked In document."""
	doc = frappe.get_doc("Checked In", checked_in_name)
	if doc.docstatus != 1:
		frappe.throw(_("Folio can only be created for submitted documents."))
	doc._create_folio()
	return doc.profile


@frappe.whitelist()
def extend_stay(checked_in_name, new_checkout, reason=None):
	"""Extend the checkout date of a checked-in guest and post the additional room charge."""
	from frappe.utils import get_datetime, flt

	doc = frappe.get_doc("Checked In", checked_in_name)

	if doc.status != "Checked In":
		frappe.throw(_("Stay extension is only allowed for guests who are currently checked in."))

	old_checkout = get_datetime(doc.expected_check_out)
	new_checkout_dt = get_datetime(new_checkout)

	if new_checkout_dt <= old_checkout:
		frappe.throw(_("New checkout date must be after the current checkout date ({0}).").format(
			str(doc.expected_check_out)
		))

	# Calculate additional nights
	extra_nights = (new_checkout_dt - old_checkout).days
	if extra_nights < 1:
		frappe.throw(_("Extension must be at least 1 night."))

	# Update the stay record
	doc.db_set("expected_check_out", new_checkout_dt)
	doc.db_set("nights", (doc.nights or 0) + extra_nights)
	doc.db_set("total_amount", flt(doc.total_amount or 0) + extra_nights * flt(doc.room_rate or 0))

	# Post additional room charge to folio
	if doc.profile and doc.room_rate:
		profile = frappe.get_doc("iHotel Profile", doc.profile)
		profile.post_charge(
			charge_type="Room Charge",
			description=_("Room {0} — Extension: {1} night(s) @ {2}").format(
				doc.room or "", extra_nights, doc.room_rate
			),
			rate=doc.room_rate,
			quantity=extra_nights,
			reference_doctype="Checked In",
			reference_name=doc.name,
		)

	# Log a comment
	note = _("Stay extended by {0} night(s). New checkout: {1}.").format(extra_nights, str(new_checkout_dt))
	if reason:
		note += " " + _("Reason: {0}").format(reason)
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Checked In",
		"reference_name": checked_in_name,
		"content": note,
	}).insert(ignore_permissions=True)

	frappe.msgprint(
		_("Stay extended by {0} night(s). New checkout: {1}.").format(extra_nights, str(new_checkout_dt)),
		indicator="green",
		alert=True,
	)

	return {"new_checkout": str(new_checkout_dt), "extra_nights": extra_nights}


@frappe.whitelist()
def move_room(checked_in_name, new_room, reason=None):
	"""Move a checked-in guest to a different room."""
	checked_in = frappe.get_doc("Checked In", checked_in_name)

	if checked_in.status != "Checked In":
		frappe.throw(_("Room move is only allowed for guests who are currently checked in."))

	if checked_in.room == new_room:
		frappe.throw(_("Guest is already assigned to room {0}.").format(new_room))

	# Confirm the destination room is available
	new_room_doc = frappe.get_doc("Room", new_room)
	if new_room_doc.status not in ("Available", "Housekeeping"):
		frappe.throw(_("Room {0} is not available (current status: {1}).").format(
			new_room, new_room_doc.status
		))

	# Confirm no active stay already using that room
	conflict = frappe.db.exists("Checked In", {
		"room": new_room,
		"status": ["in", ["Reserved", "Checked In"]],
		"docstatus": 1,
		"name": ["!=", checked_in_name],
	})
	if conflict:
		frappe.throw(_("Room {0} is already occupied by another guest.").format(new_room))

	old_room = checked_in.room

	# Free the old room
	if old_room:
		old_room_doc = frappe.get_doc("Room", old_room)
		old_room_doc.status = "Available"
		old_room_doc.save(ignore_permissions=True)

	# Occupy the new room
	new_room_doc.status = "Occupied"
	new_room_doc.save(ignore_permissions=True)

	# Update the Check In record
	checked_in.db_set("room", new_room)

	# Log a comment with the move details
	note = _("Room moved from {0} to {1}.").format(old_room or _("(none)"), new_room)
	if reason:
		note += " " + _("Reason: {0}").format(reason)
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Checked In",
		"reference_name": checked_in_name,
		"content": note,
	}).insert(ignore_permissions=True)

	frappe.msgprint(
		_("Guest moved from Room {0} to Room {1}.").format(old_room or _("(none)"), new_room),
		indicator="green",
		alert=True,
	)

	return new_room


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_rooms_for_room_type(doctype, txt, searchfield, start, page_len, filters):
	"""Return Rooms filtered by room_type."""
	room_type = (filters or {}).get("room_type")
	conditions = []
	values = []

	if txt:
		conditions.append("name LIKE %s")
		values.append(f"%{txt}%")

	if room_type:
		conditions.append("room_type = %s")
		values.append(room_type)

	# Exclude rooms that are permanently unavailable
	conditions.append("status NOT IN ('Out of Order', 'Out of Service')")

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	return frappe.db.sql(
		f"SELECT name FROM `tabRoom` {where} ORDER BY name LIMIT %s, %s",
		values + [start, page_len],
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_rate_types_for_room_type(doctype, txt, searchfield, start, page_len, filters):
	"""Return Rate Types applicable to a given room type (All Rooms + Room Type-specific)."""
	room_type = (filters or {}).get("room_type")
	conditions = []
	values = []

	if txt:
		conditions.append(f"(name LIKE %s OR rate_type_name LIKE %s)")
		values += [f"%{txt}%", f"%{txt}%"]

	if room_type:
		conditions.append("(applicable_to = 'All Rooms' OR (applicable_to = 'Room Type' AND room_type = %s))")
		values.append(room_type)

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	return frappe.db.sql(
		f"SELECT name FROM `tabRate Type` {where} ORDER BY name LIMIT %s, %s",
		values + [start, page_len],
	)


class CheckedIn(Document):
    """
    Hotel Stay document representing a guest reservation or stay.
    Manages check-in/check-out, room assignment, billing, and room status updates.
    """
    def validate(self):
        """
        Validate hotel stay information before saving.
        Ensures dates are valid, room is available, and totals are calculated.
        """
        self.validate_restricted_guest()
        self.validate_dates()
        self.validate_room_availability()
        self.validate_rate_type()
        self.calculate_total_amount()
        self.calculate_additional_services_amount()
        self.validate_additional_services()

    def validate_restricted_guest(self):
        """Block check-in for guests flagged as restricted."""
        if not self.guest:
            return
        restricted, note = frappe.db.get_value(
            "Guest", self.guest, ["restricted", "restriction_note"]
        ) or (0, "")
        if restricted:
            msg = _("Guest {0} is marked as Restricted and cannot be checked in.").format(self.guest)
            if note:
                msg += "<br><b>{0}:</b> {1}".format(_("Reason"), note)
            frappe.throw(msg, title=_("Restricted Guest"))

    def validate_dates(self):
        """
        Validate that check-in date is before check-out date.
        """
        if self.expected_check_in and self.expected_check_out:
            checked_in = get_datetime(self.expected_check_in)
            check_out = get_datetime(self.expected_check_out)
            if checked_in >= check_out:
                frappe.throw(_("Check-in date must be before check-out date"))

        if self.is_new() and self.expected_check_in:
            from frappe.utils import getdate, nowdate
            if getdate(self.expected_check_in) < getdate(nowdate()):
                frappe.throw(_("Check-in date cannot be in the past"))

    def validate_room_availability(self):
        """
        Validate that the room is available for the selected dates.
        Checks for overlapping reservations with proper status matching.
        """
        if not self.room or self.status not in ["Reserved", "Checked In"]:
            return

        # Always block rooms that are permanently out of service
        room_status = frappe.get_value("Room", self.room, "status")
        if room_status in ("Out of Order", "Out of Service"):
            frappe.throw(
                _("Room {0} is {1} and cannot be booked.").format(self.room, room_status)
            )

        # For immediate check-ins the room must be physically ready
        if self.status == "Checked In":
            READY_STATUSES = {"Available", "Pickup", "Inspected"}
            if room_status not in READY_STATUSES:
                frappe.throw(
                    _("Room {0} is not ready for check-in (current status: {1}). "
                      "Only Available, Pickup, or Inspected rooms can be checked into.").format(
                        self.room, room_status
                    )
                )

        # Check for overlapping reservations (exclude cancelled and checked out)
            overlapping_stays = frappe.db.sql("""
                SELECT name FROM `tabChecked In`
                WHERE room = %s
                AND status IN ('Reserved', 'Checked In')
                AND docstatus != 2
                AND name != %s
                AND (
                    (expected_check_in <= %s AND expected_check_out > %s)
                    OR (expected_check_in < %s AND expected_check_out >= %s)
                    OR (expected_check_in >= %s AND expected_check_out <= %s)
                )
            """, (self.room, self.name or "", self.expected_check_in, self.expected_check_in,
                  self.expected_check_out, self.expected_check_out,
                  self.expected_check_in, self.expected_check_out), as_dict=True)

            if overlapping_stays:
                frappe.throw(_("Room is not available for the selected dates. "
                             "There is an overlapping reservation: {0}").format(
                             overlapping_stays[0].name))

    def validate_rate_type(self):
        if self.rate_type and self.nights:
            rate_type = frappe.get_cached_doc("Rate Type", self.rate_type)
            if rate_type.minimum_stay_nights and self.nights < rate_type.minimum_stay_nights:
                frappe.throw(
                    _("Minimum stay for rate type {0} is {1} nights").format(
                        self.rate_type, rate_type.minimum_stay_nights
                    )
                )
            if rate_type.maximum_stay_nights and self.nights > rate_type.maximum_stay_nights:
                frappe.throw(
                    _("Maximum stay for rate type {0} is {1} nights").format(
                        self.rate_type, rate_type.maximum_stay_nights
                    )
                )

    def calculate_total_amount(self):
        """
        Calculate total amount based on number of nights and room rate.
        Automatically calculates nights and total amount when dates or rate change.
        """
        if self.expected_check_in and self.expected_check_out and self.room_rate:
            checked_in = get_datetime(self.expected_check_in)
            check_out = get_datetime(self.expected_check_out)
            nights = (check_out - checked_in).days
            if nights > 0:
                self.total_amount = nights * (self.room_rate or 0)
                self.nights = nights
            else:
                self.total_amount = 0
                self.nights = 0

    def calculate_additional_services_amount(self):
        """
        Calculate amount for each service item in additional_services table.
        Amount = rate * quantity for each service.
        """
        if self.additional_services:
            for service in self.additional_services:
                if service.rate is not None and service.quantity is not None:
                    service.amount = (service.rate or 0) * (service.quantity or 0)
                else:
                    service.amount = 0

    def validate_additional_services(self):
        """
        Validate that no empty rows exist in the additional_services table.
        A row is considered empty if service_type is not provided.
        """
        if self.additional_services:
            for idx, service in enumerate(self.additional_services, start=1):
                if not service.service_type:
                    frappe.throw(_("Row {0} in Additional Services table is empty. Please fill in the Service Type or remove the row.").format(idx))

    def on_submit(self):
        """
        Update room status when hotel stay is submitted.
        Auto-create a folio and post the initial room charge.
        """
        if self.status == "Reserved":
            self.mark_room_as_occupied()
        self._create_folio()

    def _create_folio(self):
        """Create an iHotel Profile (folio) for this stay if one doesn't exist yet."""
        existing = frappe.db.get_value("iHotel Profile", {"hotel_stay": self.name}, "name")
        if existing:
            self.db_set("profile", existing, update_modified=False)
            return

        profile = frappe.get_doc({
            "doctype": "iHotel Profile",
            "hotel_stay": self.name,
            "status": "Open",
        })
        profile.insert(ignore_permissions=True)
        self.db_set("profile", profile.name, update_modified=False)

        # Post the room charge for the full stay upfront
        if self.room_rate and self.nights:
            profile.post_charge(
                charge_type="Room Charge",
                description=_("Room {0} — {1} night(s) @ {2}").format(
                    self.room or "", self.nights, self.room_rate
                ),
                rate=self.room_rate,
                quantity=self.nights,
                reference_doctype="Checked In",
                reference_name=self.name,
            )



    def on_update(self):
        """
        Keep associated room status in sync with the stay lifecycle.
        """
        self.sync_room_status()

    def on_update_after_submit(self):
        """
        Frappe calls this hook when a submitted stay is edited (e.g., check-in/out).
        """
        self.sync_room_status()
        if self.status == "Checked Out":
            self.update_guest_stats()

    def update_guest_stats(self):
        """Recompute and persist lifetime stats on the linked Guest profile."""
        if not self.guest:
            return
        try:
            from frappe.utils import flt, today
            stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total_stays,
                    SUM(nights) as total_nights,
                    SUM(total_amount) as total_revenue,
                    MAX(DATE(actual_check_out)) as last_stay_date
                FROM `tabChecked In`
                WHERE guest = %s
                AND status = 'Checked Out'
                AND docstatus = 1
            """, self.guest, as_dict=True)
            if stats:
                s = stats[0]
                frappe.db.set_value("Guest", self.guest, {
                    "total_stays": s.total_stays or 0,
                    "total_nights": s.total_nights or 0,
                    "total_revenue": flt(s.total_revenue),
                    "last_stay_date": s.last_stay_date,
                }, update_modified=False)
        except Exception as e:
            frappe.log_error(f"Error updating guest stats for {self.guest}: {str(e)}")




    def on_cancel(self):
        """
        Free up the room when hotel stay is cancelled.
        """
        if self.room:
            try:
                room = frappe.get_doc("Room", self.room)
                # Only update status if room is currently marked as Occupied
                if room.status == "Occupied":
                    # Check if there are other active stays for this room
                    active_stays = frappe.db.exists("Checked In", {
                        "room": self.room,
                        "status": ["in", ["Reserved", "Checked In"]],
                        "docstatus": 1,
                        "name": ["!=", self.name]
                    })
                    if not active_stays:
                        room.status = "Available"
                        room.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Error updating room status on cancel: {str(e)}")
                # Don't throw error to allow cancellation

    def mark_room_as_occupied(self):
        """
        Sync the linked room document so that its status mirrors an active stay.
        """
        if not self.room:
            return

        try:
            room = frappe.get_doc("Room", self.room)

            # Update only when the room is not already marked as occupied
            if room.status != "Occupied":
                room.status = "Occupied"
                room.save(ignore_permissions=True)
        except Exception as e:
            message = _("Error updating room status: {0}").format(str(e))
            frappe.log_error(message)
            frappe.throw(message)

    def mark_room_as_available(self):
        """
        Free the linked room when the stay completes and no other active stays remain.
        """
        if not self.room:
            return

        try:
            # Ensure there isn't another active stay keeping the room busy
            active_stay_exists = frappe.db.exists("Checked In", {
                "room": self.room,
                "status": ["in", ["Reserved", "Checked In"]],
                "docstatus": 1,
                "name": ["!=", self.name]
            })

            if not active_stay_exists:
                room = frappe.get_doc("Room", self.room)
                if room.status != "Available":
                    room.status = "Available"
                    room.save(ignore_permissions=True)
        except Exception as e:
            message = _("Error freeing room status: {0}").format(str(e))
            frappe.log_error(message)
            frappe.throw(message)

    def sync_room_status(self):
        """
        Central place to mirror stay status transitions to the linked room.
        """
        if self.status == "Checked In":
            self.mark_room_as_occupied()
        elif self.status == "Checked Out":
            self.mark_room_as_available()
