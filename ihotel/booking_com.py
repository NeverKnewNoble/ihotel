# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt
"""Booking.com iCal sync — delegates to the generic OTA iCal engine."""

from ihotel.ical_sync import sync_platform


def sync_bookings():
    """Fetch the Booking.com iCal feed and sync all events into Reservations."""
    sync_platform("booking_com")
