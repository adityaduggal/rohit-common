#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

import frappe
from frappe.utils import flt, getdate
from frappe.utils.background_jobs import enqueue
from erpnext.stock.stock_ledger import NegativeStockError
from ..india_gst_api.einv import (
    einv_needed,
    generate_irn,
    generate_irn_whitebooks,
    generate_irn_whitebooks_bulk,
)


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
    Submits the Sales Invoices or JV which are marked to Submit
    """
    doc_list = ["Sales Invoice"]
    for doc in doc_list:
        dft_doc = frappe.db.sql(f"""SELECT name FROM `tab{doc}` WHERE docstatus = 0
            AND marked_to_submit = 1""", as_dict=1)
        if dft_doc:
            for dtd in dft_doc:
                doc_t = frappe.get_doc(doc, dtd.name)
                try:
                    doc_t.submit()
                    print(f"Submitting {doc_t.name}")
                except NegativeStockError:
                    print(f"Negative Stock Error for {doc_t.name} hence Rolling Back")
                    frappe.db.rollback()
                except Exception as e:
                    print(f"Some Other Error for {doc_t.name} and Error = {e}")
                    frappe.db.rollback()
                frappe.db.commit()


def make_einvoice_for_docs():
    """
    Makes the einvoice for the Docs based on eInvoice Applicability and its Date
    """
    doc_list = ["Sales Invoice"]
    einv_app = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "enable_einvoice"))
    einv_date = frappe.get_value("Rohit Settings", "Rohit Settings", "einvoice_applicable_date")
    if einv_app == 1:
        for doc in doc_list:
            # `doc` (table name) comes from the fixed doc_list above, not user input, so
            # it's safe to interpolate directly (bind params can't parameterize identifiers
            # anyway). `einv_date` is a value, so it's bound rather than interpolated.
            query = f"""SELECT name, posting_date FROM `tab{doc}` WHERE docstatus = 1 AND
            (irn IS NULL OR ack_no IS NULL OR ack_date IS NULL) AND
            posting_date >= %(einv_date)s ORDER BY posting_date DESC, name DESC"""
            einv_docs = frappe.db.sql(query, {"einv_date": einv_date}, as_dict=1)
            if einv_docs:
                for einv in einv_docs:
                    need_einv = einv_needed(doc, einv.name)
                    if need_einv == 1:
                        try:
                            print(f"Trying to Generate eInvoice for {doc}: {einv.name}")
                            generate_irn(dtype=doc, dname=einv.name)
                        except Exception as e:
                            print(e)


def make_eway_bill_for_docs():
    """
    If eway is needed for a doc then eway bill is made based on IRN generated
    """
    pass


# ---------------------------------------------------------------------------
# WhiteBooks.in live path (T10, docs/designs/gst-asp-migration-whitebooks.md)
#
# NOT YET LIVE — generate_irn_whitebooks() (T3) is unverified against a real
# WhiteBooks sandbox response. This on_submit hook is wired in hooks.py, so
# it WILL fire once merged, but generate_irn_whitebooks() itself still needs
# The Assignment's sandbox handshake before this path can be trusted with
# real invoices. Until then, treat any failures here as expected.
#
# This is a genuinely new codepath, not a tweak to an existing one — before
# T10, no on_submit hook triggered e-invoice generation at all; the only
# existing mechanism was make_einvoice_for_docs()'s 15-minute cron sweep.
# ---------------------------------------------------------------------------

LIVE_EINVOICE_QUEUE = "short"


def queue_live_einvoice_submission(doc, method=None):
    """
    on_submit hook for Sales Invoice (see hooks.py). Enqueues the live-path
    WhiteBooks e-invoice submission on a dedicated short queue, immediately
    at submit time — not called inline, so the user's submit request isn't
    blocked on an external API call (same principle
    rohit_common.rohit_common.validations.sales_invoice.on_submit already
    follows for large invoices via doc.queue_action()).
    """
    if not _live_einvoice_applicable(doc):
        return
    enqueue(
        submit_live_einvoice_whitebooks,
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


def submit_live_einvoice_whitebooks(dtype, dname):
    """
    The live-path job body. Synchronous WhiteBooks call within this one
    background job — no E-Invoice Submission Log entry, no webhook: the
    single-invoice generate call returns the IRN in the same response (see
    Approach C's synchronous-live-path revision), so there's no async gap
    to correlate. A failure here is caught, logged, and re-raised so
    Frappe's own background-job failure tracking (RQ) sees it as failed —
    this invoice then falls through to the backlog sweep (T11) on its next
    15-minute run, since it will still be missing an IRN.
    """
    try:
        generate_irn_whitebooks(dtype, dname)
    except Exception as e:
        frappe.log_error(
            title="WhiteBooks live e-invoice submission failed",
            message=f"{dtype} {dname}: {e}",
        )
        raise


# ---------------------------------------------------------------------------
# WhiteBooks.in backlog path (T11, docs/designs/gst-asp-migration-whitebooks.md)
#
# NOT YET WIRED into scheduler_events — make_einvoice_for_docs() above
# remains the live 15-minute sweep (Charteredinfo, one invoice at a time)
# until this bulk path is sandbox-verified and the actual cutover happens.
# make_einvoice_for_docs_whitebooks_bulk() below is the intended eventual
# replacement, callable manually for testing in the meantime.
# ---------------------------------------------------------------------------


def _find_pending_einvoice_docs(einv_date):
    """Same query make_einvoice_for_docs() already uses, factored out so
    both the live sweep and the backlog bulk path find the same candidate
    set — see the design's Premise on the two paths agreeing on
    eligibility."""
    query = """SELECT name, posting_date FROM `tabSales Invoice` WHERE docstatus = 1 AND
        (irn IS NULL OR ack_no IS NULL OR ack_date IS NULL) AND
        posting_date >= %(einv_date)s ORDER BY posting_date DESC, name DESC"""
    return frappe.db.sql(query, {"einv_date": einv_date}, as_dict=1)


def _current_environment():
    rset = frappe.get_single("Rohit Settings")
    return "Sandbox" if bool(rset.sandbox_mode) else "Production"


def make_einvoice_for_docs_whitebooks_bulk():
    """
    Backlog/recovery path body. Finds every submitted Sales Invoice still
    missing an IRN (same candidate set as the live sweep — once the live
    path (T10) is cut over, this should normally be near-empty; non-empty
    means the live path failed or WhiteBooks was down for those invoices)
    and submits them together via generate_irn_whitebooks_bulk() (T11).

    Creates one E-Invoice Submission Log entry per invoice: `Failed` with
    the error recorded immediately for invoices the bulk ACK rejected
    synchronously (partial-batch-failure case — NOT all-or-nothing),
    `Submitted` for invoices accepted for async processing, awaiting the
    webhook (T9) to resolve them to Success/Failed later.

    Returns {"submitted": N, "rejected": M} — 0/0 if e-invoicing is
    disabled or there's nothing pending.
    """
    einv_app = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "enable_einvoice"))
    if einv_app != 1:
        return {"submitted": 0, "rejected": 0}

    einv_date = frappe.get_value("Rohit Settings", "Rohit Settings", "einvoice_applicable_date")
    einv_docs = _find_pending_einvoice_docs(einv_date)
    dnames = [d.name for d in einv_docs if einv_needed("Sales Invoice", d.name) == 1]
    if not dnames:
        return {"submitted": 0, "rejected": 0}

    submission_ids, immediate_rejections = generate_irn_whitebooks_bulk("Sales Invoice", dnames)
    environment = _current_environment()
    submitted = 0
    rejected = 0
    for dname in dnames:
        error = immediate_rejections.get(dname)
        is_rejected = dname in immediate_rejections
        log = frappe.get_doc(
            {
                "doctype": "E-Invoice Submission Log",
                "reference_doctype": "Sales Invoice",
                "reference_name": dname,
                "submission_path": "Backlog",
                "environment": environment,
                "status": "Failed" if is_rejected else "Submitted",
                "submission_id": submission_ids[dname],
                "error_message": error,
                "submitted_on": frappe.utils.now_datetime(),
            }
        )
        log.insert(ignore_permissions=True)
        if is_rejected:
            rejected += 1
            frappe.log_error(
                title="WhiteBooks backlog e-invoice rejected",
                message=f"{dname}: {error}",
            )
        else:
            submitted += 1
    frappe.db.commit()
    return {"submitted": submitted, "rejected": rejected}
