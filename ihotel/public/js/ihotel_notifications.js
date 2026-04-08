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
		text.textContent = __("You have new notifications. Please check the Notifications section in the sidebar.");

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
