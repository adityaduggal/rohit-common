# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the Sales Invoices in ERP and Update the
# Shipping Bill No and Shipping Bill Date

import time
import frappe
from ..erpnext_api.erpnext_api_common import get_dt
from ...utils.accounts_utils import get_base_doc_no


BATCH_SIZE = 50


def update_export_invoices():
    log = frappe.logger("export_invoice_update")

    start_time = time.time()
    updated = 0

    invoices = frappe.db.sql("""
        SELECT
            si.name,
            si.amended_from
        FROM `tabSales Invoice` si
        JOIN `tabSales Taxes and Charges Template` st
            ON si.taxes_and_charges = st.name
        WHERE
            si.docstatus = 1
            AND si.base_net_total > 0
            AND st.disabled = 0
            AND st.is_export = 1
            AND si.shipping_bill_number IS NULL
        ORDER BY si.creation
    """, as_dict=True)

    for inv in invoices:

        try:
            doc = frappe.get_doc("Sales Invoice", inv.name)
            base_si_no = get_base_doc_no(doc)

            filters = [
                ["docstatus", "=", 1],
                ["name", "like", f"%{base_si_no}%"]
            ]

            result = get_dt(
                dt="Sales Invoice",
                fields_list=["name", "shipping_bill_number", "shipping_bill_date"],
                filters=filters
            )

            if result and result.get("data"):
                row = result["data"][0]

                frappe.db.set_value(
                    "Sales Invoice",
                    inv.name,
                    {
                        "shipping_bill_number": row.get("shipping_bill_number"),
                        "shipping_bill_date": row.get("shipping_bill_date"),
                    }
                )

                updated += 1
                log.info(f"Updated shipping bill for {inv.name}")

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Export invoice update failed for {inv.name}"
            )

        if updated and updated % BATCH_SIZE == 0:
            frappe.db.commit()

    frappe.db.commit()

    log.info(f"Total Invoices Updated = {updated}")
    log.info(f"Total Time Taken = {int(time.time() - start_time)} seconds")

