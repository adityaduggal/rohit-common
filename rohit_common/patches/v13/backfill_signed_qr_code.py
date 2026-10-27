import frappe
from frappe.modules.utils import sync_customizations

from rohit_common.rohit_common.india_gst_api.qr_backfill import (
    backfill_signed_qr_code,
    check_dependencies,
)


def execute():
    """
    Backfills Sales Invoice.signed_qr_code from the qrcode_image PNGs
    (issue #17). The patches.txt suffix was bumped to #2026-10-27 so this
    runs once more: the #2026-08-22 run was logged as done although a flag
    gate made it skip.

    A missing dependency raises, so the patch is not logged and runs again on
    the next migrate. Invoices that fail to decode (e.g. PNG missing on disk)
    don't fail the patch: they're in the Error Log, and
    backfill_signed_qr_code() can be re-run from the console. Runbook:
    docs/qr-backfill-runbook.md.
    """
    check_dependencies()
    # Patches run before migrate syncs custom fields, so add the field first.
    if not frappe.db.has_column("Sales Invoice", "signed_qr_code"):
        sync_customizations("rohit_common")
    backfill_signed_qr_code()
