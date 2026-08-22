import frappe

from rohit_common.rohit_common.india_gst_api.qr_backfill import backfill_signed_qr_code


def execute():
    """
    Backfills Sales Invoice.signed_qr_code from existing qrcode_image PNGs
    (T7, docs/designs/gst-asp-migration-whitebooks.md).

    DO NOT let this patch run automatically as part of a routine
    `bench migrate` until sample_decode_check() (in
    rohit_common.rohit_common.india_gst_api.qr_backfill) has been run
    manually against real production data and confirmed a decode rate of
    at least 95% — that decision has not been made yet as of 2026-08-22
    (this was written without bench/site access). The guard below makes
    that an explicit, deliberate opt-in rather than a silent skip or an
    accidental run. Full manual runbook: docs/qr-backfill-runbook.md.
    """
    if not frappe.flags.get("qr_backfill_confirmed"):
        frappe.logger().warning(
            "Skipping backfill_signed_qr_code patch: sample_decode_check() has not "
            "been run and confirmed against real data yet. See "
            "docs/qr-backfill-runbook.md for the manual steps — run "
            "sample_decode_check() via bench console, decide, then set "
            "frappe.flags.qr_backfill_confirmed = True and call "
            "backfill_signed_qr_code() directly in that same console session "
            "(frappe.flags is per-process, so `bench execute` from a fresh "
            "process won't see a flag set externally)."
        )
        return

    if not frappe.db.has_column("Sales Invoice", "signed_qr_code"):
        return

    backfill_signed_qr_code()
