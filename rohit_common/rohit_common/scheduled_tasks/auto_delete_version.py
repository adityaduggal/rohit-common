# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the table TabVersion and delete from them old entries.
# Based on Reference Doctype mentioned in the Rohit Settings.

from __future__ import unicode_literals
import time
import frappe
from frappe.utils import flt
from frappe.utils.background_jobs import enqueue


def enqueue_deletion():
    enqueue(execute, queue="long", timeout=3600)


def execute():
    st_time = time.time()
    rset = frappe.get_single("Rohit Settings")
    max_days = int(flt(rset.max_days_to_keep_version)) or 30  # ensure int and default to 30
    dt_list = [row.document_type for row in rset.auto_delete_from_version]

    if dt_list:
        placeholders = ", ".join(["%s"] * len(dt_list))
        query = f"""
            SELECT name, creation, ref_doctype, docname
            FROM `tabVersion`
            WHERE ref_doctype NOT IN ({placeholders})
            AND creation <= (DATE_SUB(CURDATE(), INTERVAL {max_days} DAY))
        """
        un_regulated_version = frappe.db.sql(query, tuple(dt_list), as_dict=1)
    else:
        # If dt_list empty, simply skip the NOT IN clause
        query = f"""
            SELECT name, creation, ref_doctype, docname
            FROM `tabVersion`
            WHERE creation <= (DATE_SUB(CURDATE(), INTERVAL {max_days} DAY))
        """
        un_regulated_version = frappe.db.sql(query, as_dict=1)

    deleted_0 = 0
    deleted_1 = 0

    for d in un_regulated_version:
        print(f"Deleting Versions for All Un-Listed Doctypes older than {max_days} Days")
        deleted_0 += 1
        frappe.delete_doc("Version", d.name, for_reload=1)
        if deleted_0 % 2000 == 0:
            frappe.db.commit()
            print(f"Committing After {deleted_0} deletions. Time Elapsed {int(time.time() - st_time)} seconds")

    # Now process doctypes listed in settings
    for row in rset.auto_delete_from_version:
        max_days_row = int(flt(row.days_to_keep)) if flt(row.days_to_keep) > 0 else 1
        print(f"Deleting Versions for {row.document_type} older than {max_days_row} Days")

        query = f"""
            SELECT name, creation, ref_doctype, docname
            FROM `tabVersion`
            WHERE ref_doctype = %s
            AND creation <= (DATE_SUB(CURDATE(), INTERVAL {max_days_row} DAY))
        """
        reg_version = frappe.db.sql(query, (row.document_type,), as_dict=1)

        for d in reg_version:
            deleted_1 += 1
            frappe.delete_doc("Version", d.name, for_reload=1)
            if deleted_1 % 2000 == 0:
                frappe.db.commit()
                print(f"Committing After {deleted_1} deletions. Time Elapsed {int(time.time() - st_time)} seconds")

    tot_time = int(time.time() - st_time)
    print(f"Total Versions Deleted = {deleted_0 + deleted_1}")
    print(f"Total Time Taken = {tot_time} seconds")
