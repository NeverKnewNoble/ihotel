# Copyright (c) 2025, Noble and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


# class Room(Document):
# 	pass


import frappe
from frappe.model.document import Document
from frappe import _

class Room(Document):
    """
    Room document representing a hotel room.
    Manages room status, availability, and maintenance information.
    """
    def validate(self):
        """
        Validate room information before saving.
        """
        self.validate_room_number()

    def validate_room_number(self):
        """
        Ensure room number is unique across all rooms.
        """
        if self.room_number and frappe.db.exists("Room", {
            "room_number": self.room_number, 
            "name": ["!=", self.name]
        }):
            frappe.throw(_("Room number {0} already exists").format(self.room_number))

    def before_save(self):
        """
        Update room status based on current active reservations.
        Status is automatically set to Occupied if there's an active stay.
        """
        if self.name:  # Only check for existing rooms
            current_stay = frappe.db.exists("Checked In", {
                "room": self.name,
                "status": ["in", ["Checked In", "Reserved"]],
                "docstatus": 1
            })

            if current_stay:
                # Room has an active reservation, mark as occupied
                if self.status not in ["Occupied", "Occupied Dirty", "Occupied Clean", "Out of Order"]:
                    self.status = "Occupied"
            elif self.status == "Occupied":
                # No active reservation but marked as occupied — reset to Vacant Dirty for housekeeping
                self.status = "Vacant Dirty"
