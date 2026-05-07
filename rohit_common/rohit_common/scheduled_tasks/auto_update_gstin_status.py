#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
import time
from datetime import date
from frappe.utils import flt
from frappe.utils.background_jobs import enqueue
from ..validations.address import validate_gstin_from_portal


BATCH_SIZE = 50


def enqueue_gstin_update():
    enqueue(execute, queue="long", timeout=7200)


def execute():
    start_time = time.time()
    validated_count = 0

    auto_days = flt(
        frappe.db.get_single_value("Rohit Settings", "auto_validate_gstin_after")
    )

    addresses = frappe.db.sql(
        """
        SELECT name, gstin
        FROM `tabAddress`
        WHERE gstin IS NOT NULL
            AND gstin != 'NA'
            AND disabled = 0
            AND country = 'India'
            AND (
                validated_gstin IS NULL
                OR DATE_ADD(IFNULL(gst_validation_date,'1900-01-01'), INTERVAL %s DAY) < CURDATE()
            )
        ORDER BY gstin, name
        """,
        auto_days,
        as_dict=True,
    )

    for i, row in enumerate(addresses, start=1):
        print(f"Checking Address {row.name} with GSTIN {row.gstin}")

        try:
            doc = frappe.get_doc("Address", row.name)

            validate_gstin_from_portal(doc, auto_days)

            doc.flags.ignore_mandatory = True
            doc.save()

            validated_count += 1
            print(f"{doc.name} Saved")

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"GSTIN Validation Failed for {row.name}",
            )

        if validated_count and validated_count % BATCH_SIZE == 0:
            print(
                f"Committing after {validated_count} validations "
                f"(Elapsed {int(time.time() - start_time)}s)"
            )
            frappe.db.commit()
            time.sleep(2)

    frappe.db.commit()

    print(f"Total GSTIN validated: {validated_count}")
    print(f"Total Time Taken: {int(time.time() - start_time)} seconds")