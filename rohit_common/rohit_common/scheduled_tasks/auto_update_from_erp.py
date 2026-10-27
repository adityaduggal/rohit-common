# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would Periodically check the Sales Invoices in ERP and Update the
# Shipping Bill No and Shipping Bill Date

from __future__ import unicode_literals
import frappe
import time
import requests
from rq.timeouts import JobTimeoutException
from ..erpnext_api.erpnext_api_common import get_dt, get_login_details
from ...utils.accounts_utils import get_base_doc_map
from ...utils.background_doc_processing import enqueue_once

EXPORT_UPDATE_FAILURE_TITLE = "Shipping Bill Update from ERP Failed"


def enqueue_update_export_invoices():
    # One HTTP call per invoice does not fit in the default queue's timeout
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.auto_update_from_erp.update_export_invoices",
                 queue="long", timeout=3600)


def update_export_invoices():
    """
    Copies the Shipping Bill No and Date from the ERP into each submitted export invoice that
    does not have them. An invoice whose request fails is skipped, and all failures go into
    one Error Log at the end.
    """
    if not get_login_details()[0]:
        return
    st_time = time.time()
    records_updated = 0
    failures = []
    fields = ["name", "shipping_bill_number", "shipping_bill_date"]
    pending = _pending_export_invoices()
    base_doc_map = get_base_doc_map("Sales Invoice", [inv.amended_from for inv in pending if inv.amended_from])
    for inv in pending:
        base_si_no = base_doc_map.get(inv.amended_from) if inv.amended_from else inv.name
        if not base_si_no:
            failures.append(f"{inv.name}: Amendment chain from {inv.amended_from} is broken")
            continue
        filters = [["docstatus", "=", 1], ["name", "LIKE", "%" + str(base_si_no) + "%"]]
        try:
            r = get_dt(dt="Sales Invoice", fields_list=fields, filters=filters)
        except JobTimeoutException:
            raise
        except (requests.RequestException, ValueError) as e:
            # A request error's text can hold the URL, so keep only its type (#23)
            failures.append(f"{inv.name}: {type(e).__name__}")
            continue
        if r and r.get("data"):
            epd = frappe._dict(r.get("data")[0])
            if epd.shipping_bill_number:
                frappe.db.set_value("Sales Invoice", inv.name, {
                    "shipping_bill_number": epd.shipping_bill_number,
                    "shipping_bill_date": epd.shipping_bill_date,
                })
                records_updated += 1
                print(f"Updated Shipping Bill No and Date in {inv.name}")
    if failures:
        frappe.log_error("\n".join(failures), EXPORT_UPDATE_FAILURE_TITLE)
    print(f"Total Invoices Updated = {records_updated}, Failed = {len(failures)}")
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds")


def _pending_export_invoices():
    return frappe.db.sql("""SELECT si.name, si.amended_from
        FROM `tabSales Invoice` si, `tabSales Taxes and Charges Template` st
        WHERE si.docstatus=1 AND si.base_net_total > 0 AND si.taxes_and_charges = st.name AND st.disabled = 0
        AND st.is_export = 1 AND si.shipping_bill_number IS NULL ORDER BY si.creation""", as_dict=1)
