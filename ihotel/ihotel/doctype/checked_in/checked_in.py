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


# Payment Items.payment_method is a Link to Mode of Payment, so the stored
# value IS the ERPXpand Mode of Payment name — no translation table needed.
_DEFAULT_MODE_OF_PAYMENT = "Cash"


def _company_currency(company):
    """Return the company's base currency; memoised via Frappe's cache."""
    if not company:
        return "USD"
    return frappe.get_cached_value("Company", company, "default_currency") or "USD"


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
        """Compute total tax from the first rate_line's Rate Type tax_schedule (scalar)."""
        return round(sum(amt for _acct, amt in self._compute_tax_breakdown(net_total)), 2)

    def _compute_tax_breakdown(self, net_total):
        """Return per-row tax as [(tax_account, amount), ...] from the Rate Type tax_schedule.

        tax_account may be None when the Rate Type schedule did not set one;
        callers that need per-account posting should handle that case.
        """
        from frappe.utils import flt, cint
        rate_type_name = next(
            (r.rate_type for r in (self.rate_lines or []) if r.rate_type), None
        )
        if not rate_type_name:
            return []
        try:
            rt = frappe.get_cached_doc("Rate Type", rate_type_name)
        except Exception:
            return []
        amounts = []
        breakdown = []
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
            amt = round(amt, 2)
            amounts.append(amt)
            breakdown.append((row.tax_account, amt))
        return breakdown

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
                # No Sales Invoice (e.g. room-only folio in Night Audit JE mode
                # where Room Charges are skipped). Still post any folio payments
                # as standalone Receives against the Customer AR — the JE path
                # already booked AR via the Night Audit JE.
                if profile.get("payments"):
                    self._sync_folio_payments(profile, customer, company, invoice=None)
                    frappe.log_error(
                        title="iHotel checkout: payments posted without Sales Invoice",
                        message=(
                            f"Stay {self.name}: folio has payments but no Sales Invoice was built "
                            "(e.g. room-only folio with Night Audit Journal Entry mode). "
                            "Posted Payment Entries as standalone Receives against Debtors."
                        ),
                    )
                return

            self.db_set("sales_invoice", invoice.name, update_modified=False)
            self.db_set("invoice_sync_status", "Synced", update_modified=False)
            self.db_set("invoice_sync_error", "", update_modified=False)

            if profile.get("payments"):
                self._sync_folio_payments(profile, customer, company, invoice=invoice)

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
        """Build, insert and submit a Sales Invoice from the stay + folio.

        Items are posted **tax-exclusive** (net) and a Sales Taxes and Charges
        table is appended so tax breaks out per GL account (from the stay's
        Rate Type tax_schedule). Non-room folio charges (services, laundry,
        F&B) are sourced from the folio because they are posted net.

        Invariant relied on: `_create_folio` and `Laundry Order._post_to_folio`
        post non-Room folio rows at **net** rate; Room Charge rows are posted
        tax-inclusive and are not read here (we use rate_lines × nights).
        """
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

        nights = self.nights or 1
        room_net_total = 0.0
        service_net_total = 0.0

        # Room revenue: one SI item per rate_line, net × nights.
        # Skipped when the Night Audit JE mode is on — that path books room
        # revenue and tax directly to GL per schedule account.
        if not skip_room_on_invoice and room_item:
            for rl in (self.rate_lines or []):
                rate = flt(rl.amount)
                if rate <= 0:
                    continue
                row = {
                    "item_code": room_item,
                    "item_name": _("Room Charge — {0}").format(self.room or ""),
                    "description": getattr(rl, "rate_type", None) or "Room Charge",
                    "qty": nights,
                    "rate": rate,
                }
                acct = resolve_income_account("Room Charge", company)
                if acct:
                    row["income_account"] = acct
                invoice.append("items", row)
                room_net_total += rate * nights

        # Non-room charges from the folio (services, laundry, F&B, …).
        # Posted net per the folio invariant; billed at stored rate × qty.
        for charge in (profile.charges or []):
            if charge.charge_type == "Room Charge":
                continue
            rate = flt(charge.rate)
            qty = flt(charge.quantity) or 1
            if rate <= 0 and qty <= 0:
                continue
            if not extra_item:
                continue
            row = {
                "item_code": extra_item,
                "item_name": charge.description or charge.charge_type,
                "description": charge.description or charge.charge_type,
                "qty": qty,
                "rate": rate,
            }
            acct = resolve_income_account(charge.charge_type, company)
            if acct:
                row["income_account"] = acct
            invoice.append("items", row)
            service_net_total += rate * qty

        if not invoice.get("items"):
            frappe.log_error(f"iHotel: No items to invoice for stay {self.name} — check Item settings")
            return None

        # Tax: one Sales Taxes and Charges row per tax_account from the stay's
        # Rate Type tax_schedule. Tax is applied to the total SI net (room +
        # services) to match the current Checked In tax-compute convention
        # (_compute_tax uses total_charges = rate_lines + services).
        net_total_for_tax = round(room_net_total + service_net_total, 2)
        total_tax = 0.0
        if net_total_for_tax > 0:
            for tax_account, amount in (self._compute_tax_breakdown(net_total_for_tax) or []):
                amount = flt(amount)
                if amount <= 0:
                    continue
                if not tax_account:
                    frappe.log_error(
                        title=f"iHotel: Sales Invoice tax row missing tax_account — {self.name}",
                        message=(
                            f"Stay {self.name}: Rate Type tax_schedule has a row without "
                            "an ERPXpand Tax Account. Checkout Sales Invoice skipped tax for "
                            "this row — set the Tax Account on every Rate Tax Schedule row."
                        ),
                    )
                    continue
                invoice.append("taxes", {
                    "charge_type": "Actual",
                    "account_head": tax_account,
                    "description": _("Tax"),
                    "tax_amount": amount,
                })
                total_tax += amount

        # Reconciliation: SI gross (items + tax) vs folio gross (folio rows
        # are tax-inclusive for Room Charge, net for services). Log when
        # drift > 0.02; ERPNext's rounding_adjustment handles ≤0.02 drift.
        folio_gross = 0.0
        for c in (profile.charges or []):
            if skip_room_on_invoice and c.charge_type == "Room Charge":
                continue
            folio_gross += flt(c.amount)
        si_gross = round(room_net_total + service_net_total + total_tax, 2)
        if abs(round(folio_gross, 2) - si_gross) > 0.02:
            frappe.log_error(
                title=f"iHotel: Sales Invoice / folio reconciliation drift — {self.name}",
                message=(
                    f"Stay {self.name}: folio gross {folio_gross:.2f} vs SI gross "
                    f"{si_gross:.2f} — drift {(folio_gross - si_gross):+.2f}."
                ),
            )

        invoice.insert(ignore_permissions=True)
        invoice.submit()
        return invoice

    def _sync_folio_payments(self, profile, customer, company, invoice=None):
        """Create ERPXpand Payment Entries for folio payments not yet synced.

        Idempotent: folio rows that already have `payment_entry` set are skipped.
        When `invoice` is provided, the PE is allocated against it (SI mode).
        When `invoice` is None, the PE is a standalone Receive against the
        Customer AR (JE mode — room revenue already hit AR via the Night Audit JE).

        Per-row exceptions are logged and the batch continues. Returns the list
        of newly-created Payment Entry names.
        """
        from frappe.utils import flt, nowdate

        created = []
        failed = []  # per-row failure details for the caller / user
        for payment in (profile.payments or []):
            if payment.get("payment_entry"):
                continue
            # Convert to company currency so AR reconciliation works in a
            # single currency. The folio row keeps the original Amount +
            # Currency as an audit trail for the guest receipt.
            ex_rate = flt(payment.exchange_rate) or 1
            amount = round(flt(payment.rate) * ex_rate, 2)
            if amount <= 0:
                continue

            # payment.payment_method is now a Link to Mode of Payment, so
            # the stored value passes straight to the PE — no translation.
            mode = payment.payment_method or _DEFAULT_MODE_OF_PAYMENT

            try:
                # Resolve the paid_to account from the Mode of Payment's
                # company-specific default. ERPNext normally fills this in
                # validate(), but when we build the PE programmatically with
                # references attached, the order-of-operations occasionally
                # leaves paid_to unset — preempt that here.
                paid_to_acct = frappe.db.get_value(
                    "Mode of Payment Account",
                    {"parent": mode, "company": company},
                    "default_account",
                )
                paid_to_currency = (
                    frappe.db.get_value("Account", paid_to_acct, "account_currency")
                    if paid_to_acct else None
                ) or _company_currency(company)

                row_currency = payment.currency or _company_currency(company)
                row_amount   = flt(payment.rate)  # amount in the row's currency

                pe = frappe.new_doc("Payment Entry")
                pe.payment_type    = "Receive"
                pe.company         = company
                pe.mode_of_payment = mode
                pe.posting_date    = payment.date or nowdate()
                pe.party_type      = "Customer"
                pe.party           = customer
                if paid_to_acct:
                    pe.paid_to = paid_to_acct

                # Multi-currency routing. ERPNext's Payment Entry semantics:
                #   paid_amount     → in paid_from's currency (off the AR)
                #   received_amount → in paid_to's currency   (into the bank)
                #   base_paid_amount     = paid_amount × source_exchange_rate
                #   base_received_amount = received_amount × target_exchange_rate
                # source_exchange_rate converts paid_from → company (= 1 here
                # since AR is always in company currency for iHotel).
                pe.source_exchange_rate = 1
                if paid_to_currency == row_currency:
                    # Guest paid USD 85 into a USD-denominated bank account.
                    # paid_from (GHS Debtors) gets 1020 GHS taken off; paid_to
                    # (USD Ecobank) gets 85 USD added.
                    pe.paid_amount          = amount       # GHS off AR
                    pe.received_amount      = row_amount   # USD into bank
                    pe.target_exchange_rate = ex_rate      # USD → GHS
                elif paid_to_currency == _company_currency(company):
                    # Front desk physically converted the foreign currency
                    # before dropping it into the GHS cash drawer / bank.
                    # paid_to is in base; both amounts are base-currency equiv.
                    pe.paid_amount          = amount
                    pe.received_amount      = amount
                    pe.target_exchange_rate = 1
                else:
                    # paid_to is in a third currency that doesn't match either
                    # the row currency or the company currency. Ambiguous; fall
                    # back to base amounts so we don't mis-post.
                    pe.paid_amount          = amount
                    pe.received_amount      = amount
                    pe.target_exchange_rate = 1
                # Bank-type Modes of Payment (Credit Card, Cheque, Wire
                # Transfer, etc.) require a Reference No + Reference Date.
                # Fill from payment.detail (user-entered, e.g. "Visa 4321") or
                # synthesize from the folio row's own name. Harmless for
                # Cash-type modes.
                pe.reference_no = (
                    (payment.get("detail") or "").strip()
                    or f"IHOTEL-{payment.parent}-{payment.name[:8]}"
                )
                pe.reference_date = payment.date or nowdate()
                if invoice is not None:
                    pe.append("references", {
                        "reference_doctype": "Sales Invoice",
                        "reference_name":    invoice.name,
                        "allocated_amount":  amount,
                    })
                pe.insert(ignore_permissions=True)
                pe.submit()
                frappe.db.set_value(
                    "Payment Items", payment.name, "payment_entry", pe.name,
                    update_modified=False,
                )
                payment.payment_entry = pe.name
                created.append(pe.name)
            except Exception as e:
                err_msg = str(e)[:500]
                frappe.log_error(
                    f"iHotel: Payment Entry sync failed for stay {self.name}, "
                    f"folio row {payment.name} ({mode} {amount} {payment.currency or ''}): {err_msg}"
                )
                # Drop the failed row from the folio so total_payments reflects
                # only what actually hit GL. Without this, the folio claims the
                # guest settled while AR says otherwise. SQL-delete bypasses
                # the profile's delete-guard (the row never had a PE link, so
                # the guard wouldn't fire anyway, but we want to avoid any
                # Frappe child-row lifecycle surprises here).
                try:
                    frappe.db.sql(
                        "DELETE FROM `tabPayment Items` WHERE name = %s",
                        payment.name,
                    )
                except Exception:
                    pass
                failed.append({
                    "method": mode,
                    "amount": flt(payment.rate),
                    "currency": payment.currency or "",
                    "error": err_msg,
                })

        # Publish failures through frappe.flags so the top-level caller
        # (take_payment API) can surface them in its response + alert the
        # user on the UI. Also msgprint directly so users who save the
        # profile form manually see the issue immediately.
        if failed:
            existing = getattr(frappe.flags, "ihotel_payment_failures", None) or []
            frappe.flags.ihotel_payment_failures = existing + failed
            from frappe import _

            # Profile totals were computed + committed BEFORE this sync ran
            # (on_update fires post-save). We SQL-deleted the failed rows,
            # so total_payments / outstanding / status on the profile are
            # now stale — recompute and write via db.set_value so we don't
            # re-trigger validate/on_update recursion.
            profile.reload()
            profile.recalculate_amounts()
            profile.update_status()
            frappe.db.set_value(
                "iHotel Profile", profile.name,
                {
                    "total_amount":        profile.total_amount,
                    "total_payments":      profile.total_payments,
                    "outstanding_balance": profile.outstanding_balance,
                    "status":              profile.status,
                },
                update_modified=False,
            )

            lines = [
                _("{method} {amount} {currency} — {error}").format(**f)
                for f in failed
            ]
            frappe.msgprint(
                _("Some payments could not be posted to ERPXpand and have been removed from the folio. Fix the configuration below and take the payment again.") + "<br><br>" + "<br>".join(lines),
                title=_("Payment Posting Failed"),
                indicator="red",
            )
        return created

    def _create_payment_entries(self, profile, invoice, customer, company):
        """Back-compat shim — delegates to _sync_folio_payments."""
        return self._sync_folio_payments(profile, customer, company, invoice=invoice)

    def _sync_folio_payments_from_profile(self, profile):
        """Entry point used by iHotel Profile.on_update when a folio is Settled.

        Resolves settings + customer + (optional) SI, then delegates to
        _sync_folio_payments. Silent on misconfiguration so profile saves
        never break from a downstream sync issue.
        """
        try:
            if "erpnext" not in frappe.get_installed_apps():
                return
            settings = frappe.get_single("iHotel Settings")
            if not settings.get("enable_accounting_integration"):
                return
            company = settings.company
            if not company:
                return
            customer = self._get_or_create_customer(settings, company)
            if not customer:
                return

            invoice = None
            if self.sales_invoice:
                try:
                    candidate = frappe.get_doc("Sales Invoice", self.sales_invoice)
                    if candidate.docstatus == 1:
                        invoice = candidate
                except frappe.DoesNotExistError:
                    invoice = None

            self._sync_folio_payments(profile, customer, company, invoice=invoice)
        except Exception as e:
            frappe.log_error(
                f"iHotel: folio-triggered Payment Entry sync failed for stay "
                f"{self.name}: {e!s}"
            )


def on_payment_entry_cancel(doc, method=None):
    """Cascade a Payment Entry cancellation back to any iHotel folio row.

    When a PE linked to a folio payment row is cancelled, its GL entries are
    reversed — the money no longer exists on AR. The folio must reflect that:
    remove the row so `recalculate_amounts` drops the amount from
    `total_payments` and the profile transitions back to Open if it was
    Settled only because of this PE.

    Runs via hooks.py `doc_events` → `Payment Entry.on_cancel`.
    """
    rows = frappe.db.get_all(
        "Payment Items",
        filters={"payment_entry": doc.name, "parenttype": "iHotel Profile"},
        fields=["name", "parent"],
    )
    if not rows:
        return

    affected_profiles = set()
    for row in rows:
        # SQL delete bypasses the validate_linked_payment_rows_preserved guard
        # on iHotel Profile — that guard is meant to block *user* deletions,
        # not the PE-cancel cleanup path.
        frappe.db.sql(
            "DELETE FROM `tabPayment Items` WHERE name = %s",
            row.name,
        )
        affected_profiles.add(row.parent)

    for profile_name in affected_profiles:
        try:
            profile = frappe.get_doc("iHotel Profile", profile_name)
            # Save to recompute totals + flip status back to Open when a
            # settled folio loses its payment. on_update cascade is a no-op
            # since no unsynced rows remain.
            profile.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                f"iHotel: could not refresh profile {profile_name} after "
                f"Payment Entry {doc.name} cancel: {e!s}"
            )


@frappe.whitelist()
def take_payment(checked_in, payments, also_checkout=False):
    """Append payments to a stay's folio and sync them to ERPXpand Payment Entries.

    Used by the Take Payment dialog on the Checked In form. Accepts a JSON
    string or a list for `payments` (each row: date / payment_method / amount /
    detail / payment_status). When `also_checkout` is truthy and the folio
    settles (outstanding <= 0), runs the existing do_checkout flow so
    front desk can settle + check out in one submit.

    Returns {profile, outstanding, payment_entries, checked_out}.
    """
    import json
    from frappe.utils import flt, nowdate

    if isinstance(payments, str):
        payments = json.loads(payments or "[]")
    if not isinstance(payments, list):
        frappe.throw(_("payments must be a list of payment rows."))
    if isinstance(also_checkout, str):
        also_checkout = also_checkout.lower() in ("1", "true", "yes", "y")

    stay = frappe.get_doc("Checked In", checked_in)
    if stay.docstatus != 1:
        frappe.throw(_("Payments can only be taken on a submitted stay."))

    # Ensure folio exists; reuse the whitelisted helper so any existing
    # onboarding rules (e.g. iHotel Profile defaults) are honoured.
    if not stay.profile:
        create_folio(stay.name)
        stay.reload()

    profile = frappe.get_doc("iHotel Profile", stay.profile)

    for p in payments:
        amount = flt(p.get("amount") or p.get("rate"))
        if amount <= 0:
            continue
        currency = p.get("currency") or frappe.db.get_value(
            "Company", stay.get("company") or frappe.db.get_single_value("iHotel Settings", "company"),
            "default_currency",
        )
        exchange_rate = flt(p.get("exchange_rate")) or 1
        profile.append("payments", {
            "date":           p.get("date") or nowdate(),
            "payment_method": p.get("payment_method") or "Cash",
            "currency":       currency,
            "exchange_rate":  exchange_rate,
            "rate":           amount,
            "detail":         p.get("detail") or "",
            "payment_status": p.get("payment_status") or "Paid",
        })

    # validate() recalculates totals and auto-flips status; on_update triggers
    # _sync_folio_payments_from_profile → Payment Entries post there. Failed
    # rows are removed from the folio inside the sync, so after reload()
    # totals reflect only what actually posted to GL.
    frappe.flags.ihotel_payment_failures = []  # isolate failures from this call
    profile.save(ignore_permissions=True)
    profile.reload()

    pe_names = [row.payment_entry for row in profile.payments if row.payment_entry]
    failures = list(frappe.flags.get("ihotel_payment_failures") or [])
    frappe.flags.ihotel_payment_failures = []

    checked_out = False
    if also_checkout and not failures and flt(profile.outstanding_balance) <= 0:
        do_checkout(stay.name)
        checked_out = True

    return {
        "profile": profile.name,
        "outstanding": flt(profile.outstanding_balance),
        "payment_entries": pe_names,
        "failed_payments": failures,
        "checked_out": checked_out,
    }
