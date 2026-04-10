(() => {
	const BANNER_ID = "ihotel-notification-banner";
	let checkInFlight = false;

	function getBanner() {
		return document.getElementById(BANNER_ID);
	}

	function hideBanner() {
		const banner = getBanner();
		if (banner) banner.remove();
	}

	function clickBySelectors(selectors) {
		for (const selector of selectors) {
			const el = document.querySelector(selector);
			if (el) {
				el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
				el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
				el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
				return true;
			}
		}
		return false;
	}

	function openNotificationsPanel() {
		const deferOpen = (fn) => {
			setTimeout(fn, 0);
			return true;
		};

		// Primary path for Desk sidebar notifications modal/panel.
		if (frappe.app?.sidebar?.wrapper) {
			return deferOpen(() => {
				const sidebar = frappe.app.sidebar;
				if (typeof sidebar.open === "function") {
					sidebar.open();
				}
				const $dropdown = sidebar.wrapper.find(".dropdown-notifications");
				if ($dropdown.length) {
					$dropdown.removeClass("hidden");
					return;
				}
				const $sidebarButton = sidebar.wrapper.find(".sidebar-notification");
				if ($sidebarButton.length) {
					$sidebarButton.trigger("click");
				}
			});
		}

		// Try framework-level API first if available.
		if (frappe.ui?.toolbar?.show_notifications && typeof frappe.ui.toolbar.show_notifications === "function") {
			frappe.ui.toolbar.show_notifications();
			return true;
		}
		if (frappe.ui?.toolbar?.toggle_notifications && typeof frappe.ui.toolbar.toggle_notifications === "function") {
			frappe.ui.toolbar.toggle_notifications();
			return true;
		}
		if (frappe.ui?.notifications?.open && typeof frappe.ui.notifications.open === "function") {
			frappe.ui.notifications.open();
			return true;
		}

		// Fallbacks for common Desk/navbar/sidebar notification triggers.
		const opened = clickBySelectors([
			".dropdown-notifications .dropdown-toggle",
			".dropdown-notifications .notifications-icon",
			".navbar .notifications-icon",
			".notification-icon",
			".navbar .dropdown-notifications > a",
			".standard-sidebar .item-anchor[title='Notifications']",
			".standard-sidebar .item-anchor[data-title='Notifications']",
			".standard-sidebar .standard-sidebar-item[title='Notifications']",
			".standard-sidebar .standard-sidebar-item[data-label='Notifications']",
			".layout-side-section [title='Notifications']",
			".layout-side-section [data-label='Notifications']",
			"[aria-label='Notifications']",
			"[data-original-title='Notifications']",
			"[title='Notifications']",
			"a[href*='notifications']",
		]);
		if (opened) return true;

		// Fallback via Bootstrap/jQuery dropdown API (used in some Desk versions).
		if (window.jQuery) {
			const $toggle = window.jQuery(".dropdown-notifications .dropdown-toggle, .navbar .dropdown-notifications > a").first();
			if ($toggle.length) {
				if (typeof $toggle.dropdown === "function") $toggle.dropdown("toggle");
				else $toggle.trigger("click");
				return true;
			}
		}

		const notificationLabel = __("Notifications");
		const clickableNodes = Array.from(document.querySelectorAll("a, button, [role='button'], .standard-sidebar-item, .item-anchor"));
		const notificationsNode = clickableNodes.find((node) => node.textContent?.trim() === notificationLabel || node.textContent?.trim() === "Notifications");
		if (notificationsNode) {
			notificationsNode.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
			notificationsNode.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
			notificationsNode.dispatchEvent(new MouseEvent("click", { bubbles: true }));
			const href = notificationsNode.getAttribute?.("href");
			if (href && frappe.set_route) {
				const cleaned = href.replace(/^#/, "");
				if (cleaned) frappe.set_route(cleaned);
			}
			return true;
		}

		// Never fail silently: route to Notification Log list as a last fallback.
		if (frappe.set_route) {
			frappe.set_route("List", "Notification Log");
			return true;
		}

		return false;
	}

	function showBanner() {
		if (getBanner()) return;

		const banner = document.createElement("div");
		banner.id = BANNER_ID;
		banner.style.cssText = [
			"position: fixed",
			"top: 56px",
			"left: 50%",
			"transform: translateX(-50%)",
			"z-index: 1040",
			"background: #0b5fff",
			"color: #fff",
			"padding: 10px 14px",
			"border-radius: 10px",
			"box-shadow: 0 8px 24px rgba(0,0,0,0.2)",
			"font-size: 13px",
			"display: flex",
			"gap: 12px",
			"align-items: center",
			"max-width: min(92vw, 740px)",
		].join(";");

		const text = document.createElement("div");
		const messageLink = document.createElement("a");
		messageLink.href = "#";
		messageLink.textContent = __("You have new notifications");
		messageLink.style.cssText = "color: #fff; text-decoration: underline; font-weight: 600; cursor: pointer;";
		messageLink.onclick = (event) => {
			event.preventDefault();
			event.stopPropagation();
			event.stopImmediatePropagation();
			const opened = openNotificationsPanel();
			if (!opened) {
				frappe.show_alert({
					message: __("Unable to open Notifications from this view."),
					indicator: "orange",
				});
			}
		};
		text.appendChild(messageLink);

		const closeBtn = document.createElement("button");
		closeBtn.textContent = __("Dismiss");
		closeBtn.style.cssText =
			"border: 0; background: rgba(255,255,255,0.16); color: #fff; border-radius: 8px; padding: 6px 10px; cursor: pointer;";
		closeBtn.onclick = hideBanner;

		banner.appendChild(text);
		banner.appendChild(closeBtn);
		document.body.appendChild(banner);
	}

	function checkUnreadNotifications() {
		if (!frappe.session || frappe.session.user === "Guest" || checkInFlight) return;
		checkInFlight = true;

		frappe
			.xcall("frappe.desk.doctype.notification_log.notification_log.get_notification_logs", { limit: 20 })
			.then((r) => {
				const logs = (r && r.notification_logs) || [];
				const hasUnread = logs.some((d) => cint(d.read) === 0);
				if (hasUnread) showBanner();
				else hideBanner();
			})
			.finally(() => {
				checkInFlight = false;
			});
	}

	$(document).on("app_ready", () => {
		checkUnreadNotifications();
		setInterval(checkUnreadNotifications, 30000);
	});

	// Trigger immediate re-check whenever a new notification is pushed.
	frappe.realtime.on("notification", checkUnreadNotifications);
	frappe.realtime.on("ihotel_new_notification", checkUnreadNotifications);
})();
