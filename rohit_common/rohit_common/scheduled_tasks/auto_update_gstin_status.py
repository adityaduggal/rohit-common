#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
import time
from datetime import date
from frappe.utils import flt, getdate
from frappe.utils.background_jobs import enqueue
from ..validations.address import validate_gstin_from_portal


def enqueue_gstin_update():
    enqueue(execute, queue="long", timeout=7200)


def execute():
    st_time = time.time()
    validate = 0
    auto_days = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "auto_validate_gstin_after"))
    query = """SELECT name, validated_gstin, disabled,
        IFNULL(gst_validation_date, '1900-01-01') as gst_validation_date, gstin, gst_status
    FROM `tabAddress`
    WHERE gstin IS NOT NULL AND gstin != "NA" AND disabled=0 AND country = 'India'
    AND (validated_gstin IS NULL OR DATE_ADD(IFNULL(gst_validation_date, '1900-01-01'), INTERVAL %(auto_days)s DAY) < CURDATE())
    ORDER BY gstin, name"""

    add_list = frappe.db.sql(query, {"auto_days": auto_days}, as_dict=1)

    for add in add_list:
        print(f"Checking Address with GSTIN {add.gstin} with Validation Date {add.gst_validation_date}")
        changes_made = 0
        if add.gst_validation_date:
            if add.validated_gstin:
                days_since_validation = (date.today() - getdate(add.gst_validation_date)).days
            else:
                days_since_validation = (date.today() - getdate('1900-01-01')).days
            if days_since_validation > auto_days:
                # Now Validate the GSTIN
                add_doc = frappe.get_doc("Address", add.name)
                validate_gstin_from_portal(add_doc, auto_days=auto_days)
                changes_made = 1
                validate += 1
        else:
            changes_made = 1
            add_doc = frappe.get_doc("Address", add.name)
            validate_gstin_from_portal(add_doc, auto_days=auto_days)
            validate += 1
        if changes_made == 1:
            try:
                add_doc.flags.ignore_mandatory = True
                add_doc.save()
                print(f"{add_doc.name} Saved")
            except Exception as e:
                print(f"{e}")
        if validate % 50 == 0 and validate > 0:
            print(f"Committing Changes after {validate} Changes. Time Elapsed = {int(time.time() - st_time)} seconds")
            time.sleep(2)
            frappe.db.commit()
    print(f"Total GSTIN validated from GSTIN Website {validate}")
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds")
