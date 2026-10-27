#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
import frappe
from ..india_gst_api.gst_api import check_for_refresh_token


def execute():
    """
    Extends the WhiteBooks GST session of each GSTIN in Rohit GST Settings before it expires.
    Each GSTIN is its own unit: a failure rolls back only that row (savepoint) and writes an
    Error Log, and the other GSTINs are still refreshed.
    """
    r_set = frappe.get_single("Rohit GST Settings")
    for row in r_set.gst_registration_details:
        frappe.db.savepoint("gstin_token")
        try:
            check_for_refresh_token(row=row)
        except Exception:
            frappe.db.rollback(save_point="gstin_token")
            frappe.log_error(frappe.get_traceback(),
                             f"WhiteBooks GST Token Refresh Failed for {row.gst_registration_number}")
