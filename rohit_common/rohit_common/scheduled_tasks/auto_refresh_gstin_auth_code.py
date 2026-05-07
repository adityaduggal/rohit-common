#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

import time
import frappe
from ..india_gst_api.gst_api import check_for_refresh_token
from frappe import logger

def execute():
    st_time = time.time()
    try:
        r_set = frappe.get_doc("Rohit GST Settings", "Rohit GST Settings")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Failed to load Rohit GST Settings")
        return

    for row in r_set.gst_registration_details:
        try:
            check_for_refresh_token(row=row, settings_doc=r_set)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"check_for_refresh_token failed for {row.gst_registration_number}")

    try:
        r_set.reload()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Failed to reload Rohit GST Settings after refresh")

    logger("gst_api").info(f"auto_refresh_gstin_auth_code completed in {int(time.time() - st_time)}s")
