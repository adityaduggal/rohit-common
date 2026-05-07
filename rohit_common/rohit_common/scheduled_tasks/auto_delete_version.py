# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the table TabVersion and delete from them old entries.
# Based on Reference Doctype mentioned in the Rohit Settings.

import time
import frappe
from frappe.utils import flt, nowdate, add_days
from frappe.utils.background_jobs import enqueue

log = frappe.logger("version_cleanup")

BATCH_SIZE = 5000


def enqueue_deletion():
    enqueue(execute, queue="long", timeout=3600)


def delete_versions(query, params):
    """
    Deletes versions using SQL batching
    """
    deleted = 0

    while True:

        rows = frappe.db.sql(
            f"""
            SELECT name
            FROM `tabVersion`
            {query}
            LIMIT %s
            """,
            params + (BATCH_SIZE,),
            as_dict=True,
        )

        if not rows:
            break

        names = [r.name for r in rows]

        frappe.db.sql(
            f"""
            DELETE FROM `tabVersion`
            WHERE name IN ({",".join(["%s"] * len(names))})
            """,
            names,
        )

        frappe.db.commit()

        deleted += len(names)

        log.info(f"Deleted {deleted} versions so far")

    return deleted


def execute():

    start = time.time()

    settings = frappe.get_single("Rohit Settings")

    max_days = int(flt(settings.max_days_to_keep_version) or 30)

    cutoff = add_days(nowdate(), -max_days)

    dt_list = [row.document_type for row in settings.auto_delete_from_version]

    # -------------------------
    # Unregulated doctypes
    # -------------------------

    if dt_list:

        placeholders = ", ".join(["%s"] * len(dt_list))

        query = f"""
        WHERE ref_doctype NOT IN ({placeholders})
        AND creation <= %s
        """

        params = tuple(dt_list) + (cutoff,)

    else:

        query = """
        WHERE creation <= %s
        """

        params = (cutoff,)

    deleted_unregulated = delete_versions(query, params)

    # -------------------------
    # Regulated doctypes
    # -------------------------

    deleted_regulated = 0

    for row in settings.auto_delete_from_version:

        days = int(flt(row.days_to_keep) or 1)

        cutoff = add_days(nowdate(), -days)

        log.info(
            f"Deleting versions for {row.document_type} older than {days} days"
        )

        query = """
        WHERE ref_doctype = %s
        AND creation <= %s
        """

        params = (row.document_type, cutoff)

        deleted_regulated += delete_versions(query, params)

    total = deleted_unregulated + deleted_regulated

    log.info(f"Total Versions Deleted = {total}")
    log.info(f"Total runtime = {int(time.time() - start)}s")
