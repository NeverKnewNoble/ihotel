# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime, timedelta
from frappe.utils import get_datetime, getdate


def _resolve_default_customer_group(settings):
    """Return a safe non-group customer group for auto-created customers."""
    group = settings.get("default_customer_group") or "Individual"
    if frappe.db.get_value("Customer Group", group, "is_group"):
        fallback = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        return fallback or group
    return group


@frappe.whitelist()
def create_folio(checked_in_name):
	"""Manually create a folio for a submitted Checked In document."""
	doc = frappe.get_doc("Checked In", checked_in_name)
	if doc.docstatus != 1:
		frappe.throw(_("Folio can only be created for submitted documents."))
	doc._create_folio()
	return doc.profile


@frappe.whitelist()
def retry_sales_invoice_sync(checked_in_name):
	"""Re-attempt ERPXpand Sales Invoice creation for a stay that previously failed."""
	frappe.has_permission("Checked In", "write", checked_in_name, throw=True)
	doc = frappe.get_doc("Checked In", checked_in_name)
	if doc.status != "Checked Out":
		frappe.throw(_("Invoice sync can only be retried for checked-out stays."))
	if doc.sales_invoice:
		frappe.throw(_("A Sales Invoice ({0}) already exists for this stay.").format(doc.sales_invoice))
	doc._create_erp_invoice()
	status = frappe.db.get_value("Checked In", checked_in_name, "invoice_sync_status")
	return status


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


_HK_DEDUPE_WINDOW_MINUTES = 5  # Suppress duplicate service alerts within this window


@frappe.whitelist()
def notify_housekeeping(checked_in_name, service_type):
	"""
	Send an in-app (and email) notification to housekeepers for a guest service request.
	service_type: "Do Not Disturb", "Make Up Room", or "Turndown"

	Deduplication: suppresses a repeat notification for the same stay + service type
	within the configured dedupe window (default 5 minutes) to prevent alert fatigue.

	Targeting: if a Housekeeping Assignment links this room to specific housekeepers,
	only those assigned workers are notified. Falls back to all active housekeepers
	when no assignment exists (e.g. unassigned or DND where no action is needed).
	"""
	doc = frappe.get_doc("Checked In", checked_in_name)

	MESSAGES = {
		"Do Not Disturb": _("Room {0} — Guest {1} has set <strong>Do Not Disturb</strong>. Please do not enter the room."),
		"Make Up Room":   _("Room {0} — Guest {1} has requested <strong>Make Up Room</strong> service."),
		"Turndown":       _("Room {0} — Guest {1} has requested <strong>Turndown</strong> service."),
	}
	message_tmpl = MESSAGES.get(service_type)
	if not message_tmpl:
		frappe.throw(_("Unknown service type: {0}").format(service_type))

	# Dedupe guard: skip if the same alert was sent for this stay + service within the window
	from frappe.utils import add_to_date, now_datetime
	cutoff = add_to_date(now_datetime(), minutes=-_HK_DEDUPE_WINDOW_MINUTES)
	recent_duplicate = frappe.db.exists("Notification Log", {
		"document_type": "Checked In",
		"document_name": checked_in_name,
		"subject": ["like", f"%{service_type}%"],
		"creation": [">", cutoff],
	})
	if recent_duplicate:
		return True  # Silently skip — duplicate within dedupe window

	subject = _("[iHotel] {0} — Room {1}").format(service_type, doc.room)
	message = message_tmpl.format(doc.room, doc.guest)

	# Prefer assigned housekeepers for this room; fall back to all active housekeepers
	recipients = _get_assigned_housekeepers(doc.room) or frappe.get_all(
		"Housekeeper",
		filters={"is_active": 1},
		fields=["employee_name", "user", "email"],
	)

	for hk in recipients:
		if hk.user:
			frappe.get_doc({
				"doctype": "Notification Log",
				"subject": subject,
				"email_content": message,
				"for_user": hk.user,
				"type": "Alert",
				"document_type": "Checked In",
				"document_name": doc.name,
				"from_user": frappe.session.user,
			}).insert(ignore_permissions=True)
			frappe.publish_realtime("notification_bell", {}, user=hk.user)

		target_email = hk.email or (frappe.db.get_value("User", hk.user, "email") if hk.user else None)
		if target_email:
			frappe.sendmail(
				recipients=[target_email],
				subject=subject,
				message=message,
			)

	return True


def _get_assigned_housekeepers(room):
	"""
	Return active housekeepers currently assigned to this room via Housekeeping Assignment.
	Returns an empty list if none are assigned, signalling the caller to fall back.
	"""
	if not room:
		return []
	try:
		assignments = frappe.db.sql("""
			SELECT DISTINCT hk.employee_name, hk.user, hk.email
			FROM `tabHousekeeping Assignment` ha
			INNER JOIN `tabHousekeeping Assignment Room` har ON har.parent = ha.name
			INNER JOIN `tabHousekeeper` hk ON hk.name = ha.housekeeper
			WHERE har.room = %s
			  AND ha.status IN ('Assigned', 'In Progress')
			  AND hk.is_active = 1
		""", room, as_dict=True)
		return assignments
	except Exception:
		# Table may not exist or schema may differ; fall back gracefully
		return []


@frappe.whitelist()
def do_checkout(checked_in_name):
	"""Set status to Checked Out and stamp actual_check_out, then trigger post-checkout hooks."""
	from frappe.utils import flt
	doc = frappe.get_doc("Checked In", checked_in_name)

	if doc.status != "Checked In":
		frappe.throw(_("Only guests with status 'Checked In' can be checked out."))

	# Guard: night audit coverage (db_set bypasses validate, so enforce here)
	doc._check_night_audit_coverage()

	# Guard: outstanding balance
	profile_name = frappe.db.get_value("Checked In", checked_in_name, "profile") or doc.profile
	if profile_name:
		outstanding = frappe.db.get_value("iHotel Profile", profile_name, "outstanding_balance") or 0
		if flt(outstanding) > 0:
			frappe.throw(
				_("Cannot check out {0}. Outstanding balance of {1} must be settled before checkout.").format(
					doc.guest, frappe.format_value(outstanding, {"fieldtype": "Currency"})
				),
				title=_("Outstanding Balance")
			)

	doc.db_set("status", "Checked Out", update_modified=True)
	doc.db_set("actual_check_out", frappe.utils.now_datetime(), update_modified=True)

	# Reload and run post-submit hooks manually (sync room, stats, invoice)
	doc.reload()
	doc.on_update_after_submit()

	return True


@frappe.whitelist()
def get_night_audit_checkout_blockers(checked_in_name):
	"""Return formatted dates missing Night Audit (for desk Check Out button)."""
	frappe.has_permission("Checked In", "read", checked_in_name, throw=True)
	doc = frappe.get_doc("Checked In", checked_in_name)
	return {"missing_dates": doc._get_missing_night_audit_dates()}


@frappe.whitelist()
def move_room(checked_in_name, new_room, reason=None):
	"""
	Move a checked-in guest to a different room.
	Transfers all stay info, folio room reference, and charge descriptions to the new room.
	Old room is marked Vacant Dirty for housekeeping.
	"""
	checked_in = frappe.get_doc("Checked In", checked_in_name)

	if checked_in.status != "Checked In":
		frappe.throw(_("Room move is only allowed for guests who are currently checked in."))

	if checked_in.room == new_room:
		frappe.throw(_("Guest is already assigned to room {0}.").format(new_room))

	# Confirm the destination room is ready
	new_room_doc = frappe.get_doc("Room", new_room)
	READY = {"Available", "Inspected", "Vacant Clean", "Housekeeping"}
	if new_room_doc.status not in READY:
		frappe.throw(_("Room {0} is not available for a room move (current status: {1}).").format(
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

	# Acquire a row-level lock on the destination room to prevent simultaneous moves
	frappe.db.sql("SELECT name FROM `tabRoom` WHERE name=%s FOR UPDATE", new_room)

	# Re-verify no conflict appeared since the pre-check above (race guard)
	conflict_after_lock = frappe.db.exists("Checked In", {
		"room": new_room,
		"status": ["in", ["Reserved", "Checked In"]],
		"docstatus": 1,
		"name": ["!=", checked_in_name],
	})
	if conflict_after_lock:
		frappe.throw(
			_("Room {0} was just occupied by another guest. Please choose a different room.").format(new_room)
		)

	# ── Update Checked In record ──────────────────────────────────────────────
	new_room_type = frappe.db.get_value("Room", new_room, "room_type")
	checked_in.db_set("room", new_room, update_modified=False)
	if new_room_type:
		checked_in.db_set("room_type", new_room_type, update_modified=False)

	# ── Update folio (iHotel Profile) room reference ──────────────────────────
	profile_name = checked_in.profile or frappe.db.get_value(
		"iHotel Profile", {"hotel_stay": checked_in_name}, "name"
	)
	if profile_name:
		profile = frappe.get_doc("iHotel Profile", profile_name)
		profile.room = new_room

		# Update room reference in existing charge descriptions
		for charge in profile.charges:
			if old_room and old_room in (charge.description or ""):
				charge.description = charge.description.replace(old_room, new_room)

		profile.save(ignore_permissions=True)

	# ── Update room statuses ──────────────────────────────────────────────────
	if old_room:
		frappe.db.set_value("Room", old_room, "status", "Vacant Dirty")

	new_room_doc.status = "Occupied"
	new_room_doc.save(ignore_permissions=True)

	# ── Log the move ──────────────────────────────────────────────────────────
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
		_("Guest moved from Room {0} to Room {1}. All charges and payments have been transferred.").format(
			old_room or _("(none)"), new_room
		),
		indicator="green",
		alert=True,
	)

	return True


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

	# Only show rooms that are ready to sell (Available, Vacant Clean, or
	# Inspected). Prevents the front desk from assigning a room that is
	# occupied, dirty, being cleaned, or out of service.
	conditions.append("status IN ('Available', 'Vacant Clean', 'Inspected')")

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
        if self.status == "Checked Out":
            self._check_night_audit_coverage()
            # Always read from DB — self.profile may be stale if folio was created after submit
            profile_name = frappe.db.get_value("Checked In", self.name, "profile") or self.profile
            if profile_name:
                outstanding = frappe.db.get_value("iHotel Profile", profile_name, "outstanding_balance") or 0
                if outstanding > 0:
                    frappe.throw(
                        _("Cannot check out {0}. Outstanding balance of {1} must be settled before checkout.").format(
                            self.guest, frappe.format_value(outstanding, {"fieldtype": "Currency"})
                        ),
                        title=_("Outstanding Balance")
                    )

    def _get_missing_night_audit_dates(self):
        """
        Each calendar date from check-in through yesterday must have a Night Audit
        before checkout (today's audit is not required yet). If Night Audit is
        submittable, only submitted documents count as posted.
        """
        from frappe.utils import getdate, add_days, nowdate, date_diff

        start = getdate(self.actual_check_in or self.expected_check_in)
        today = getdate(nowdate())
        if start >= today:
            return []

        filters = {
            "audit_date": ["between", [str(start), str(add_days(today, -1))]],
        }
        if frappe.get_meta("Night Audit").is_submittable:
            filters["docstatus"] = 1

        posted = set(
            str(d)
            for d in frappe.get_all("Night Audit", filters=filters, pluck="audit_date")
        )

        nights = date_diff(today, start)
        missing = []
        for i in range(nights):
            d = getdate(add_days(start, i))
            if str(d) not in posted:
                missing.append(frappe.format_value(d, {"fieldtype": "Date"}))
        return missing

    def _check_night_audit_coverage(self):
        """Block checkout if any night of the stay is missing a Night Audit record."""
        missing = self._get_missing_night_audit_dates()
        if missing:
            frappe.throw(
                _("Cannot check out. Night Audit has not been posted for: {0}").format(
                    ", ".join(missing)
                ),
                title=_("Night Audit Required"),
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
            # Use calendar dates (not timedelta.days) so a stay like Apr-8 14:00 → Apr-9 11:00
            # (21 hours, but one hotel night) correctly passes the minimum-stay check.
            calendar_nights = (getdate(self.expected_check_out) - getdate(self.expected_check_in)).days
            if calendar_nights < 1:
                frappe.throw(_("Minimum stay is 1 night."))

        if self.is_new() and self.expected_check_in:
            from frappe.utils import nowdate
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

        # Read status directly from DB to avoid Frappe's document cache,
        # which can hold a stale value after raw db.set_value updates elsewhere
        # (e.g. move_room, night audit).
        row = frappe.db.sql(
            "SELECT status FROM `tabRoom` WHERE name=%s", self.room, as_dict=True
        )
        room_status = row[0].status if row else None

        # Block rooms that are physically unavailable for a new stay.
        # Vacant Dirty is intentionally allowed — the room is free, housekeeping will clean before guest goes up.
        UNAVAILABLE = ("Out of Order", "Out of Service", "Occupied", "Occupied Dirty", "Occupied Clean")
        if room_status in UNAVAILABLE:
            frappe.throw(
                _("Room {0} is {1} and cannot be booked.").format(self.room, room_status)
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

    def calculate_total_amount(self):
        from frappe.utils import flt
        if self.expected_check_in and self.expected_check_out:
            checked_in_dt = get_datetime(self.expected_check_in)
            check_out_dt  = get_datetime(self.expected_check_out)
            nights = (check_out_dt - checked_in_dt).days
            self.nights = max(nights, 0)

        nights           = self.nights or 0
        rate_lines_total = round(sum(flt(r.amount) for r in (self.rate_lines or [])), 2)
        svc_total        = flt(self.additional_services_total)

        self.total_charges = round(rate_lines_total + svc_total, 2)
        self.tax           = self._compute_tax(self.total_charges)
        self.total_amount  = round(self.total_charges + self.tax, 2)
        # room_rate = the per-night price (sum of rate line amounts after discounts).
        # Rate line amounts already represent the nightly rate — do NOT divide by nights,
        # as that would give a fractional rate when total_charges is the per-night total.
        self.room_rate = rate_lines_total

    def _compute_tax(self, net_total):
        """Compute tax from the first rate_line's Rate Type tax_schedule."""
        from frappe.utils import flt, cint
        rate_type_name = next(
            (r.rate_type for r in (self.rate_lines or []) if r.rate_type), None
        )
        if not rate_type_name:
            return 0.0
        try:
            rt = frappe.get_cached_doc("Rate Type", rate_type_name)
        except Exception:
            return 0.0
        amounts = []
        for row in (rt.tax_schedule or []):
            ct   = row.charge_type or "On Net Total"
            rate = flt(row.rate)
            amt  = 0.0
            if ct == "On Net Total":
                amt = net_total * rate / 100
            elif ct == "Actual":
                amt = rate
            elif ct == "On Previous Row Amount":
                idx = cint(row.row_id or 1) - 1
                amt = (amounts[idx] if idx < len(amounts) else 0) * rate / 100
            elif ct == "On Previous Row Total":
                idx = cint(row.row_id or 1) - 1
                amt = (net_total + sum(amounts[:idx + 1])) * rate / 100
            amounts.append(round(amt, 2))
        return round(sum(amounts), 2)

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

    def before_cancel(self):
        """Break the Profile back-link before Frappe's cancel link-check runs."""
        if self.profile:
            frappe.db.set_value("iHotel Profile", self.profile, "hotel_stay", None,
                                update_modified=False)

    def on_trash(self):
        """Delete the linked Profile before Frappe's trash link-check runs."""
        if self.profile:
            try:
                frappe.delete_doc("iHotel Profile", self.profile,
                                  ignore_permissions=True, force=True)
            except Exception:
                pass

    def on_submit(self):
        """
        Update room status when hotel stay is submitted.
        Auto-create a folio and post the initial room charge.
        Performs a final locked room availability re-check to prevent race conditions.
        """
        self.db_set("status", "Checked In", update_modified=False)
        if not self.actual_check_in:
            self.db_set("actual_check_in", frappe.utils.now_datetime(), update_modified=False)
        self._lock_and_verify_room()
        self.mark_room_as_occupied()
        self._create_folio()

    def _lock_and_verify_room(self):
        """
        Acquire a row-level lock on the target room and re-verify availability.
        Called from on_submit so the check happens inside the commit transaction,
        preventing two simultaneous check-ins from both succeeding for the same room.
        """
        if not self.room:
            return
        # Lock the room row for the duration of this transaction
        frappe.db.sql("SELECT name FROM `tabRoom` WHERE name=%s FOR UPDATE", self.room)

        # Re-check for overlapping active stays now that we hold the lock
        conflict = frappe.db.sql("""
            SELECT name FROM `tabChecked In`
            WHERE room = %s
            AND status IN ('Reserved', 'Checked In')
            AND docstatus = 1
            AND name != %s
            AND expected_check_in < %s
            AND expected_check_out > %s
        """, (self.room, self.name or "", self.expected_check_out, self.expected_check_in),
            as_dict=True)

        if conflict:
            frappe.throw(
                _("Room {0} was just taken by another reservation ({1}). Please assign a different room.").format(
                    self.room, conflict[0].name
                ),
                title=_("Room Conflict")
            )

    def _create_folio(self):
        """Create an iHotel Profile (folio) for this stay if one doesn't exist yet."""
        existing = frappe.db.get_value("iHotel Profile", {"hotel_stay": self.name}, "name")
        if existing:
            self.db_set("profile", existing, update_modified=False)
            return

        # Set room and guest explicitly: fetch_from does not reliably persist on programmatic insert,
        # and POS / reports join folio to Room via p.room (must be stored).
        profile = frappe.get_doc({
            "doctype": "iHotel Profile",
            "hotel_stay": self.name,
            "status": "Open",
            "room": self.room,
            "guest": self.guest,
        })
        profile.insert(ignore_permissions=True)
        self.db_set("profile", profile.name, update_modified=False)

        from frappe.utils import flt, nowdate

        no_post = frappe.db.get_value("Checked In", self.name, "no_post") or self.no_post

        # ── First-night room charge ───────────────────────────────────────────
        # Post the first night immediately so the folio is never empty at check-in.
        # Night Audit posts subsequent nights; its duplicate guard skips this date.
        # Charge is posted tax-inclusive so the folio's Total Charges matches the
        # stay's Total (incl. Tax) — tax is computed from the rate_lines[0].rate_type tax_schedule.
        rate_lines_total = round(sum(flt(r.amount) for r in (self.rate_lines or [])), 2)
        if not no_post and rate_lines_total > 0:
            check_in_date = getdate(self.actual_check_in or self.expected_check_in)
            nightly_tax = self._compute_tax(rate_lines_total)
            nightly_total_incl_tax = round(rate_lines_total + nightly_tax, 2)
            profile.post_charge(
                charge_type="Room Charge",
                description=_("Nightly room charge — Room {0} ({1})").format(
                    self.room or "", check_in_date
                ),
                rate=nightly_total_incl_tax,
                quantity=1,
                reference_doctype="Checked In",
                reference_name=self.name,
                charge_date=check_in_date,
            )
        elif no_post:
            frappe.log_error(
                title=f"iHotel: No Post active for {self.name}",
                message=f"Stay {self.name} has no_post=1. Room charges are blocked at check-in and night audit."
            )

        # ── Additional services ──────────────────────────────────────────────
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

        # ── Deposit / payment recording ──────────────────────────────────────
        # Only record actual collected deposits. Do NOT pre-fill a "Pending payment"
        # placeholder — it creates a false balance before charges are posted.
        if flt(self.deposit_amount) > 0:
            profile.append("payments", {
                "date": nowdate(),
                "payment_method": self.deposit_method or "Cash",
                "detail": self.payment_detail or _("Deposit collected at check-in"),
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
                if room.status not in ("Vacant Dirty", "Vacant Clean"):
                    room.status = "Vacant Dirty"
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
        """Create a Sales Invoice (and Payment Entries) in ERPXpand on checkout.

        Persists outcome in invoice_sync_status/invoice_sync_error so front desk
        can see failures and trigger a retry without re-doing the full checkout.
        """
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
                if profile.get("payments"):
                    frappe.log_error(
                        title="iHotel checkout: payments without Sales Invoice",
                        message=(
                            f"Stay {self.name}: folio has payments but no Sales Invoice was built "
                            "(e.g. room-only folio with Night Audit Journal Entry mode). "
                            "Record receipts in ERPXpand manually if needed."
                        ),
                    )
                return

            self.db_set("sales_invoice", invoice.name, update_modified=False)
            self.db_set("invoice_sync_status", "Synced", update_modified=False)
            self.db_set("invoice_sync_error", "", update_modified=False)

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
            error_msg = str(e)
            frappe.log_error(f"iHotel: Error creating Sales Invoice for {self.name}: {error_msg}")
            # Persist failure so the retry button in the form becomes actionable
            self.db_set("invoice_sync_status", "Failed", update_modified=False)
            self.db_set("invoice_sync_error", error_msg[:500], update_modified=False)
            frappe.msgprint(
                _("Checkout complete, but Sales Invoice could not be auto-created. "
                  "Use Retry Invoice Sync on the form or create it manually. Error has been logged."),
                indicator="orange",
                alert=True,
            )

    def _get_or_create_customer(self, settings, company):
        """Return ERPXpand Customer name, creating one from the Guest if needed.
        Auto-creation uses ignore_permissions because it runs in a system context
        (on_update_after_submit / night audit). Actor and reason are logged.
        """
        if not self.guest:
            return None

        guest_name = frappe.db.get_value("Guest", self.guest, "guest_name") or self.guest

        # Try exact match first
        customer = frappe.db.get_value("Customer", {"customer_name": guest_name})
        if customer:
            return customer

        guest_phone = frappe.db.get_value("Guest", self.guest, "phone") if self.guest else None
        try:
            mobile = str(guest_phone) if guest_phone else None
            cust = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": guest_name,
                "customer_type": "Individual",
                "customer_group": _resolve_default_customer_group(settings),
                "territory": settings.get("default_territory") or "All Territories",
                "mobile_no": mobile,
                "mobile_number": mobile,
            })
            # Bypass used here because checkout / night-audit may run as a system user
            # that lacks Customer create rights. Actor logged for audit trail.
            cust.insert(ignore_permissions=True)
            frappe.log_error(
                title=f"iHotel: auto-created Customer for guest {self.guest}",
                message=f"Actor: {frappe.session.user} | Stay: {self.name} | Customer: {cust.name}"
            )
            return cust.name
        except Exception as e:
            frappe.log_error(f"iHotel: Could not create Customer for guest {self.guest}: {str(e)}")
            return None

    def _build_sales_invoice(self, profile, customer, company, settings):
        """Build, insert and submit a Sales Invoice from the folio charges."""
        from frappe.utils import flt, nowdate
        from ihotel.ihotel.doctype.ihotel_settings.ihotel_settings import resolve_income_account

        room_item  = settings.get("room_charge_item")
        extra_item = settings.get("extra_charge_item")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer  = customer
        invoice.company   = company
        invoice.posting_date = nowdate()
        invoice.due_date     = nowdate()

        if settings.get("accounts_receivable_account"):
            invoice.debit_to = settings.accounts_receivable_account

        skip_room_on_invoice = (
            "erpnext" in frappe.get_installed_apps()
            and settings.get("enable_accounting_integration")
            and settings.get("post_room_revenue_via_night_audit_je")
        )

        # Per-charge-type income account resolution. Room Charge and any other
        # charge type (F&B, Laundry, Spa, Minibar, …) pick their credit account
        # from the Income Accounts table on iHotel Settings — keyed by charge_type.
        for charge in profile.charges:
            if skip_room_on_invoice and charge.charge_type == "Room Charge":
                continue
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
            acct = resolve_income_account(charge.charge_type, company)
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
