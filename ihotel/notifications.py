# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import fmt_money


def _hotel_name():
	try:
		return frappe.get_single("iHotel Settings").hotel_name or "iHotel"
	except Exception:
		return "iHotel"


def _email_wrapper(hotel_name, content):
	"""Wrap content in a clean, professional hotel email layout."""
	return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1);">

      <!-- Header -->
      <tr>
        <td style="background:#1e3a5f;padding:24px 32px;">
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:600;letter-spacing:.5px;">
            {hotel_name}
          </h1>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="padding:32px;">
          {content}
        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="background:#f8f9fa;padding:16px 32px;border-top:1px solid #e9ecef;">
          <p style="margin:0;font-size:12px;color:#6c757d;text-align:center;">
            This is an automated message from {hotel_name}. Please do not reply directly to this email.
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def _info_row(label, value):
	return f"""
<tr>
  <td style="padding:8px 0;border-bottom:1px solid #f0f0f0;color:#6c757d;font-size:14px;width:160px;">{label}</td>
  <td style="padding:8px 0;border-bottom:1px solid #f0f0f0;color:#212529;font-size:14px;font-weight:500;">{value}</td>
</tr>"""


def on_hotel_stay_update(doc, method):
	"""Send a checkout receipt email when a guest checks out."""
	if doc.status != "Checked Out" or not doc.guest:
		return

	# Respect email toggle
	try:
		settings = frappe.get_single("iHotel Settings")
		if not settings.get("send_checkout_receipt"):
			return
	except Exception:
		pass

	guest = frappe.get_cached_doc("Guest", doc.guest)
	if not guest.email:
		return

	hotel = _hotel_name()
	currency = frappe.get_single("iHotel Settings").get("currency") or \
		frappe.boot.get("sysdefaults", {}).get("currency") or ""

	total_str = fmt_money(doc.total_amount or 0, currency=currency)
	checkin_str  = str(doc.actual_check_in  or doc.expected_check_in  or "")
	checkout_str = str(doc.actual_check_out or doc.expected_check_out or "")

	content = f"""
<p style="margin:0 0 20px;font-size:16px;color:#212529;">
  Dear <strong>{guest.guest_name}</strong>,
</p>
<p style="margin:0 0 24px;font-size:14px;color:#495057;line-height:1.6;">
  Thank you for staying with us. We hope you had a wonderful experience and look
  forward to welcoming you again soon.
</p>

<h3 style="margin:0 0 12px;font-size:15px;color:#1e3a5f;">Stay Summary</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
  {_info_row("Booking Reference", doc.name)}
  {_info_row("Room", doc.room or "-")}
  {_info_row("Check-in", checkin_str)}
  {_info_row("Check-out", checkout_str)}
  {_info_row("Nights", str(doc.nights or "-"))}
  {_info_row("Room Rate / Night", fmt_money(doc.room_rate or 0, currency=currency))}
  {_info_row("Total Amount", total_str)}
</table>

<p style="margin:28px 0 0;font-size:14px;color:#495057;line-height:1.6;">
  If you have any questions about your stay or this receipt, please don't hesitate to
  contact us.
</p>
<p style="margin:8px 0 0;font-size:14px;color:#495057;">
  Warm regards,<br>
  <strong>The {hotel} Team</strong>
</p>"""

	try:
		frappe.sendmail(
			recipients=[guest.email],
			subject=_("Thank you for staying — {0}").format(hotel),
			message=_email_wrapper(hotel, content),
			reference_doctype="Checked In",
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(f"Error sending checkout email for {doc.name}")


def _fmt_date(d):
	"""Format a date as DD-MMM-YYYY (e.g. 20-FEB-2026)."""
	if not d:
		return "-"
	try:
		from datetime import date as _date
		import datetime
		if isinstance(d, str):
			d = datetime.datetime.strptime(d, "%Y-%m-%d").date()
		return d.strftime("%d-%b-%Y").upper()
	except Exception:
		return str(d)


def _fmt_time(t):
	"""Format a time value as HH:MM."""
	if not t:
		return "-"
	try:
		s = str(t)
		return s[:5]
	except Exception:
		return str(t)


def _bullet_list(text):
	"""Convert newline-separated text into HTML bullet points."""
	if not text:
		return ""
	lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
	if not lines:
		return ""
	items = "".join(f"<li style='margin:4px 0;'>{l}</li>" for l in lines)
	return f"<ul style='margin:8px 0 0 0;padding-left:20px;'>{items}</ul>"


def _policy_block(label, text):
	"""Render a named policy paragraph; returns empty string if no text."""
	if not text or not text.strip():
		return ""
	return f"""
<p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#1e3a5f;">{label}</p>
<p style="margin:0 0 12px;font-size:13px;color:#495057;line-height:1.5;">{text.strip()}</p>"""


def on_reservation_update(doc, method):
	"""Send a professional reservation confirmation letter when a reservation is confirmed."""
	# Only send for confirmed status (covers 'confirmed' string from Reservation)
	if doc.status not in ("confirmed", "Confirmed"):
		return
	if not doc.email_address:
		return

	# Duplicate guard — don't resend if already sent
	if frappe.db.get_value("Reservation", doc.name, "confirmation_email_sent"):
		return

	# Respect email toggle
	try:
		settings = frappe.get_single("iHotel Settings")
		if not settings.get("send_reservation_confirmation"):
			return
	except Exception:
		settings = frappe._dict()

	hotel = settings.hotel_name or "iHotel"
	currency = settings.get("currency") or ""

	# ── Guest details ────────────────────────────────────────────────────────
	guest_name   = doc.full_name or "Guest"
	pax_str      = f"{doc.adults or 1} Adult(s)"
	if doc.children:
		pax_str += f" / {doc.children} Child(ren)"

	# ── Rate type label ──────────────────────────────────────────────────────
	rate_type_label = doc.rate_type or ""
	if doc.rate_type:
		try:
			rt = frappe.get_doc("Rate Type", doc.rate_type)
			rate_type_label = rt.rate_type_name or doc.rate_type
		except Exception:
			pass

	rate_str = fmt_money(doc.rent or 0, currency=currency)
	if rate_type_label:
		rate_str += f" per night ({rate_type_label})"
	else:
		rate_str += " per night"

	# ── Payment description ──────────────────────────────────────────────────
	payment_str = doc.payment_method or "-"
	if doc.credit_card_type:
		payment_str = doc.credit_card_type
		if doc.credit_card_last4:
			payment_str += f" ending {doc.credit_card_last4}"

	# ── Arrival time ─────────────────────────────────────────────────────────
	arrival_time = _fmt_time(doc.eta or doc.check_in_time)

	# ── Settings-driven content ──────────────────────────────────────────────
	default_checkin_time  = _fmt_time(settings.get("default_check_in_time"))
	default_checkout_time = _fmt_time(settings.get("default_check_out_time"))
	included_services     = settings.get("included_services") or ""
	late_checkout_policy  = settings.get("late_checkout_policy") or ""
	airport_policy        = settings.get("airport_transfer_policy") or ""
	booking_guarantee     = settings.get("booking_guarantee_policy") or ""
	cancellation_policy   = settings.get("cancellation_policy") or ""
	data_privacy          = settings.get("data_privacy_notice") or ""
	signatory_name        = settings.get("hotel_signatory_name") or f"The {hotel} Team"
	signatory_title       = settings.get("hotel_signatory_title") or ""

	# ── Room type + PAX display ──────────────────────────────────────────────
	room_type_str = doc.room_type or "-"
	if doc.no_of_rooms and doc.no_of_rooms > 1:
		room_type_str = f"{doc.no_of_rooms}-{room_type_str}"
	room_type_pax = f"{room_type_str} / {pax_str}"

	# ── Check-in/out policy block ────────────────────────────────────────────
	checkinout_html = f"""
<p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#1e3a5f;">Check-In / Check-Out</p>
<p style="margin:0 0 4px;font-size:13px;color:#495057;">
  Standard Check-In: <strong>{default_checkin_time}</strong> &nbsp;|&nbsp;
  Standard Check-Out: <strong>{default_checkout_time}</strong>
</p>"""
	if late_checkout_policy:
		checkinout_html += f"""
<p style="margin:0 0 12px;font-size:13px;color:#495057;line-height:1.5;">
  <em>Late Check-Out:</em> {late_checkout_policy.strip()}
</p>"""
	else:
		checkinout_html += "<br>"

	# ── Included services bullets ────────────────────────────────────────────
	services_html = ""
	if included_services:
		services_html = f"""
<h3 style="margin:20px 0 6px;font-size:14px;color:#1e3a5f;border-bottom:1px solid #dee2e6;padding-bottom:4px;">
  Included Services &amp; Facilities
</h3>
{_bullet_list(included_services)}"""

	# ── Policies block ───────────────────────────────────────────────────────
	policies_html = ""
	policy_parts = (
		_policy_block("Cancellation Policy", cancellation_policy) +
		_policy_block("Airport Transfer", airport_policy) +
		_policy_block("Booking Guarantee", booking_guarantee)
	)
	if policy_parts.strip():
		policies_html = f"""
<h3 style="margin:20px 0 8px;font-size:14px;color:#1e3a5f;border-bottom:1px solid #dee2e6;padding-bottom:4px;">
  Policies
</h3>
{policy_parts}"""

	# ── Data privacy ─────────────────────────────────────────────────────────
	privacy_html = ""
	if data_privacy:
		privacy_html = f"""
<p style="margin:20px 0 0;font-size:11px;color:#6c757d;line-height:1.5;border-top:1px solid #e9ecef;padding-top:12px;">
  {data_privacy.strip()}
</p>"""

	# ── Signatory block ──────────────────────────────────────────────────────
	signatory_html = f"""
<p style="margin:24px 0 0;font-size:14px;color:#212529;">
  Best Regards,<br>
  <strong>{signatory_name}</strong>
  {"<br><em style='font-size:12px;color:#6c757d;'>" + signatory_title + "</em>" if signatory_title else ""}
</p>"""

	# ── Build full letter ────────────────────────────────────────────────────
	content = f"""
<p style="margin:0 0 6px;font-size:13px;color:#6c757d;">Date: {_fmt_date(frappe.utils.nowdate())}</p>

<p style="margin:0 0 20px;font-size:16px;color:#212529;">
  Dear <strong>{guest_name}</strong>,
</p>

<p style="margin:0 0 20px;font-size:14px;color:#495057;line-height:1.6;">
  Thank you for choosing <strong>{hotel}</strong>. Please print or save this letter
  to present upon check-in.
</p>

<h3 style="margin:0 0 10px;font-size:14px;color:#1e3a5f;border-bottom:1px solid #dee2e6;padding-bottom:4px;">
  Reservation Details
</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:8px;">
  {_info_row("Confirmation No.", f"<strong>{doc.name}</strong>")}
  {_info_row("Guest Name", guest_name)}
  {_info_row("Source", doc.business_source_category or "-")}
  {_info_row("Arrival Date", _fmt_date(doc.check_in_date))}
  {_info_row("Departure Date", _fmt_date(doc.check_out_date))}
  {_info_row("Number of Nights", str(doc.days or "-"))}
  {_info_row("Room Type / PAX", room_type_pax)}
  {_info_row("Room Rate", rate_str)}
  {_info_row("Payment", payment_str)}
  {_info_row("Arrival Time", arrival_time if arrival_time != "-" else "Please advise")}
  {_info_row("Preferences", doc.special_requests or "Please advise with any preferences")}
</table>

{services_html}

<div style="margin-top:20px;">
  {checkinout_html}
</div>

{policies_html}

{privacy_html}

{signatory_html}"""

	try:
		frappe.sendmail(
			recipients=[doc.email_address],
			subject=_("Reservation Confirmation — {0} | {1}").format(hotel, doc.name),
			message=_email_wrapper(hotel, content),
			reference_doctype="Reservation",
			reference_name=doc.name,
		)
		# Mark as sent to prevent resend on subsequent saves
		frappe.db.set_value("Reservation", doc.name, "confirmation_email_sent", 1,
			update_modified=False)
	except Exception:
		frappe.log_error(f"Error sending confirmation email for {doc.name}")
