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

    # ---- Room status breakdown ----
    # Frappe doesn't snapshot per-status room counts on Night Audit, so a
    # full breakdown is only meaningful for TODAY (live state). For other
    # dates we still provide aggregate Sold/Available/Blocked numbers via
    # the Night Audit (handled below); the per-status dict will be zeroed
    # so the UI hides the breakdown rows.
    room_status = {
        "Available": 0, "Occupied": 0,
        "Vacant Dirty": 0, "Occupied Dirty": 0,
        "Out of Order": 0, "Out of Service": 0, "DND": 0,
    }
    if is_today:
        room_counts = frappe.db.sql(
            "SELECT status, COUNT(name) as count FROM `tabRoom` GROUP BY status",
            as_dict=True,
        )
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

    # ---------------- Housekeeping summary ----------------
    # Scoped to the selected date via Housekeeping Task.assigned_date.
    hk_status_rows = frappe.db.sql(
        """
        SELECT status, COUNT(name) AS count
        FROM `tabHousekeeping Task`
        WHERE assigned_date = %s
        GROUP BY status
        """,
        (sel_date_str,),
        as_dict=True,
    )
    hk_status = {"Pending": 0, "In Progress": 0, "Completed": 0}
    for h in hk_status_rows:
        if h.status in hk_status:
            hk_status[h.status] = h.count
    hk_total = sum(hk_status.values())

    hk_type_rows = frappe.db.sql(
        """
        SELECT task_type, COUNT(name) AS count
        FROM `tabHousekeeping Task`
        WHERE assigned_date = %s AND IFNULL(task_type, '') != ''
        GROUP BY task_type
        """,
        (sel_date_str,),
        as_dict=True,
    )
    hk_by_type = {row.task_type: row.count for row in hk_type_rows}

    housekeeping = {
        "total": hk_total,
        "status": hk_status,
        "by_type": hk_by_type,
        # All tasks counted here are by definition "due/scheduled for sel_date"
        "due_today": hk_total,
        # Backwards-compat: keep flat status keys at top level
        "Pending":     hk_status["Pending"],
        "In Progress": hk_status["In Progress"],
        "Completed":   hk_status["Completed"],
    }

    # ---------------- Maintenance summary -----------------
    # Scoped to the selected date via Maintenance Request.reported_date.
    mt_status_rows = frappe.db.sql(
        """
        SELECT status, COUNT(name) AS count
        FROM `tabMaintenance Request`
        WHERE reported_date = %s
        GROUP BY status
        """,
        (sel_date_str,),
        as_dict=True,
    )
    mt_status = {"Open": 0, "In Progress": 0, "Resolved": 0, "Closed": 0}
    for m in mt_status_rows:
        if m.status in mt_status:
            mt_status[m.status] = m.count
    mt_total = sum(mt_status.values())

    mt_cat_rows = frappe.db.sql(
        """
        SELECT category, COUNT(name) AS count
        FROM `tabMaintenance Request`
        WHERE reported_date = %s AND IFNULL(category, '') != ''
        GROUP BY category
        ORDER BY count DESC
        LIMIT 6
        """,
        (sel_date_str,),
        as_dict=True,
    )
    mt_by_category = [{"category": r.category, "count": r.count} for r in mt_cat_rows]

    mt_critical = frappe.db.count(
        "Maintenance Request",
        filters={"reported_date": sel_date_str, "priority": "Critical"},
    )
    mt_open_today = mt_status["Open"] + mt_status["In Progress"]

    maintenance = {
        "total": mt_total,
        "status": mt_status,
        "by_category": mt_by_category,
        "critical": mt_critical,
        "open_today": mt_open_today,
        # Backwards-compat
        "Open":        mt_status["Open"],
        "In Progress": mt_status["In Progress"],
        "Resolved":    mt_status["Resolved"],
        "Closed":      mt_status["Closed"],
    }

    critical_maintenance = mt_critical  # legacy alias

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
