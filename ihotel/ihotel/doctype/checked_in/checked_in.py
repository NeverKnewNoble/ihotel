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
        self.validate_status_transition()
        self.validate_room_availability()
        self.validate_rate_type()
        self.calculate_additional_services_amount()
        self.calculate_total_amount()
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

    def validate_status_transition(self):
        """Enforce valid status transitions to prevent illegal state jumps."""
        if self.is_new():
            return
        old_status = frappe.db.get_value("Checked In", self.name, "status")
        if not old_status or old_status == self.status:
            return
        valid = {
            "Reserved":    ["Checked In", "No Show", "Cancelled"],
            "Checked In":  ["Checked Out"],
            "Checked Out": [],
            "No Show":     [],
            "Cancelled":   [],
        }
        allowed = valid.get(old_status, [])
        if self.status not in allowed:
            frappe.throw(
                _("Cannot change status from {0} to {1}. Allowed: {2}").format(
                    old_status, self.status,
                    ", ".join(allowed) if allowed else _("None")
                )
            )

    def validate_dates(self):
        """
        Validate that check-in date is before check-out date.
        """
        if self.expected_check_in and self.expected_check_out:
            checked_in = get_datetime(self.expected_check_in)
            check_out = get_datetime(self.expected_check_out)
            if checked_in >= check_out:
                frappe.throw(_("Check-in date must be before check-out date"))
            if (check_out - checked_in).days < 1:
                frappe.throw(_("Minimum stay is 1 night."))

        if self.is_new() and self.expected_check_in:
            from frappe.utils import getdate, nowdate
            if getdate(self.expected_check_in) < getdate(nowdate()):
                allow_past = frappe.db.get_single_value("iHotel Settings", "allow_past_dates")
                if not allow_past:
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

        # Check for overlapping stays (runs for both Reserved and Checked In)
        if self.expected_check_in and self.expected_check_out:
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
        Calculate total amount: (nights × room_rate) + additional_services - discount.
        """
        from frappe.utils import flt
        if self.expected_check_in and self.expected_check_out and self.room_rate:
            checked_in = get_datetime(self.expected_check_in)
            check_out = get_datetime(self.expected_check_out)
            nights = (check_out - checked_in).days
            if nights > 0:
                self.nights = nights
                room_total = nights * flt(self.room_rate)
                services_total = flt(self.additional_services_total)
                discount = flt(self.discount)
                self.total_amount = max(0, room_total + services_total - discount)
            else:
                self.total_amount = 0
                self.nights = 0

    def calculate_additional_services_amount(self):
        """
        Calculate amount for each service row and sum into additional_services_total.
        """
        from frappe.utils import flt
        total = 0.0
        for service in (self.additional_services or []):
            service.amount = round(flt(service.rate or 0) * flt(service.quantity or 0), 2)
            total += service.amount
        self.additional_services_total = round(total, 2)

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

        from frappe.utils import flt, nowdate

        # Post the room charge for the full stay upfront
        if self.room_rate and self.nights:
            room_rate = flt(self.room_rate)
            discount = flt(self.discount)
            if discount > 0:
                # Post full room charge then a discount line
                profile.post_charge(
                    charge_type="Room Charge",
                    description=_("Room {0} — {1} night(s) @ {2}").format(
                        self.room or "", self.nights, room_rate
                    ),
                    rate=room_rate,
                    quantity=self.nights,
                    reference_doctype="Checked In",
                    reference_name=self.name,
                )
                profile.post_charge(
                    charge_type="Other",
                    description=_("Discount applied"),
                    rate=-discount,
                    quantity=1,
                    reference_doctype="Checked In",
                    reference_name=self.name,
                )
            else:
                profile.post_charge(
                    charge_type="Room Charge",
                    description=_("Room {0} — {1} night(s) @ {2}").format(
                        self.room or "", self.nights, room_rate
                    ),
                    rate=room_rate,
                    quantity=self.nights,
                    reference_doctype="Checked In",
                    reference_name=self.name,
                )

        # Post each additional service as a folio charge
        for svc in (self.additional_services or []):
            if flt(svc.amount) == 0:
                continue
            profile.post_charge(
                charge_type="Additional Service",
                description=svc.service_type or _("Additional Service"),
                rate=flt(svc.rate or 0),
                quantity=flt(svc.quantity or 1),
                reference_doctype="Checked In",
                reference_name=self.name,
            )

        # Post deposit as a folio payment if already collected
        if self.deposit_received and flt(self.deposit_amount) > 0:
            profile.append("payments", {
                "date": nowdate(),
                "payment_method": self.deposit_method or "Cash",
                "detail": _("Deposit collected at check-in"),
                "rate": flt(self.deposit_amount),
                "payment_status": "Paid",
            })
            profile.save(ignore_permissions=True)



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
            if not self.sales_invoice:
                self._create_erp_invoice()

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

    # ── ERPXpand Accounting Integration ────────────────────────────────────────

    def _create_erp_invoice(self):
        """Create a Sales Invoice (and Payment Entries) in ERPXpand on checkout."""
        from frappe.utils import flt, nowdate

        try:
            settings = frappe.get_single("iHotel Settings")
            if not settings.get("enable_accounting_integration"):
                return

            company = settings.company
            if not company:
                frappe.log_error("iHotel: Accounting enabled but no Company set in iHotel Settings")
                return

            if not self.profile:
                return
            profile = frappe.get_doc("iHotel Profile", self.profile)
            if not profile.get("charges"):
                return

            customer = self._get_or_create_customer(settings, company)
            if not customer:
                return

            invoice = self._build_sales_invoice(profile, customer, company, settings)
            if not invoice:
                return

            self.db_set("sales_invoice", invoice.name, update_modified=False)

            if profile.get("payments"):
                self._create_payment_entries(profile, invoice, customer, company)

            frappe.msgprint(
                _("Sales Invoice {0} created in ERPXpand.").format(
                    frappe.utils.get_link_to_form("Sales Invoice", invoice.name)
                ),
                indicator="green",
                alert=True,
            )

        except Exception as e:
            frappe.log_error(f"iHotel: Error creating Sales Invoice for {self.name}: {str(e)}")
            frappe.msgprint(
                _("Checkout complete, but Sales Invoice could not be auto-created. "
                  "Please create it manually. Error has been logged."),
                indicator="orange",
                alert=True,
            )

    def _get_or_create_customer(self, settings, company):
        """Return ERPXpand Customer name, creating one from the Guest if needed."""
        if not self.guest:
            return None

        guest_name = frappe.db.get_value("Guest", self.guest, "guest_name") or self.guest

        # Try exact match first
        customer = frappe.db.get_value("Customer", {"customer_name": guest_name})
        if customer:
            return customer

        try:
            cust = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": guest_name,
                "customer_type": "Individual",
                "customer_group": settings.get("default_customer_group") or "All Customer Groups",
                "territory": settings.get("default_territory") or "All Territories",
            })
            cust.insert(ignore_permissions=True)
            return cust.name
        except Exception as e:
            frappe.log_error(f"iHotel: Could not create Customer for guest {self.guest}: {str(e)}")
            return None

    def _build_sales_invoice(self, profile, customer, company, settings):
        """Build, insert and submit a Sales Invoice from the folio charges."""
        from frappe.utils import flt, nowdate

        room_item  = settings.get("room_charge_item")
        extra_item = settings.get("extra_charge_item")
        room_acct  = settings.get("room_revenue_account")
        extra_acct = settings.get("extra_charges_income_account")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer  = customer
        invoice.company   = company
        invoice.posting_date = nowdate()
        invoice.due_date     = nowdate()

        if settings.get("accounts_receivable_account"):
            invoice.debit_to = settings.accounts_receivable_account

        for charge in profile.charges:
            is_room = (charge.charge_type == "Room Charge")
            item_code = room_item if is_room else extra_item
            if not item_code:
                continue
            row = {
                "item_code": item_code,
                "item_name": charge.description or charge.charge_type,
                "description": charge.description or charge.charge_type,
                "qty": flt(charge.quantity) or 1,
                "rate": flt(charge.rate),
            }
            acct = room_acct if is_room else extra_acct
            if acct:
                row["income_account"] = acct
            invoice.append("items", row)

        if not invoice.get("items"):
            frappe.log_error(f"iHotel: No items to invoice for stay {self.name} — check Item settings")
            return None

        invoice.insert(ignore_permissions=True)
        invoice.submit()
        return invoice

    def _create_payment_entries(self, profile, invoice, customer, company):
        """Create a Payment Entry for each folio payment, allocated to the invoice."""
        from frappe.utils import flt, nowdate

        _mode_map = {
            "Cash": "Cash",
            "Visa": "Credit Card",
            "Mastercard": "Credit Card",
            "Amex": "Credit Card",
            "Bank Transfer": "Bank Transfer",
            "Cheque": "Cheque",
            "City Ledger": "Bank Transfer",
            "Complimentary": "Cash",
        }

        for payment in profile.payments:
            amount = flt(payment.rate)
            if not amount:
                continue
            try:
                mode = _mode_map.get(payment.payment_method, "Cash")
                pe = frappe.new_doc("Payment Entry")
                pe.payment_type     = "Receive"
                pe.company          = company
                pe.mode_of_payment  = mode
                pe.posting_date     = payment.date or nowdate()
                pe.party_type       = "Customer"
                pe.party            = customer
                pe.paid_amount      = amount
                pe.received_amount  = amount
                pe.append("references", {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": amount,
                })
                pe.insert(ignore_permissions=True)
                pe.submit()
            except Exception as e:
                frappe.log_error(
                    f"iHotel: Could not create Payment Entry for stay {self.name}: {str(e)}"
                )
