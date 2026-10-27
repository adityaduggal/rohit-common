# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# Weekly database housekeeping: trims old Stock Ledger FIFO queues and clears log tables
# that nothing else cleans. The one-time patch patches/v13/shrink_database.py also runs it.

from __future__ import unicode_literals
import time
import frappe
from frappe.utils import cint, getdate
from ...utils.background_doc_processing import enqueue_once
from .auto_delete_version import _delete_versions

BATCH_SIZE = 5000
NOISE_VERSION_DAYS = 30
NOISE_VERSION_DOCTYPES = ("Route History", "Activity Log", "Email Queue", "GSTR2A RIGPL")
ACCESS_LOG_DAYS = 365
# Tables of DocTypes that no longer exist
ORPHAN_TABLE_DOCTYPES = ("Feed",)


def enqueue_execute():
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.db_housekeeping.execute",
                 queue="long", timeout=3600)


def execute():
    st_time = time.time()
    cutoff = get_stock_queue_cutoff()
    if cutoff:
        freeze_stock_upto(cutoff)
        print(f"Trimmed FIFO queue of {trim_stock_queue(cutoff)} SLEs up to {cutoff}")
    else:
        print("No submitted Period Closing Voucher hence Skipping Stock Queue Trim")
    print(f"Deleted {delete_noise_versions()} noise Versions")
    print(f"Deleted {purge_access_log()} old Access Logs")
    print(f"Deleted {delete_orphan_global_search()} orphan Global Search rows")
    drop_orphan_tables()
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds")


def get_stock_queue_cutoff():
    """
    Returns the posting date (year end) of the latest submitted Period Closing Voucher, or None.
    SLEs on or before it are in a closed year, so their FIFO queue is never read again.
    """
    return frappe.db.sql("""SELECT MAX(posting_date) FROM `tabPeriod Closing Voucher`
        WHERE docstatus = 1""")[0][0]


def freeze_stock_upto(cutoff):
    """
    Moves Stock Settings Stock Frozen Upto forward to `cutoff`, never back. A back-dated SLE
    before the cutoff would read a trimmed queue and get a wrong FIFO rate.
    """
    current = frappe.db.get_single_value("Stock Settings", "stock_frozen_upto")
    if not current or getdate(current) < getdate(cutoff):
        frappe.db.set_value("Stock Settings", None, "stock_frozen_upto", cutoff)
        frappe.db.commit()


def trim_stock_queue(cutoff):
    """
    Sets stock_queue to '[]' on SLEs posted on or before `cutoff`, except the last
    non-cancelled SLE per item and warehouse. ERPNext (v13 to v16) reads the queue only from
    the latest SLE before a posting date, so that SLE and all later ones keep theirs.
    '[]' and not NULL, because stock_controller compares the queue with "[]".
    Returns the number of SLEs trimmed.
    """
    pairs = frappe.db.sql("""SELECT DISTINCT item_code, warehouse
        FROM `tabStock Ledger Entry`""", as_dict=1)
    trimmed = 0
    for pair in pairs:
        keeper = _get_last_sle(pair.item_code, pair.warehouse, cutoff)
        if keeper:
            trimmed += _clear_older_queues(pair.item_code, pair.warehouse, cutoff, keeper)
    return trimmed


def delete_noise_versions(days=None):
    """Versions of log-like doctypes, which nobody reads. Returns the number deleted."""
    days = days or NOISE_VERSION_DAYS
    return sum(_delete_versions(days, ref_doctype=dt) for dt in NOISE_VERSION_DOCTYPES)


def purge_access_log(days=None):
    """v13 has no clean-up for Access Log. Returns the number deleted."""
    query = """DELETE FROM `tabAccess Log`
        WHERE creation <= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY) LIMIT {limit}""".format(
        limit=BATCH_SIZE)
    return _run_in_batches(query, {"days": days or ACCESS_LOG_DAYS})


def delete_orphan_global_search():
    """
    Log Settings deletes old Activity Logs but leaves their Global Search rows.
    The two tables have different collations, hence the COLLATE.
    Returns the number deleted.
    """
    query = """DELETE FROM `__global_search` WHERE doctype = 'Activity Log'
        AND NOT EXISTS (SELECT 1 FROM `tabActivity Log` al
            WHERE al.name = `__global_search`.name COLLATE utf8mb4_unicode_ci)
        LIMIT {limit}""".format(limit=BATCH_SIZE)
    return _run_in_batches(query, {})


def drop_orphan_tables():
    for doctype in ORPHAN_TABLE_DOCTYPES:
        if not frappe.db.exists("DocType", doctype) and frappe.db.table_exists(doctype):
            print(f"Dropping orphan table tab{doctype}")
            frappe.db.sql_ddl(f"DROP TABLE `tab{doctype}`")


def _get_last_sle(item_code, warehouse, cutoff):
    keeper = frappe.db.sql("""SELECT name FROM `tabStock Ledger Entry`
        WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s
        AND is_cancelled = 0 AND posting_date <= %(cutoff)s
        ORDER BY posting_date DESC, posting_time DESC, creation DESC LIMIT 1""",
        {"item_code": item_code, "warehouse": warehouse, "cutoff": cutoff})
    return keeper[0][0] if keeper else None


def _clear_older_queues(item_code, warehouse, cutoff, keeper):
    query = """UPDATE `tabStock Ledger Entry` SET stock_queue = '[]'
        WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s
        AND posting_date <= %(cutoff)s AND name != %(keeper)s
        AND stock_queue IS NOT NULL AND stock_queue != '[]' LIMIT {limit}""".format(
        limit=BATCH_SIZE)
    return _run_in_batches(query, {"item_code": item_code, "warehouse": warehouse,
                                   "cutoff": cutoff, "keeper": keeper})


def _run_in_batches(query, values):
    """
    Runs a DELETE or UPDATE that has LIMIT BATCH_SIZE until it touches fewer rows, and commits
    after each batch, so one run does not lock the whole table. Returns the rows touched.
    """
    total = 0
    while True:
        frappe.db.sql(query, values)
        batch_count = cint(frappe.db._cursor.rowcount)
        frappe.db.commit()
        total += batch_count
        if batch_count < BATCH_SIZE:
            return total
