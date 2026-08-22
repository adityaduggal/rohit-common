#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Inbound webhook endpoint for WhiteBooks e-invoice async results (T9, docs/
designs/gst-asp-migration-whitebooks.md).

**NOT YET LIVE.** Built per T9, but two blocking dependencies from the
design doc remain unresolved, and this must not be registered with
WhiteBooks (or relied on) until they are:

1. **Push-vs-poll (T2, still open)**: whether WhiteBooks actually pushes
   webhook results, or requires polling a status endpoint instead, has not
   been confirmed against WhiteBooks' real API reference/sandbox. This
   module assumes push. If it turns out to be poll-based, this whole file
   is the wrong architecture and needs replacing with a scheduled polling
   job instead — not a tunable detail.
2. **Signature mechanism (UNVERIFIED)**: `verify_webhook_signature()` below
   assumes HMAC-SHA256 of the raw request body, hex-encoded, presented in
   an `X-WhiteBooks-Signature` header — the single most common webhook
   signing convention, used as a placeholder since WhiteBooks' actual
   signing mechanism was not in the pages fetched during this design's
   WebSearch. Confirm against WhiteBooks' real docs before trusting this.
3. **Response/payload shape (UNVERIFIED)**: `_process_webhook_result()`'s
   reading of `payload.get("status")`/`payload.get("irn")`/
   `payload.get("submission_id")` is a placeholder guess at WhiteBooks'
   webhook body shape, not confirmed.

**Security surface, per the architecture finding this closes**: this is the
first `allow_guest=True` endpoint in this app — no Frappe session exists,
so signature verification is the entire identity check. Layered controls:

- Signature verification (primary, required) — fails CLOSED: an unconfigured
  secret rejects every request, it does not silently allow unsigned calls.
- IP allowlist (defense-in-depth, best-effort) — only enforced if
  `Rohit Settings.whitebooks_webhook_ip_allowlist` is populated. Left blank
  by default since WhiteBooks hasn't published source IPs to allowlist as
  of 2026-08-22 (design doc's own note on this).
- Rate limiting, independent of signature checks, via Frappe's own
  `frappe.rate_limiter.rate_limit` — so a flood of malformed requests can't
  hammer the endpoint before signature verification even runs.
- Idempotency dedupe on `submission_id` against `E-Invoice Submission Log`
  — a duplicate/replayed webhook delivery for an already-resolved
  submission is acknowledged without reprocessing, per the design's
  webhook-idempotency requirement.
"""
import hashlib
import hmac

import frappe
from frappe.rate_limiter import rate_limit

WEBHOOK_RATE_LIMIT = 60
WEBHOOK_RATE_LIMIT_WINDOW_SEC = 60


def _request_ip():
    return getattr(frappe.local, "request_ip", None) or "127.0.0.1"


def _get_allowed_ips():
    rset = frappe.get_single("Rohit Settings")
    raw = getattr(rset, "whitebooks_webhook_ip_allowlist", None) or ""
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def check_ip_allowlist():
    """Best-effort defense-in-depth — see module docstring. A blank
    allowlist means this check is not enforced; it does not mean every
    request is rejected (that's the signature check's job)."""
    allowed = _get_allowed_ips()
    if not allowed:
        return
    if _request_ip() not in allowed:
        frappe.throw("Forbidden", frappe.PermissionError)


def verify_webhook_signature(raw_body, signature_header):
    """UNVERIFIED mechanism — see module docstring. Fails CLOSED: no
    secret configured, or no/mismatched signature header, both return
    False (reject), never an implicit allow."""
    if not signature_header:
        return False
    rset = frappe.get_single("Rohit Settings")
    secret = rset.get_password("whitebooks_webhook_secret")
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _extract_submission_id(payload):
    return payload.get("submission_id") or payload.get("submissionId")


def process_webhook_result(submission_id, payload):
    """Applies a webhook result to the matching E-Invoice Submission Log
    entry. Idempotent: a submission_id already in a terminal state
    (Success/Failed) is acknowledged without reprocessing — this is the
    dedupe half of the design's webhook-idempotency requirement (the other
    half, `submission_id` being `unique` on the doctype, prevents the
    outbound side from ever creating two log entries for one submission).
    """
    existing = frappe.db.get_value(
        "E-Invoice Submission Log",
        {"submission_id": submission_id},
        ["name", "status"],
        as_dict=True,
    )
    if not existing:
        frappe.log_error(
            title="WhiteBooks webhook: unknown submission_id",
            message=f"submission_id={submission_id}, payload={payload}",
        )
        return

    if existing.status in ("Success", "Failed"):
        return

    # UNVERIFIED response shape — see module docstring, point 3.
    if payload.get("irn") or payload.get("status") == "success":
        frappe.db.set_value(
            "E-Invoice Submission Log",
            existing.name,
            {"status": "Success", "irn": payload.get("irn")},
        )
    else:
        frappe.db.set_value(
            "E-Invoice Submission Log",
            existing.name,
            {"status": "Failed", "error_message": payload.get("error") or str(payload)},
        )
    frappe.db.commit()


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=WEBHOOK_RATE_LIMIT, seconds=WEBHOOK_RATE_LIMIT_WINDOW_SEC, methods="POST")
def whitebooks_einvoice_webhook():
    """Entry point. Reachable at
    /api/method/rohit_common.rohit_common.india_gst_api.webhook.whitebooks_einvoice_webhook
    once whitelisted — no separate hooks.py wiring needed for a new
    whitelisted method. NOT YET registered with WhiteBooks — see module
    docstring for the two blocking dependencies that must be confirmed
    first."""
    check_ip_allowlist()

    raw_body = frappe.request.get_data()
    signature = frappe.request.headers.get("X-WhiteBooks-Signature")
    if not verify_webhook_signature(raw_body, signature):
        frappe.throw("Invalid signature", frappe.PermissionError)

    payload = frappe.parse_json(raw_body)
    submission_id = _extract_submission_id(payload)
    if not submission_id:
        frappe.throw("Missing submission_id in webhook payload")

    process_webhook_result(submission_id, payload)
    return {"status": "ok"}
