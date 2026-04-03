# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt
"""
Booking.com iCal Phase-1 sync.

Polls the Booking.com iCal feed configured in iHotel Settings every 30 minutes,
parses VEVENT entries, and creates confirmed Reservations for new bookings.
Cancellations update the existing Reservation status.
"""

import urllib.request
import frappe
from frappe import _


# ── Public entry point ────────────────────────────────────────────────────────

def sync_bookings():
    """Fetch the Booking.com iCal feed and sync all events into Reservations."""
    settings = frappe.get_single("iHotel Settings")

    if not settings.get("booking_com_enabled"):
        return

    url = (settings.get("booking_com_ical_url") or "").strip()
    if not url:
        frappe.log_error(
            "Booking.com iCal sync: no iCal URL configured in iHotel Settings → Booking.com.",
            title="Booking.com Sync"
        )
        return

    try:
        raw = _fetch_ical(url)
    except Exception as e:
        frappe.log_error(
            f"Booking.com iCal sync: failed to fetch feed.\nURL: {url}\nError: {e}",
            title="Booking.com Sync"
        )
        return

    events = _parse_ical(raw)
    synced = 0

    for event in events:
        try:
            if _sync_event(event):
                synced += 1
        except Exception as e:
            frappe.db.rollback()  # prevent orphan Guest rows from being committed later
            uid = event.get("UID", "unknown")
            frappe.log_error(
                f"Booking.com iCal sync: error on UID {uid}.\nError: {e}",
                title="Booking.com Sync"
            )

    frappe.db.set_single_value(
        "iHotel Settings", "booking_com_last_sync", frappe.utils.now_datetime()
    )
    frappe.db.commit()

    if synced:
        frappe.logger().info(f"Booking.com iCal sync: {synced} new reservation(s) created.")
    elif events:
        # Feed had events but none were imported — surface this so staff know
        frappe.log_error(
            f"Booking.com iCal sync completed: 0 of {len(events)} event(s) were imported. "
            f"Check individual UID errors above.",
            title="Booking.com Sync — No Events Imported"
        )


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_ical(url):
    """Download raw iCal text from the given URL. Enforces HTTPS and retries up to 3 times."""
    import time
    if not url.lower().startswith("https://"):
        frappe.throw(_("Booking.com iCal URL must use HTTPS. Please update the URL in iHotel Settings."))
    req = urllib.request.Request(url, headers={"User-Agent": "iHotel/1.0"})
    last_exc = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(5)
    raise last_exc


# ── Parse ─────────────────────────────────────────────────────────────────────

def _parse_ical(text):
    """
    Parse iCal text into a list of property dicts, one per VEVENT.
    Handles RFC 5545 line folding (continuation lines start with space/tab).
    """
    # Unfold folded lines
    for sep in ("\r\n ", "\r\n\t", "\n ", "\n\t"):
        text = text.replace(sep, "")

    events = []
    in_event = False
    current = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT":
            in_event = False
            if current:
                events.append(current)
        elif in_event and ":" in line:
            # Split on the FIRST colon only to preserve values that contain colons
            # (URLs, times like "15:00", descriptions like "Arrival: 15:00").
            colon_idx = line.index(":")
            key_part  = line[:colon_idx]
            value     = line[colon_idx + 1:]
            # Strip property parameters (e.g. DTSTART;VALUE=DATE → DTSTART)
            key = key_part.split(";")[0].upper()
            current[key] = value

    return events


def _parse_ical_date(value):
    """Convert iCal date token (YYYYMMDD or YYYYMMDDTHHMMSSZ) to YYYY-MM-DD string."""
    if not value:
        return None
    date_part = value.split("T")[0].replace("-", "")
    if len(date_part) == 8:
        return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
    return None


def _parse_description(raw_desc):
    """
    Extract structured fields from Booking.com DESCRIPTION.
    Booking.com uses 'Key: value\\n' pairs inside the description.
    Returns a flat dict with snake_case keys.
    """
    data = {}
    text = raw_desc.replace("\\n", "\n").replace("\\,", ",")
    for line in text.splitlines():
        line = line.strip()
        if ": " in line:
            key, _, val = line.partition(": ")
            data[key.strip().lower().replace(" ", "_")] = val.strip()
    return data


def _parse_guest_name(summary):
    """
    Extract guest name from SUMMARY.
    Booking.com format: 'John Doe (Booking.com - 1234567890)'
    or just 'John Doe' for older formats.
    """
    if not summary:
        return None
    if "(" in summary:
        return summary[: summary.index("(")].strip()
    return summary.strip() or None


# ── Sync one event ────────────────────────────────────────────────────────────

def _sync_event(event):
    """
    Process one VEVENT.
    - New booking  → create Reservation, return True
    - Seen before  → if now CANCELLED, cancel the Reservation; return False
    - Cancelled    → skip; return False
    """
    uid = event.get("UID", "").strip()
    if not uid:
        return False

    status = event.get("STATUS", "CONFIRMED").upper()

    existing = frappe.db.get_value("Reservation", {"booking_com_ref": uid}, "name")

    if existing:
        if status == "CANCELLED":
            res = frappe.get_doc("Reservation", existing)
            if res.status != "cancelled":
                res.db_set("status", "cancelled")
                res.db_set("cancellation_reason", "Guest Request")
                res.db_set("cancellation_number", f"BCom-{uid[:12]}")
                # Calculate cancellation fee (db_set bypasses validate, so call it manually)
                res.reload()
                res.calculate_cancellation_fee()
                if res.cancellation_fee:
                    res.db_set("cancellation_fee", res.cancellation_fee, update_modified=False)
                frappe.db.commit()
        return False

    if status == "CANCELLED":
        return False  # Never seen — nothing to cancel

    # ── Parse dates ───────────────────────────────────────────────────────────
    check_in  = _parse_ical_date(event.get("DTSTART", ""))
    check_out = _parse_ical_date(event.get("DTEND", ""))

    if not check_in or not check_out:
        frappe.log_error(
            f"Booking.com iCal sync: missing dates for UID {uid}.",
            title="Booking.com Sync"
        )
        return False

    # ── Parse description ─────────────────────────────────────────────────────
    desc_data  = _parse_description(event.get("DESCRIPTION", ""))
    guest_name = desc_data.get("guest_name") or _parse_guest_name(event.get("SUMMARY", ""))

    # ── Get or create Guest profile ───────────────────────────────────────────
    # Match by email first to avoid merging two different guests with the same name.
    guest_link = None
    email = desc_data.get("email", "")
    if email:
        guest_link = frappe.db.get_value("Guest", {"email": email}, "name")
    if not guest_link and guest_name:
        guest_link = frappe.db.get_value("Guest", {"guest_name": guest_name}, "name")
    if not guest_link and guest_name:
        g = frappe.get_doc({
            "doctype": "Guest",
            "guest_name": guest_name,
            "phone":      desc_data.get("phone", ""),
            "email":      email,
        })
        g.insert(ignore_permissions=True)
        guest_link = g.name

    # ── Resolve Booking.com business source (if configured) ───────────────────
    bcom_source = (
        frappe.db.get_value("Business Source Category", "Booking.com", "name")
        or frappe.db.get_value(
            "Business Source Category",
            {"business_source_category_name": "Booking.com"},
            "name",
        )
    )

    adults   = max(1, _safe_int(desc_data.get("adults"), 1))
    children = max(0, _safe_int(desc_data.get("children"), 0))

    # ── Create Reservation ────────────────────────────────────────────────────
    res = frappe.get_doc({
        "doctype":                   "Reservation",
        "guest":                     guest_link,
        "full_name":                 guest_name or "",
        "phone_number":              desc_data.get("phone", ""),
        "email_address":             desc_data.get("email", ""),
        "check_in_date":             check_in,
        "check_out_date":            check_out,
        "adults":                    adults,
        "children":                  children,
        "status":                    "confirmed",
        "booking_com_ref":           uid,
        "business_source_category":  bcom_source or "",
        "guarantee_type":            "No Guarantee",
        "special_requests":          desc_data.get("special_requests", ""),
    })
    res.flags.from_booking_com = True  # bypass past-date validation in reservation.py
    res.insert(ignore_permissions=True)
    frappe.db.commit()
    return True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_int(value, default=0):
    """Convert value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
