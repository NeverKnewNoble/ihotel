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


def on_reservation_update(doc, method):
	"""Send a booking confirmation when a reservation is confirmed."""
	if doc.status != "confirmed" or not doc.email_address:
		return

	# Respect email toggle
	try:
		settings = frappe.get_single("iHotel Settings")
		if not settings.get("send_reservation_confirmation"):
			return
	except Exception:
		pass

	hotel = _hotel_name()
	currency = frappe.get_single("iHotel Settings").get("currency") or \
		frappe.boot.get("sysdefaults", {}).get("currency") or ""

	guest_name = doc.full_name or "Guest"
	total_str  = fmt_money(doc.total_charges or 0, currency=currency)

	content = f"""
<p style="margin:0 0 20px;font-size:16px;color:#212529;">
  Dear <strong>{guest_name}</strong>,
</p>
<p style="margin:0 0 24px;font-size:14px;color:#495057;line-height:1.6;">
  Your reservation has been <strong style="color:#198754;">confirmed</strong>.
  We look forward to welcoming you to {hotel}.
</p>

<h3 style="margin:0 0 12px;font-size:15px;color:#1e3a5f;">Reservation Details</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
  {_info_row("Confirmation No.", doc.name)}
  {_info_row("Room Type", doc.room_type or "-")}
  {_info_row("Check-in", str(doc.check_in_date or "-"))}
  {_info_row("Check-out", str(doc.check_out_date or "-"))}
  {_info_row("Nights", str(doc.days or "-"))}
  {_info_row("Rate / Night", fmt_money(doc.rent or 0, currency=currency))}
  {_info_row("Total Charges", total_str)}
</table>

{"" if not doc.cancellation_number else f'<p style="margin:20px 0 0;font-size:13px;color:#6c757d;">Cancellation No: <strong>{doc.cancellation_number}</strong></p>'}

<p style="margin:28px 0 0;font-size:14px;color:#495057;line-height:1.6;">
  Should you need to make any changes or have questions about your booking,
  please contact us and quote your confirmation number.
</p>
<p style="margin:8px 0 0;font-size:14px;color:#495057;">
  Warm regards,<br>
  <strong>The {hotel} Team</strong>
</p>"""

	try:
		frappe.sendmail(
			recipients=[doc.email_address],
			subject=_("Reservation Confirmed — {0} ({1})").format(hotel, doc.name),
			message=_email_wrapper(hotel, content),
			reference_doctype="Reservation",
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(f"Error sending confirmation email for {doc.name}")
