#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

import time
import frappe
import requests
from frappe.utils import add_to_date, flt, getdate, now_datetime
from frappe.utils.background_jobs import enqueue
from rq.timeouts import JobTimeoutException
from ..india_gst_api.einv import einv_needed, generate_irn
from ...utils.background_doc_processing import enqueue_once, short_error, unmark_failed_doc

SWEEP_TIMEOUT = 800
# Both sweeps run every 15 mins. Stop picking new invoices well before the rq timeout.
SWEEP_TIME_BUDGET = 600
SUBMIT_BATCH_SIZE = 200
EINV_BATCH_SIZE = 100
EINV_FAILURE_TITLE = "eInvoice Generation Failed for "
EINV_RETRY_AFTER_HOURS = 24


def enq_inv_sub():
    """
    Performs Draft Invoice Submission for 14 mins max since it runs every 15 mins
    """
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.get_docs_to_submit",
                 queue="long", timeout=SWEEP_TIMEOUT)


def enq_einv_create():
    """
    Performs eInvoice jobs for 14 mins max since it runs every 15 mins
    """
    enqueue_once("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.make_einvoice_for_docs",
                 queue="long", timeout=SWEEP_TIMEOUT)


def get_unposted_invoices():
    """
    Gets a list of invoices which are not posted in the General Ledger and also the ones
    not posted in Stock Ledger
    """
    gl_not_posted = frappe.db.sql("""SELECT si.name, si.creation FROM `tabSales Invoice` si
        WHERE si.base_grand_total > 0 AND si.docstatus = 1 AND si.name NOT IN (SELECT gle.voucher_no
        FROM `tabGL Entry` gle WHERE gle.voucher_type = 'Sales Invoice'
        AND gle.voucher_no = si.name) ORDER BY si.creation""", as_dict=1)
    for un_si in gl_not_posted:
        # Bug fix: un_si is a _dict row (name, creation), not a document name. Passing a
        # dict as the `name` arg makes frappe.get_doc() construct a new unsaved in-memory
        # document instead of loading the real Sales Invoice, so sid.cancel() would operate
        # on the wrong object. Use un_si.name to load the actual document.
        sid = frappe.get_doc("Sales Invoice", un_si.name)
        sid.cancel()
        frappe.db.set_value("Sales Invoice", un_si.name, "docstatus", 0)
        frappe.db.set_value("Sales Invoice", un_si.name, "set_posting_time", 1)
        frappe.db.set_value("Sales Invoice", un_si.name, "marked_to_submit", 1)
        print(f"SI# {un_si.name} not Posted in General Ledger hence Made Draft")


def get_docs_to_submit():
    """
    Submits the Sales Invoices marked to Submit, oldest first, until the batch or time
    budget runs out. An invoice that fails is unmarked with a short comment, so it does
    not use the budget again on every run (#16).
    """
    st_time = time.time()
    dft_docs = frappe.get_all("Sales Invoice", filters={"docstatus": 0, "marked_to_submit": 1},
        order_by="posting_date, name", limit=SUBMIT_BATCH_SIZE, pluck="name")
    for dname in dft_docs:
        if time.time() - st_time > SWEEP_TIME_BUDGET:
            print(f"Time Budget of {SWEEP_TIME_BUDGET} seconds Used hence Stopping")
            return
        try:
            frappe.get_doc("Sales Invoice", dname).submit()
            frappe.db.commit()
            print(f"Submitted {dname}")
        except JobTimeoutException:
            raise
        except Exception as e:
            unmark_failed_doc("Sales Invoice", dname, "marked_to_submit", "submit", e)


def make_einvoice_for_docs():
    """
    Makes the einvoice for the Docs based on eInvoice Applicability and its Date.
    Each run is limited by a batch size and a time budget. An invoice that failed in the
    last EINV_RETRY_AFTER_HOURS is skipped, so a bad GSTIN or HSN does not make an ASP
    call every 15 mins (#16).
    """
    einv_app = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "enable_einvoice"))
    if einv_app != 1:
        return
    einv_date = frappe.get_value("Rohit Settings", "Rohit Settings", "einvoice_applicable_date")
    st_time = time.time()
    einv_docs = _find_pending_einvoice_docs(einv_date, exclude=_recent_einvoice_failures(),
        limit=EINV_BATCH_SIZE)
    for einv in einv_docs:
        if time.time() - st_time > SWEEP_TIME_BUDGET:
            print(f"Time Budget of {SWEEP_TIME_BUDGET} seconds Used hence Stopping")
            return
        try:
            print(f"Trying to Generate eInvoice for Sales Invoice: {einv.name}")
            generate_irn(dtype="Sales Invoice", dname=einv.name)
        except JobTimeoutException:
            raise
        except requests.RequestException as e:
            # A request error's text can hold a URL with credentials, so log only its
            # type (#23). whitebooks_provider already raises without the URL.
            frappe.db.rollback()
            frappe.log_error(f"Request to ASP failed: {type(e).__name__}", EINV_FAILURE_TITLE + einv.name)
        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(f"{short_error(e)}\n\n{frappe.get_traceback()}", EINV_FAILURE_TITLE + einv.name)
        frappe.db.commit()


def _recent_einvoice_failures():
    """Invoice names whose eInvoice failed within the last EINV_RETRY_AFTER_HOURS."""
    cutoff = add_to_date(now_datetime(), hours=-EINV_RETRY_AFTER_HOURS)
    titles = frappe.get_all("Error Log", pluck="method",
        filters={"method": ["like", EINV_FAILURE_TITLE + "%"], "creation": [">", cutoff]})
    return list({title[len(EINV_FAILURE_TITLE):] for title in titles})


# ---------------------------------------------------------------------------
# Live path: each Sales Invoice is sent to WhiteBooks right after submit. An
# invoice the live job misses (WhiteBooks down, validation error) still has no
# IRN, so the 15-min sweep above retries it.
# ---------------------------------------------------------------------------

LIVE_EINVOICE_QUEUE = "short"
# The sweep leaves invoices this new to the live job, so both do not send the same
# invoice at once. If they still do, the second gets a duplicate IRN reply, and
# generate_irn() saves the existing IRN.
LIVE_JOB_GRACE_MINS = 10


def queue_live_einvoice_submission(doc, method=None):
    """
    on_submit hook for Sales Invoice (see hooks.py). Enqueues the IRN on the
    short queue, so the user's submit request does not wait for the GST system.
    """
    if not _live_einvoice_applicable(doc):
        return
    enqueue(
        submit_live_einvoice,
        queue=LIVE_EINVOICE_QUEUE,
        timeout=60,
        dtype=doc.doctype,
        dname=doc.name,
    )


def _live_einvoice_applicable(doc):
    """Mirrors make_einvoice_for_docs()'s existing gating logic
    (enable_einvoice, einvoice_applicable_date, einv_needed) so the live
    path and the backlog sweep agree on what counts as e-invoice-eligible."""
    einv_app = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "enable_einvoice"))
    if einv_app != 1:
        return False
    einv_date = frappe.get_value("Rohit Settings", "Rohit Settings", "einvoice_applicable_date")
    if einv_date and getdate(doc.posting_date) < getdate(einv_date):
        return False
    return einv_needed(doc.doctype, doc.name) == 1


def submit_live_einvoice(dtype, dname):
    """
    The live-path job body. A failure is logged with the same title the sweep
    uses, so the sweep backs off this invoice for EINV_RETRY_AFTER_HOURS, and is
    re-raised so RQ marks the job failed.
    """
    try:
        generate_irn(dtype, dname)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"{short_error(e)}\n\n{frappe.get_traceback()}", EINV_FAILURE_TITLE + dname)
        frappe.db.commit()
        raise


def _find_pending_einvoice_docs(einv_date, exclude=None, limit=None):
    """Submitted Sales Invoices still missing an IRN, newest first, that the live
    job had time to handle.

    Unregistered (B2C) invoices never get an IRN, so they are filtered here in SQL and
    not by einv_needed() per row. IFNULL keeps einv_needed()'s rule that a blank
    gst_category still needs an eInvoice."""
    values = {"einv_date": einv_date, "exclude": tuple(exclude or ()), "limit": limit,
              "settled": add_to_date(now_datetime(), minutes=-LIVE_JOB_GRACE_MINS)}
    query = """SELECT name, posting_date FROM `tabSales Invoice` WHERE docstatus = 1 AND
        (irn IS NULL OR ack_no IS NULL OR ack_date IS NULL) AND
        IFNULL(gst_category, '') != 'Unregistered' AND modified < %(settled)s AND
        posting_date >= %(einv_date)s{name_filter} ORDER BY posting_date DESC, name DESC{limit}"""
    return frappe.db.sql(query.format(
        name_filter=" AND name NOT IN %(exclude)s" if exclude else "",
        limit=" LIMIT %(limit)s" if limit else "",
    ), values, as_dict=1)
