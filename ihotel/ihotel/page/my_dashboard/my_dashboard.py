import frappe
from frappe.utils import nowdate, flt, getdate


@frappe.whitelist()
def get_dashboard_data(selected_date=None):
    """Aggregate all dashboard metrics in a single call.

    selected_date (YYYY-MM-DD): the date the user selected on the dashboard.
    Defaults to today. For past dates, occupancy/revenue/ADR/RevPAR are pulled
    from the Night Audit for that date when one exists.
    """
    today = nowdate()
    sel_date = getdate(selected_date) if selected_date else getdate(today)
    sel_date_str = sel_date.strftime("%Y-%m-%d")
    is_today = sel_date_str == today

    # Hotel settings
    settings = frappe.get_single("iHotel Settings")
    hotel_name = settings.hotel_name or "iHotel"
    total_rooms = frappe.db.count("Room") or 0

    # Room status breakdown — operational, always current
    room_counts = frappe.db.sql(
        "SELECT status, COUNT(name) as count FROM `tabRoom` GROUP BY status",
        as_dict=True,
    )
    room_status = {
        "Available": 0, "Occupied": 0,
        "Vacant Dirty": 0, "Occupied Dirty": 0,
        "Out of Order": 0, "Out of Service": 0, "DND": 0,
    }
    for r in room_counts:
        if r.status in room_status:
            room_status[r.status] = r.count

    available_rooms = room_status["Available"]
    # DND rooms are sold rooms with the guest in-house — count toward occupancy.
    occupied_rooms  = room_status["Occupied"] + room_status["DND"]

    # Try Night Audit for selected date
    audit = frappe.db.get_value(
        "Night Audit",
        {"audit_date": sel_date_str},
        ["total_rooms", "occupied_rooms", "occupancy_rate",
         "total_revenue", "adr", "revpar"],
        as_dict=True,
    )

    if audit:
        # Use historical snapshot for analytics on the selected date
        total_rooms_for_date = audit.total_rooms or total_rooms
        occupied_for_date    = flt(audit.occupied_rooms)
        occupancy_rate       = flt(audit.occupancy_rate)
        todays_revenue       = flt(audit.total_revenue)
        adr                  = flt(audit.adr)
        revpar               = flt(audit.revpar)
        in_house_count       = int(occupied_for_date)
    elif is_today:
        # Live calc for today
        total_rooms_for_date = total_rooms
        occupied_for_date    = occupied_rooms
        occupancy_rate       = round((occupied_rooms / total_rooms) * 100, 1) if total_rooms else 0
        in_house_count = frappe.db.count(
            "Checked In",
            filters={"status": "Checked In", "docstatus": 1},
        )
        rev_result = frappe.db.sql(
            """
            SELECT IFNULL(SUM(room_rate), 0) as revenue
            FROM `tabChecked In`
            WHERE status = 'Checked In' AND docstatus = 1
            """,
            as_dict=True,
        )
        todays_revenue = flt(rev_result[0].revenue) if rev_result else 0
        adr    = round(todays_revenue / occupied_rooms, 2) if occupied_rooms else 0
        revpar = round(todays_revenue / total_rooms,  2) if total_rooms  else 0
    else:
        # Past date with no Night Audit — show zeros
        total_rooms_for_date = total_rooms
        occupied_for_date    = 0
        occupancy_rate       = 0
        todays_revenue       = 0
        adr                  = 0
        revpar               = 0
        in_house_count       = 0

    # Arrivals on selected date — expected check-ins on sel_date
    arrivals_today = frappe.db.count(
        "Checked In",
        filters={
            "expected_check_in": ["between", [f"{sel_date_str} 00:00:00", f"{sel_date_str} 23:59:59"]],
            "status": ["in", ["Reserved", "Checked In"]],
            "docstatus": ["!=", 2],
        },
    )

    # Departures on selected date — expected check-outs on sel_date
    departures_today = frappe.db.count(
        "Checked In",
        filters={
            "expected_check_out": ["between", [f"{sel_date_str} 00:00:00", f"{sel_date_str} 23:59:59"]],
            "status": ["in", ["Checked In", "Checked Out"]],
            "docstatus": ["!=", 2],
        },
    )

    # Active stays (Reserved + Checked In) — operational, always current
    active_stays = frappe.get_all(
        "Checked In",
        filters={"status": ["in", ["Reserved", "Checked In"]], "docstatus": 1},
        fields=["name", "guest", "room", "room_type", "status",
                "expected_check_in", "expected_check_out", "nights", "room_rate"],
        order_by="expected_check_in asc",
        limit_page_length=15,
    )

    # Housekeeping summary
    hk_counts = frappe.db.sql(
        "SELECT status, COUNT(name) as count FROM `tabHousekeeping Task` GROUP BY status",
        as_dict=True,
    )
    housekeeping = {"Pending": 0, "In Progress": 0, "Completed": 0}
    for h in hk_counts:
        if h.status in housekeeping:
            housekeeping[h.status] = h.count

    # Maintenance summary
    mt_counts = frappe.db.sql(
        "SELECT status, COUNT(name) as count FROM `tabMaintenance Request` GROUP BY status",
        as_dict=True,
    )
    maintenance = {"Open": 0, "In Progress": 0, "Resolved": 0, "Closed": 0}
    for m in mt_counts:
        if m.status in maintenance:
            maintenance[m.status] = m.count

    critical_maintenance = frappe.db.count(
        "Maintenance Request",
        filters={"priority": "Critical", "status": ["not in", ["Resolved", "Closed"]]},
    )

    # Recent night audits
    recent_audits = frappe.get_all(
        "Night Audit",
        fields=["name", "audit_date", "occupancy_rate", "total_revenue",
                "occupied_rooms", "total_rooms", "adr", "revpar"],
        order_by="audit_date desc",
        limit_page_length=5,
    )

    return {
        "hotel_name":       hotel_name,
        "selected_date":    sel_date_str,
        "is_today":         is_today,
        "has_audit":        bool(audit),
        "total_rooms":      total_rooms_for_date,
        "room_status":      room_status,
        "occupancy_rate":   occupancy_rate,
        "occupied_rooms":   int(occupied_for_date),
        "available_rooms":  available_rooms,
        "in_house_count":   in_house_count,
        "todays_revenue":   todays_revenue,
        "adr":              adr,
        "revpar":           revpar,
        "arrivals_today":   arrivals_today,
        "departures_today": departures_today,
        "active_stays":     active_stays,
        "housekeeping":     housekeeping,
        "maintenance":      maintenance,
        "critical_maintenance": critical_maintenance,
        "recent_audits":    recent_audits,
    }
