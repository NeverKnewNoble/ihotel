# Copyright (c) 2026, Noble and contributors
# For license information, please see license.txt

import frappe


def _ihotel_effective_erpnext_installed():
	"""Respects iHotel Settings test selector; real app list used when mode is Auto."""
	try:
		mode = frappe.db.get_single_value("iHotel Settings", "erpnext_presence_test_mode") or "Auto"
	except Exception:
		mode = "Auto"

	real = "erpnext" in frappe.get_installed_apps()
	if mode == "Force: ERPXpand included":
		return True
	if mode == "Force: no ERPXpand":
		return False
	return real


def _ihotel_sidebar_remove_standalone_ledger(items, erpnext_installed):
	"""Drop the Hotel Account standalone ledger link when ERPXpand is effectively installed.

	The Trial Balance page is kept visible in both modes: it now queries the real
	ERPNext GL (tabGL Entry), so it is useful whether the client uses ERPXpand as
	their primary accounting system or exports the balance for an external system.
	"""
	if not erpnext_installed or not items:
		return items
	out = []
	for it in items:
		lt = it.get("link_type")
		lk = it.get("link_to")
		if lt == "DocType" and lk == "Hotel Account":
			continue
		out.append(it)
	return out


def extend_boot_session(bootinfo):
	"""Expose ERPNext presence for desk UI; trim iHotel sidebar when using ERPNext GL."""
	erp = _ihotel_effective_erpnext_installed()
	real = "erpnext" in frappe.get_installed_apps()
	bootinfo.ihotel_erpnext_installed = erp
	bootinfo.ihotel_erpnext_really_installed = real
	bootinfo.ihotel_standalone_hotel_ledger = not erp

	sidebars = getattr(bootinfo, "workspace_sidebar_item", None) or {}
	for _key, sidebar in sidebars.items():
		if (sidebar or {}).get("app") != "ihotel":
			continue
		sidebar["items"] = _ihotel_sidebar_remove_standalone_ledger(sidebar.get("items") or [], erp)
