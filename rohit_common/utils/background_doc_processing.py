# -*- coding: utf-8 -*-
# Copyright (c) 2022, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

import time
import frappe
from frappe.utils.background_jobs import enqueue


BATCH_SIZE = 20


def enqueue_bg():
    enqueue(process_bg_docs, queue="long", timeout=2700)


def get_bg_docs():
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    return [d.document_type for d in rset.bg_submit_cancel_docs]


def process_bg_docs():
    log = frappe.logger("bg_processing")

    start = time.time()
    total = 0

    doctypes = get_bg_docs()

    for dt in doctypes:

        log.info(f"Processing background docs for {dt}")

        docs = frappe.db.sql(f"""
            SELECT name, docstatus
            FROM `tab{dt}`
            WHERE background_processing = 1
            AND docstatus IN (0,1)
        """, as_dict=True)

        for row in docs:

            try:

                doc = frappe.get_doc(dt, row.name)

                doc.background_processing = 0

                if row.docstatus == 0:
                    log.info(f"Submitting {doc.name}")
                    doc.submit()

                elif row.docstatus == 1:
                    log.info(f"Cancelling {doc.name}")
                    doc.cancel()

                total += 1

            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Background processing failed for {dt} {row.name}"
                )

            if total % BATCH_SIZE == 0:
                frappe.db.commit()

    frappe.db.commit()

    log.info(
        f"Background processing completed in {int(time.time() - start)}s | Docs processed {total}"
    )