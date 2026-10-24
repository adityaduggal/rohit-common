#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
import time
from frappe.utils import flt
from frappe.utils.background_jobs import enqueue
from ..india_gst_api.gst_public_api import search_gstin_whitebooks
from ..validations.address import validate_gstin_from_portal, is_gstin_validation_disabled

COMMIT_EVERY = 50


def enqueue_gstin_update():
    enqueue(execute, queue="long", timeout=7200)


def execute():
    if is_gstin_validation_disabled():
        print("GSTIN Validation is Disabled in Rohit Settings hence Skipping")
        return
    auto_days = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "auto_validate_gstin_after"))
    if auto_days <= 0:
        # flt(None) = 0 would match every Address every day and burn API quota
        print("Auto Validate GSTIN After is not set in Rohit Settings hence Skipping")
        return
    query = """SELECT name, gstin, IFNULL(gst_validation_date, '1900-01-01') as gst_validation_date
    FROM `tabAddress`
    WHERE gstin IS NOT NULL AND gstin != 'NA' AND disabled=0 AND country = 'India'
    AND (validated_gstin IS NULL OR DATE_ADD(IFNULL(gst_validation_date, '1900-01-01'), INTERVAL %(auto_days)s DAY) < CURDATE())
    ORDER BY gstin, name"""
    add_list = frappe.db.sql(query, {"auto_days": auto_days}, as_dict=1)
    update_addresses(add_list, auto_days)


def update_addresses(add_list, auto_days):
    """
    Validates and saves each Address from the GST portal. Each Address is its own unit:
    a failure rolls back only that Address (savepoint) and the loop continues. Addresses
    sharing a GSTIN reuse one portal response, so each GSTIN costs one API call per run.
    """
    st_time = time.time()
    portal_replies = {}
    saved, failed, since_commit = 0, 0, 0
    for add in add_list:
        print(f"Checking Address with GSTIN {add.gstin} with Validation Date {add.gst_validation_date}")
        frappe.db.savepoint("gstin_addr")
        try:
            if add.gstin not in portal_replies:
                portal_replies[add.gstin] = search_gstin_whitebooks(add.gstin)
            add_doc = frappe.get_doc("Address", add.name)
            validate_gstin_from_portal(add_doc, auto_days=auto_days, gstin_json=portal_replies[add.gstin])
            add_doc.flags.ignore_mandatory = True
            add_doc.save()
            saved += 1
            since_commit += 1
            print(f"{add_doc.name} Saved")
        except Exception:
            frappe.db.rollback(save_point="gstin_addr")
            failed += 1
            frappe.log_error(frappe.get_traceback(), f"GSTIN Auto Update Failed for {add.name}")
        if since_commit >= COMMIT_EVERY:
            print(f"Committing Changes after {saved} Changes. Time Elapsed = {int(time.time() - st_time)} seconds")
            frappe.db.commit()
            since_commit = 0
            time.sleep(2)
    frappe.db.commit()
    print(f"Total GSTIN validated from GSTIN Website {saved}, Failed {failed}")
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds")
    return saved, failed
