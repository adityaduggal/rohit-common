# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the table TabVersion and delete from them old entries.
# Based on Reference Doctype mentioned in the Rohit Settings.

from __future__ import unicode_literals
import time
import frappe
from frappe.utils import cint
from ...utils.background_doc_processing import enqueue_once

DEFAULT_DAYS_TO_KEEP = 30
VERSION_DELETE_BATCH = 5000


def enqueue_deletion():
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.auto_delete_version.execute",
                 queue="long", timeout=3600)


def execute():
    """
    Deletes Versions older than Max Days to Keep Version, except for the doctypes listed in
    Auto Delete from Version, which use their own Days to Keep.
    """
    rset = frappe.get_single("Rohit Settings")
    max_days = cint(rset.max_days_to_keep_version) or DEFAULT_DAYS_TO_KEEP
    delete_old_versions(max_days, get_listed_days(rset.auto_delete_from_version))


def get_listed_days(rows):
    """
    Returns {doctype: days to keep} from the Auto Delete from Version rows. Days to Keep is the
    age of the Versions to keep. A row without it is skipped, so its doctype keeps Versions for
    Max Days to Keep Version, not for 1 day.
    """
    listed_days = {}
    for row in rows:
        if not row.document_type:
            continue
        if cint(row.days_to_keep) < 1:
            print(f"Days to Keep not set for {row.document_type} hence using Max Days to Keep Version")
            continue
        listed_days[row.document_type] = cint(row.days_to_keep)
    return listed_days


def delete_old_versions(max_days, listed_days):
    """
    `listed_days` is {doctype: days to keep}. Versions of every other doctype are kept for
    `max_days`. Returns the number of Versions deleted.
    """
    st_time = time.time()
    print(f"Deleting Versions for All Un-Listed Doctypes older than {max_days} Days")
    deleted = _delete_versions(max_days, exclude=list(listed_days))
    for doctype, days in listed_days.items():
        print(f"Deleting Versions for {doctype} older than {days} Days")
        deleted += _delete_versions(days, ref_doctype=doctype)
    print(f"Total Versions Deleted = {deleted}")
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds")
    return deleted


def _delete_versions(days, ref_doctype=None, exclude=None):
    """
    Deletes the matching Versions in batches of VERSION_DELETE_BATCH and commits after each
    batch, so one run does not hold a lock on the whole table. Returns the number deleted.
    """
    conditions = ["creation <= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY)"]
    values = {"days": days}
    if ref_doctype:
        conditions.append("ref_doctype = %(ref_doctype)s")
        values["ref_doctype"] = ref_doctype
    if exclude:
        conditions.append("(ref_doctype IS NULL OR ref_doctype NOT IN %(exclude)s)")
        values["exclude"] = tuple(exclude)
    query = "DELETE FROM `tabVersion` WHERE {conditions} LIMIT {limit}".format(
        conditions=" AND ".join(conditions), limit=VERSION_DELETE_BATCH)

    deleted = 0
    while True:
        frappe.db.sql(query, values)
        batch_count = cint(frappe.db._cursor.rowcount)
        frappe.db.commit()
        deleted += batch_count
        if batch_count < VERSION_DELETE_BATCH:
            return deleted
