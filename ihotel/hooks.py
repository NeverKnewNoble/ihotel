app_name = "ihotel"
app_title = "iHotel"
app_publisher = "Noble"
app_description = "hotel manangement app"
app_email = "nortexnoble@gmail.com"
app_license = "mit"

# Fixtures
# ------------------
fixtures = [
	{"doctype": "Business Source Type", "filters": [["module" , "in" , ("ihotel" )]]},
	{"doctype": "Business Channel Category", "filters": [["module" , "in" , ("ihotel" )]]},
	{"doctype": "Notification", "filters": [["name", "=", "Reservation Confirmation Letter"]]},
	{"doctype": "Workspace Sidebar", "filters": [["name", "=", "iHotel"]]},
]

# Apps
# ------------------

# required_apps = []
# add_to_apps_screen = ["iHotel"]


# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "ihotel",
# 		"logo": "/assets/ihotel/logo.png",
# 		"title": "iHotel",
# 		"route": "check/ihotel",
# 		# "has_permission": "ihotel.api.permission.has_app_permission"
# 	}
# ]

# app_include_icons = [
#     "ihotel/public/icons/my_custom_icons.svg"
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/ihotel/css/ihotel.css"
app_include_js = "/assets/ihotel/js/ihotel_notifications.js"

# include js, css files in header of web template
# web_include_css = "/assets/ihotel/css/ihotel.css"
# web_include_js = "/assets/ihotel/js/ihotel.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "ihotel/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# (trial_balance.js is loaded once via Page.load_assets from the page folder;
# do not also list it here or the script runs twice and `class TrialBalance` redeclares.)
# page_js = {"trial_balance": "ihotel/page/trial_balance/trial_balance.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
doctype_calendar_js = {
	"Reservation": "public/js/reservation_calendar.js",
	"Checked In":  "public/js/checked_in_calendar.js",
}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "ihotel/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "ihotel.utils.jinja_methods",
# 	"filters": "ihotel.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "ihotel.install.before_install"
# after_install = "ihotel.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "ihotel.uninstall.before_uninstall"
# after_uninstall = "ihotel.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ihotel.utils.before_app_install"
# after_app_install = "ihotel.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "ihotel.utils.before_app_uninstall"
# after_app_uninstall = "ihotel.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "ihotel.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Additional Document Events (see doc_events in Scheduled Tasks section above)

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"ihotel.tasks.late_checkout_alert",
	],
	"daily": [
		"ihotel.tasks.auto_no_show",
		"ihotel.tasks.auto_generate_housekeeping",
		"ihotel.tasks.send_birthday_notifications",
	],
	"cron": {
		"0 23 * * *": [
			"ihotel.tasks.night_audit_reminder",
		],
		"*/30 * * * *": [
			"ihotel.tasks.sync_booking_com",
			"ihotel.tasks.sync_expedia",
			"ihotel.tasks.sync_airbnb",
			"ihotel.tasks.sync_agoda",
			"ihotel.tasks.sync_trip_com",
			"ihotel.tasks.sync_tripadvisor",
		],
	},
}

# Document Events
doc_events = {
	"Checked In": {
		"on_update_after_submit": "ihotel.notifications.on_hotel_stay_update",
	},
	# Reservation confirmation is handled by the "Reservation Confirmation Letter" Notification fixture
}

# Desk boot: ERPNext detection for sidebar + iHotel Settings (Accounting tab)
boot_session = "ihotel.boot.extend_boot_session"

# Testing
# -------

# before_tests = "ihotel.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "ihotel.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "ihotel.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["ihotel.utils.before_request"]
# after_request = ["ihotel.utils.after_request"]

# Job Events
# ----------
# before_job = ["ihotel.utils.before_job"]
# after_job = ["ihotel.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"ihotel.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

