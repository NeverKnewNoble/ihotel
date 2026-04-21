import frappe
from frappe.utils import nowdate, flt


@frappe.whitelist()
def get_dashboard_data():
    """Aggregate all dashboard metrics in a single call."""
    today = nowdate()

    # Hotel settings
    settings = frappe.get_single("iHotel Settings")
    hotel_name = settings.hotel_name or "iHotel"
    total_rooms = frappe.db.count("Room") or 0

    # Room status breakdown
    room_counts = frappe.db.sql(
        "SELECT status, COUNT(name) as count FROM `tabRoom` GROUP BY status",
        as_dict=True,
    )
    room_status = {
        "Available": 0, "Occupied": 0,
        "Vacant Dirty": 0, "Occupied Dirty": 0,
        "Out of Order": 0, "Out of Service": 0,
    }
    for r in room_counts:
        if r.status in room_status:
            room_status[r.status] = r.count

    available_rooms = room_status["Available"]
    occupied_rooms  = room_status["Occupied"]
    occupancy_rate  = round((occupied_rooms / total_rooms) * 100, 1) if total_rooms else 0

    # In-house count (guests currently checked in)
    in_house_count = frappe.db.count(
        "Checked In",
        filters={"status": "Checked In", "docstatus": 1},
    )

    # Today's revenue = sum of nightly room rates for in-house stays
    rev_result = frappe.db.sql(
        """
        SELECT IFNULL(SUM(room_rate), 0) as revenue
        FROM `tabChecked In`
        WHERE status = 'Checked In' AND docstatus = 1
        """,
        as_dict=True,
    )
    todays_revenue = flt(rev_result[0].revenue) if rev_result else 0

    # ADR = today's revenue / occupied rooms
    adr = round(todays_revenue / occupied_rooms, 2) if occupied_rooms else 0
    # RevPAR = today's revenue / total rooms
    revpar = round(todays_revenue / total_rooms, 2) if total_rooms else 0

    # Arrivals today — expected check-ins on today's date
    arrivals_today = frappe.db.count(
        "Checked In",
        filters={
            "expected_check_in": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
            "status": ["in", ["Reserved", "Checked In"]],
            "docstatus": ["!=", 2],
        },
    )

    # Departures today — expected check-outs on today's date
    departures_today = frappe.db.count(
        "Checked In",
        filters={
            "expected_check_out": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
            "status": ["in", ["Checked In", "Checked Out"]],
            "docstatus": ["!=", 2],
        },
    )

    # Active stays (Reserved + Checked In)
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
        "total_rooms":      total_rooms,
        "room_status":      room_status,
        "occupancy_rate":   occupancy_rate,
        "occupied_rooms":   occupied_rooms,
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
