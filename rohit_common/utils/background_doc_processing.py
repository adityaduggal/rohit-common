# -*- coding: utf-8 -*-
# Copyright (c) 2022, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import re
import frappe
import time
from frappe.utils import cstr, escape_html, strip_html
from frappe.utils.background_jobs import enqueue, get_jobs
from rq.timeouts import JobTimeoutException

BG_TIMEOUT = 2700
# Stop picking new docs this long before the rq timeout, so one slow doc can still finish
BG_TIME_BUDGET = 2400
BG_BATCH_SIZE = 200
FAILURE_NOTE_LENGTH = 140


def enqueue_bg():
    enqueue_once("rohit_common.utils.background_doc_processing.process_bg_docs",
                 queue="long", timeout=BG_TIMEOUT)


def enqueue_once(method, queue, timeout):
    """
    Enqueues the dotted path `method` unless it is already queued or running for this
    site. In v13 job_name is only a label, so a cron that fires faster than its job
    finishes piles up copies on the queue (#16). Returns True if it enqueued.
    """
    site = frappe.local.site
    if method in get_jobs(site=site, queue=queue, key="job_name").get(site, []):
        print(f"{method} is already queued or running on {queue} hence Skipping")
        return False
    enqueue(method, queue=queue, timeout=timeout, job_name=method)
    return True


def unmark_failed_doc(doctype, name, flag_field, action, exc):
    """
    Call from the `except` block of a background submit/cancel. Rolls back, clears
    `flag_field` so later runs skip the doc, leaves a short comment that tells the user
    what failed, and puts the full traceback in the Error Log.
    """
    traceback = frappe.get_traceback()
    frappe.db.rollback()
    frappe.local.message_log = []
    frappe.db.set_value(doctype, name, flag_field, 0, update_modified=False)
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": doctype,
        "reference_name": name,
        "content": f"Auto {action} failed: {short_error(exc)}. Fix it and tick "
                   f"{frappe.unscrub(flag_field)} again, or ask a System Manager.",
    }).insert(ignore_permissions=True)
    frappe.log_error(traceback, f"Auto {action} Failed for {doctype} {name}")
    frappe.db.commit()


def short_error(exc):
    """One line of escaped plain text from an exception, short enough for a comment."""
    message = re.sub(r"\s+", " ", strip_html(cstr(exc))).strip() or type(exc).__name__
    if len(message) > FAILURE_NOTE_LENGTH:
        message = message[:FAILURE_NOTE_LENGTH - 3] + "..."
    return escape_html(message)


def get_bg_docs():
    """
    Returns a list of document types which are enabled for Background processing
    The document type should also have a checkbox with name background_processing
    """
    doc_lst = []
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    for dtd in rset.bg_submit_cancel_docs:
        doc_lst.append(dtd.document_type)
    return doc_lst


def process_bg_docs():
    """
    Submits drafts and cancels submitted docs marked for Background Processing, oldest
    first, until the batch or time budget runs out. A doc that fails is unmarked so it
    does not stop the docs behind it on every run (#16).
    """
    st_time = time.time()
    tot_docs = 0
    for dtd in get_bg_docs():
        print(f"Processing Background Submit or Cancel for {dtd}")
        docs_marked = frappe.get_all(dtd, fields=["name", "docstatus"],
            filters={"background_processing": 1, "docstatus": ["<", 2]},
            order_by="modified", limit=BG_BATCH_SIZE)
        for mkd_dt in docs_marked:
            if time.time() - st_time > BG_TIME_BUDGET:
                print(f"Time Budget of {BG_TIME_BUDGET} seconds Used hence Stopping")
                return
            action = "submit" if mkd_dt.docstatus == 0 else "cancel"
            try:
                mkd_doc = frappe.get_doc(dtd, mkd_dt.name)
                print(f"Running {action} for {mkd_doc.name}")
                mkd_doc.background_processing = 0
                mkd_doc.save()
                getattr(mkd_doc, action)()
                frappe.db.commit()
                tot_docs += 1
            except JobTimeoutException:
                raise
            except Exception as e:
                unmark_failed_doc(dtd, mkd_dt.name, "background_processing", action, e)
    print(f"Total Time Taken = {int(time.time() - st_time)} seconds Docs Processed = {tot_docs}")
