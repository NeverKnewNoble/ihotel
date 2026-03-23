# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


# class HousekeepingTask(Document):
# 	pass


import frappe
from frappe.model.document import Document
from frappe import _

class HousekeepingTask(Document):
    """
    Housekeeping Task document for managing room cleaning and maintenance tasks.
    Automatically updates room status when tasks are completed.
    """
    def validate(self):
        """
        Validate and update task status based on dates.
        """
        self.update_task_status()

    def update_task_status(self):
        """
        Auto-set status on new tasks; validate required fields when completing.
        Only auto-sets when status is blank — never overwrites a manual status.
        """
        if not self.status:
            if self.cleaned_date or self.actual_end_time:
                self.status = "Completed"
            elif self.assigned_date or self.actual_start_time:
                self.status = "In Progress"
            else:
                self.status = "Pending"

        if self.status == "Completed" and not (self.cleaned_date or self.actual_end_time):
            frappe.throw(_("Please set the Completion Date/Time before marking this task as Completed."))

    def on_update(self):
        """
        Update room status to Available when housekeeping task is completed.
        """
        if self.status == "Completed" and self.room:
            try:
                room = frappe.get_doc("Room", self.room)
                # Only update if room is not occupied by a guest
                if room.status != "Occupied":
                    room.status = "Available"
                    room.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Error updating room status from housekeeping task: {str(e)}")
                # Don't throw error to allow task completion
