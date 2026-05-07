import frappe
import csv
import os
from frappe.utils import now_datetime


def close_zero_amount_delivery_notes(dry_run=True, batch_size=500, limit=None, write_csv=True):
    """
    Close zero-amount Delivery Notes that incorrectly show in
    "Get Items from Delivery Note" in Sales Invoice.

    After v12 → v16 migration, ~2200 old Delivery Notes have grand_total = 0
    (rates/amounts zeroed out during migration). Since per_billed = billed_amt/amount,
    and both are 0, per_billed stays at 0% forever, causing them to appear as
    unbilled in Sales Invoice.

    This script uses ERPNext's "Close" workflow status — the proper way to mark DNs
    as finalized without modifying any financial data (per_billed, billed_amt, etc.).

    The get_delivery_notes_to_be_billed query already excludes status='Closed'.

    - dry_run=True : only prints what would be changed, no DB writes
    - batch_size : number of updates before commit
    - limit : optional integer - limit number of entries processed (for testing)
    - write_csv : write audit CSV to /tmp/
    Returns a summary dict.
    """
    frappe.flags.in_migrate = True

    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    # Find all affected DNs
    affected_dns = frappe.db.sql(f"""
        SELECT dn.name, dn.posting_date, dn.customer, dn.status,
            dn.per_billed, dn.per_returned, dn.grand_total
        FROM `tabDelivery Note` dn
        WHERE dn.docstatus = 1
            AND dn.grand_total = 0
            AND dn.per_billed < 100
            AND dn.status NOT IN ('Stopped', 'Closed')
        ORDER BY dn.posting_date
        {limit_clause}
    """, as_dict=1)

    total = len(affected_dns)
    print(f"\nFound {total} zero-amount Delivery Note(s) with per_billed < 100.")

    if total == 0:
        return {"total_found": 0, "updated": 0, "skipped": 0, "errors": []}

    # Breakdown by status
    status_counts = {}
    for dn in affected_dns:
        status_counts[dn.status] = status_counts.get(dn.status, 0) + 1
    print("\nBreakdown by current status:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Date range
    print(f"\nDate range: {affected_dns[0].posting_date} to {affected_dns[-1].posting_date}")

    # Check how many have SI references
    with_si = frappe.db.sql("""
        SELECT COUNT(DISTINCT dn.name)
        FROM `tabDelivery Note` dn
        WHERE dn.docstatus = 1 AND dn.grand_total = 0 AND dn.per_billed < 100
            AND dn.status NOT IN ('Stopped', 'Closed')
            AND EXISTS (
                SELECT 1 FROM `tabSales Invoice Item` sii
                JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
                WHERE sii.delivery_note = dn.name
            )
    """)[0][0]
    print(f"\nOf these, {with_si} already have linked Sales Invoices")
    print(f"And {total - with_si} have no SI references (zero-value, nothing to bill)")

    # CSV audit log
    writer = None
    csv_file = None
    csv_path = ""

    if write_csv:
        timestamp = now_datetime().strftime("%Y%m%d%H%M%S")
        csv_path = f"/tmp/close_zero_dns_{'dryrun' if dry_run else 'update'}_{timestamp}.csv"
        os.makedirs("/tmp", exist_ok=True)
        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_file, fieldnames=[
            "name", "posting_date", "customer", "old_status", "new_status",
            "per_billed", "per_returned", "grand_total", "has_si", "action"
        ])
        writer.writeheader()

    updated = 0
    skipped = 0
    errors = []

    for counter, dn in enumerate(affected_dns, 1):
        new_status = "Closed"

        # Check if this DN has SI references
        has_si = frappe.db.sql("""
            SELECT 1 FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
            WHERE sii.delivery_note = %s LIMIT 1
        """, dn.name)
        has_si_flag = "Yes" if has_si else "No"

        if write_csv and writer:
            writer.writerow({
                "name": dn.name, "posting_date": dn.posting_date,
                "customer": dn.customer, "old_status": dn.status,
                "new_status": new_status, "per_billed": dn.per_billed,
                "per_returned": dn.per_returned, "grand_total": dn.grand_total,
                "has_si": has_si_flag,
                "action": "would_close" if dry_run else "closed"
            })

        if dry_run:
            if counter <= 10 or counter % 500 == 0:
                print(f"  [{counter}/{total}] Would close {dn.name} | "
                      f"{dn.posting_date} | {dn.customer} | has_si={has_si_flag}")
        else:
            try:
                frappe.db.sql("""
                    UPDATE `tabDelivery Note`
                    SET status = %s, modified = NOW(), modified_by = %s
                    WHERE name = %s
                """, (new_status, frappe.session.user, dn.name))
                updated += 1
            except Exception as e:
                errors.append((dn.name, str(e)))
                print(f"  ERROR closing {dn.name}: {e}")

            if updated and (updated % batch_size == 0):
                frappe.db.commit()
                print(f"  Committed batch up to {updated} updates...")

    if not dry_run:
        frappe.db.commit()
        print("Final commit done.")

    if csv_file:
        csv_file.close()

    # Verify
    remaining = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabDelivery Note`
        WHERE docstatus = 1 AND grand_total = 0 AND per_billed < 100
            AND status NOT IN ('Stopped', 'Closed')
    """)[0][0]

    print("\nDone. Summary:")
    print(f"  Total found: {total}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {len(errors)}")
    print(f"  Remaining zero-amount unbilled DNs: {remaining}")
    if csv_path:
        print(f"  Audit CSV: {csv_path}")

    return {
        "total_found": total,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "remaining": remaining,
        "audit_csv": csv_path,
    }


# bench execute entrypoint
def execute(dry_run=True, batch_size=500, limit=None, write_csv=True):
    dry_run = bool(dry_run)
    batch_size = int(batch_size) if batch_size else 500
    limit = int(limit) if limit else None
    write_csv = bool(write_csv)

    print(f"*** CLOSE ZERO-AMOUNT DELIVERY NOTES ***")
    print(f"*** {'DRY RUN' if dry_run else 'APPLYING CHANGES'} ***")
    print(f"*** Limit: {limit}, Batch Size: {batch_size}, Write CSV: {write_csv} ***")

    try:
        summary = close_zero_amount_delivery_notes(
            dry_run=dry_run, batch_size=batch_size,
            limit=limit, write_csv=write_csv
        )
    except Exception as e:
        print(f"\n*** ERROR: {e} ***")
        frappe.log_error(title="Close Zero Amount DNs Failed")
        frappe.db.rollback()
        return {"error": str(e)}

    if dry_run:
        print(f"\n*** DRY RUN COMPLETE. No changes were made. ***")
        frappe.db.rollback()
    else:
        print(f"\n*** COMPLETE. Changes committed. ***")

    return summary


# Dry Run (test with limit):
# bench --site rigplerpnext.localhost execute rohit_common.migration_scripts.close_zero_amount_dns.execute --kwargs "{'dry_run': True, 'limit': 20}"

# Dry Run (all):
# bench --site rigplerpnext.localhost execute rohit_common.migration_scripts.close_zero_amount_dns.execute --kwargs "{'dry_run': True}"

# Actual Run:
# bench --site rigplerpnext.localhost execute rohit_common.migration_scripts.close_zero_amount_dns.execute --kwargs "{'dry_run': False, 'batch_size': 500}"
