# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the table TabVersion and delete from them old entries.
# Based on Reference Doctype mentioned in the Rohit Settings.

from __future__ import unicode_literals
import time
import frappe
from frappe.utils import flt
from ...utils.background_doc_processing import enqueue_once


def enqueue_deletion():
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.auto_delete_version.execute",
                 queue="long", timeout=3600)


def execute():
    st_time = time.time()
    rset = frappe.get_single("Rohit Settings")
    max_days = flt(rset.max_days_to_keep_version)
    dt_list = []
    for row in rset.auto_delete_from_version:
        dt_list.append(row.document_type)
    if max_days == 0:
        max_days = 30

    # First delete all items except for the ones in table which are above the max days
    query = """SELECT name, creation, ref_doctype, docname FROM `tabVersion` WHERE ref_doctype NOT IN %s
    AND creation <= (DATE_SUB(CURDATE(), INTERVAL %s DAY))""" % (tuple(dt_list), max_days)
    un_regulated_version = frappe.db.sql(query, as_dict=1)
    deleted_0 = 0
    deleted_1 = 0
    for d in un_regulated_version:
        print(f"Deleting Versions for All Un-Listed Doctypes older than {max_days} Days")
        deleted_0 += 1
        frappe.delete_doc("Version", d.name, for_reload=1)
        if deleted_0 % 2000 == 0 and deleted_0 > 0:
            frappe.db.commit()
            print(f"Committing After {deleted_0} deletions. Time Elapsed {int(time.time() - st_time)} seconds")
    for row in rset.auto_delete_from_version:
        # dt_conds = ""
        # if row.doctype_conditions:
        #    dt_conds = " AND %s" % row.doctype_conditions

        max_days = flt(row.days_to_keep) if flt(row.days_to_keep) > 0 else 1
        print(f"Deleting Versions for {row.document_type} older than {max_days} Days")
        query = """SELECT name, creation, ref_doctype, docname FROM `tabVersion` WHERE ref_doctype = '%s'
        AND creation <= (DATE_SUB(CURDATE(), INTERVAL %s DAY))""" % (row.document_type, max_days)
        reg_version = frappe.db.sql(query, as_dict=1)
        for d in reg_version:
            deleted_1 += 1
            frappe.delete_doc("Version", d.name, for_reload=1)
            if deleted_1  % 2000 == 0 and deleted_1 > 0:
                frappe.db.commit()
                print(f"Committing After {deleted_1} deletions. Time Elapsed {int(time.time() - st_time)} seconds")
    tot_time = int(time.time() - st_time)
    print(f"Total Versions Deleted = {deleted_0 + deleted_1}")
    print(f"Total Time Taken = {tot_time} seconds")
