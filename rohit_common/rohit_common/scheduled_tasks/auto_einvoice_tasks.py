#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

import frappe
from frappe.utils import flt
from frappe.utils.background_jobs import enqueue
from erpnext.stock.stock_ledger import NegativeStockError

from ..india_gst_api.einv import generate_irn_from_doc


def enq_inv_sub():
    """
    Performs Draft Invoice Submission for 14 mins max since it runs every 15 mins
    """
    enqueue(get_docs_to_submit, queue="long", timeout=800)


def enq_einv_create():
    """
    Performs eInvoice jobs for 14 mins max since it runs every 15 mins
    """
    enqueue(make_einvoice_for_docs, queue="long", timeout=800)


def get_unposted_invoices():
    """
    Finds submitted invoices without GL entries and resets them to Draft.
    """
    log = frappe.logger("gl_repair")
    
    BATCH_SIZE = 20

    invoices = frappe.db.sql(
        """
        SELECT si.name
        FROM `tabSales Invoice` si
        LEFT JOIN `tabGL Entry` gle
            ON gle.voucher_no = si.name
            AND gle.voucher_type = 'Sales Invoice'
        WHERE si.base_grand_total > 0
        AND si.docstatus = 1
        AND gle.name IS NULL
        ORDER BY si.creation
        """,
        as_dict=True
    )

    processed = 0

    for row in invoices:

        try:
            doc = frappe.get_doc("Sales Invoice", row.name)

            doc.cancel()

            frappe.db.set_value(
                "Sales Invoice",
                row.name,
                {
                    "docstatus": 0,
                    "set_posting_time": 1,
                    "marked_to_submit": 1
                }
            )

            log.info(
                f"Sales Invoice {row.name} not posted in GL. Converted back to Draft."
            )

            processed += 1

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"GL repair failed for Sales Invoice {row.name}"
            )

        if processed and processed % BATCH_SIZE == 0:
            frappe.db.commit()

    frappe.db.commit()


def get_docs_to_submit():
    """
    Submits documents which were marked to submit
    """

    doc_list = ["Sales Invoice"]

    for doctype in doc_list:

        draft_docs = frappe.db.sql(
            f"""
            SELECT name
            FROM `tab{doctype}`
            WHERE docstatus = 0
            AND marked_to_submit = 1
            """,
            as_dict=True
        )

        for row in draft_docs:

            doc = frappe.get_doc(doctype, row.name)

            try:
                doc.submit()
                frappe.logger().info(f"Submitted {doctype} {doc.name}")
                
                # CRITICAL FIX: Commit only on success
                frappe.db.commit()

            except NegativeStockError:
                frappe.db.rollback()
                frappe.logger().warning(
                    f"Negative stock error while submitting {doc.name}"
                )

            except Exception:
                frappe.db.rollback()
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Submission failed for {doc.name}"
                )


def make_einvoice_for_docs():
    """
    Generates eInvoices for eligible documents
    """

    enable_einv = flt(
        frappe.db.get_single_value("Rohit Settings", "enable_einvoice")
    )

    if not enable_einv:
        return

    einv_date = frappe.db.get_single_value(
        "Rohit Settings",
        "einvoice_applicable_date"
    )

    invoices = frappe.db.sql(
        """
        SELECT name
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        AND (irn IS NULL OR ack_no IS NULL OR ack_date IS NULL)
        AND posting_date >= %s
        ORDER BY posting_date DESC, name DESC
        """,
        einv_date,
        as_dict=True
    )

    for row in invoices:

        try:
            doc = frappe.get_doc("Sales Invoice", row.name)
            
            if doc.gst_category in ("Unregistered", "Consumer"):
                continue

            frappe.logger().info(
                f"Generating eInvoice for Sales Invoice {doc.name}"
            )

            generate_irn_from_doc(doc)
            
            frappe.db.commit()

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                frappe.get_traceback(),
                f"eInvoice generation failed for {row.name}"
            )


def make_eway_bill_for_docs():
    """
    If eway is needed for a doc then eway bill is made based on IRN generated
    """
    pass