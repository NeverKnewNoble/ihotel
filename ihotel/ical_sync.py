# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt
"""
Generic OTA iCal sync engine for iHotel.

Each OTA platform (Booking.com, Expedia, Airbnb, Agoda, Trip.com, Tripadvisor)
uses the same iCal protocol. Call sync_platform(platform_key) from tasks.py
for each platform — the logic is identical, only the config differs.
"""

import urllib.request
import frappe
from frappe import _


# ── Platform registry ─────────────────────────────────────────────────────────

PLATFORMS = {
    "booking_com": {
        "label":           "Booking.com",
        "enabled_field":   "booking_com_enabled",
        "url_field":       "booking_com_ical_url",
        "last_sync_field": "booking_com_last_sync",
        "ref_field":       "booking_com_ref",
        "color":           "#0071c2",
        "cancel_prefix":   "BCom",
        "source_name":     "Booking.com",
    },
    "expedia": {
        "label":           "Expedia",
        "enabled_field":   "expedia_enabled",
        "url_field":       "expedia_ical_url",
        "last_sync_field": "expedia_last_sync",
        "ref_field":       "expedia_ref",
        "color":           "#00355F",
        "cancel_prefix":   "Expedia",
        "source_name":     "Expedia",
    },
    "airbnb": {
        "label":           "Airbnb",
        "enabled_field":   "airbnb_enabled",
        "url_field":       "airbnb_ical_url",
        "last_sync_field": "airbnb_last_sync",
        "ref_field":       "airbnb_ref",
        "color":           "#FF5A5F",
        "cancel_prefix":   "Airbnb",
        "source_name":     "Airbnb",
    },
    "agoda": {
        "label":           "Agoda",
        "enabled_field":   "agoda_enabled",
        "url_field":       "agoda_ical_url",
        "last_sync_field": "agoda_last_sync",
        "ref_field":       "agoda_ref",
        "color":           "#012169",
        "cancel_prefix":   "Agoda",
        "source_name":     "Agoda",
    },
    "trip_com": {
        "label":           "Trip.com",
        "enabled_field":   "trip_com_enabled",
        "url_field":       "trip_com_ical_url",
        "last_sync_field": "trip_com_last_sync",
        "ref_field":       "trip_com_ref",
        "color":           "#1A6FD4",
        "cancel_prefix":   "TripCom",
        "source_name":     "Trip.com",
    },
    "tripadvisor": {
        "label":           "Tripadvisor",
        "enabled_field":   "tripadvisor_enabled",
        "url_field":       "tripadvisor_ical_url",
        "last_sync_field": "tripadvisor_last_sync",
        "ref_field":       "tripadvisor_ref",
        "color":           "#34E0A1",
        "cancel_prefix":   "TripAdv",
        "source_name":     "Tripadvisor",
    },
}


# ── Public entry point ────────────────────────────────────────────────────────

def sync_platform(platform_key):
    """Fetch an OTA iCal feed and sync all events into Reservations."""
    cfg = PLATFORMS.get(platform_key)
    if not cfg:
        frappe.log_error(title="OTA iCal Sync", message=f"Unknown platform key: {platform_key}")
        return

    label    = cfg["label"]
    settings = frappe.get_single("iHotel Settings")

    if not settings.get(cfg["enabled_field"]):
        return

    url = (settings.get(cfg["url_field"]) or "").strip()
    if not url:
        frappe.log_error(
            title=f"{label} Sync",
            message=f"{label} iCal sync: no iCal URL configured in iHotel Settings.",
        )
        return

    try:
        raw = _fetch_ical(url)
    except Exception as e:
        frappe.log_error(
            title=f"{label} Sync",
            message=f"{label} iCal sync: failed to fetch feed.\nURL: {url}\nError: {e}",
        )
        return

    events = _parse_ical(raw)
    synced = 0

    for event in events:
        try:
            if _sync_event(event, cfg):
                synced += 1
        except Exception as e:
            frappe.db.rollback()
            uid = event.get("UID", "unknown")
            frappe.log_error(
                title=f"{label} Sync",
                message=f"{label} iCal sync: error on UID {uid}.\nError: {e}",
            )

    frappe.db.set_single_value(
        "iHotel Settings", cfg["last_sync_field"], frappe.utils.now_datetime()
    )
    frappe.db.commit()

    if synced:
        frappe.logger().info(f"{label} iCal sync: {synced} new reservation(s) created.")


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_ical(url):
    """Download raw iCal text. Enforces HTTPS, retries up to 3 times."""
    import time
    if not url.lower().startswith("https://"):
        frappe.throw(_("iCal URL must use HTTPS. Please update the URL in iHotel Settings."))
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
            colon_idx = line.index(":")
            key_part  = line[:colon_idx]
            value     = line[colon_idx + 1:]
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
    Extract structured fields from OTA DESCRIPTION.
    Most platforms use 'Key: value\\n' pairs inside the description.
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
    Common OTA format: 'John Doe (Platform - 1234567890)' or just 'John Doe'.
    """
    if not summary:
        return None
    if "(" in summary:
        return summary[: summary.index("(")].strip()
    return summary.strip() or None


# ── Sync one event ────────────────────────────────────────────────────────────

def _sync_event(event, cfg):
    """
    Process one VEVENT.
    - New booking  → create Reservation, return True
    - Seen before  → if now CANCELLED, cancel the Reservation; return False
    - Cancelled    → skip; return False
    """
    uid = event.get("UID", "").strip()
    if not uid:
        return False

    label     = cfg["label"]
    ref_field = cfg["ref_field"]
    status    = event.get("STATUS", "CONFIRMED").upper()

    existing = frappe.db.get_value("Reservation", {ref_field: uid}, "name")

    if existing:
        if status == "CANCELLED":
            res = frappe.get_doc("Reservation", existing)
            if res.status != "cancelled":
                res.db_set("status", "cancelled")
                res.db_set("cancellation_reason", "Guest Request")
                res.db_set("cancellation_number", f"{cfg['cancel_prefix']}-{uid[:12]}")
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
            title=f"{label} Sync",
            message=f"{label} iCal sync: missing dates for UID {uid}.",
        )
        return False

    # ── Parse description ─────────────────────────────────────────────────────
    desc_data  = _parse_description(event.get("DESCRIPTION", ""))
    guest_name = desc_data.get("guest_name") or _parse_guest_name(event.get("SUMMARY", ""))

    # ── Get or create Guest profile ───────────────────────────────────────────
    guest_link = None
    email = desc_data.get("email", "")
    if email:
        guest_link = frappe.db.get_value("Guest", {"email": email}, "name")
    if not guest_link and guest_name:
        guest_link = frappe.db.get_value("Guest", {"guest_name": guest_name}, "name")
    if not guest_link and guest_name:
        phone = _sanitize_phone(desc_data.get("phone", ""))
        g = frappe.get_doc({
            "doctype":    "Guest",
            "guest_name": guest_name,
            "phone":      phone,
            "email":      email,
        })
        try:
            g.insert(ignore_permissions=True)
        except frappe.InvalidPhoneNumberError:
            g.phone = ""
            g.insert(ignore_permissions=True)
        guest_link = g.name

    # ── Resolve Business Source Category ──────────────────────────────────────
    source_name = cfg["source_name"]
    bcom_source = (
        frappe.db.get_value("Business Source Category", source_name, "name")
        or frappe.db.get_value(
            "Business Source Category", {"source_name": source_name}, "name"
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
        "email_address":             email,
        "check_in_date":             check_in,
        "check_out_date":            check_out,
        "adults":                    adults,
        "children":                  children,
        "status":                    "confirmed",
        ref_field:                   uid,
        "business_source_category":  bcom_source or "",
        "guarantee_type":            "No Guarantee",
        "special_requests":          desc_data.get("special_requests", ""),
        "color":                     cfg["color"],
    })
    res.flags.from_ota_sync = True  # bypass past-date validation in reservation.py
    res.insert(ignore_permissions=True)
    frappe.db.commit()
    return True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sanitize_phone(phone):
    """Strip characters Frappe's validator rejects. Returns empty string if unusable."""
    if not phone:
        return ""
    import re
    cleaned = re.sub(r"[\s\-().]+", "", phone)
    if re.fullmatch(r"\+?\d+", cleaned):
        return cleaned
    return ""
