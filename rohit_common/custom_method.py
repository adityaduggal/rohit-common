from erpnext.accounts.utils import create_payment_ledger_entry
import frappe

# from erpnext.accounts.payment_ledger import create_payment_ledger_entry

def backfill_payment_ledger(batch_size=500):
    """
    Rebuild Payment Ledger Entries (PLEs) from GL Entries for all submitted vouchers.
    """

    doctypes = ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]

    for doctype in doctypes:
        names = frappe.get_all(doctype, filters={"docstatus": 1}, pluck="name")
        total = len(names)
        print(f"\n>>> Processing {doctype}: {total} documents")

        created_count = 0
        error_count = 0

        for i in range(0, total, batch_size):
            batch = names[i:i+batch_size]
            for name in batch:
                try:
                    doc = frappe.get_doc(doctype, name)
                    if hasattr(doc, "get_gl_entries"):
                        gl_entries = doc.get_gl_entries()
                        if gl_entries:
                            create_payment_ledger_entry(gl_entries)
                            created_count += 1
                except Exception:
                    error_count += 1
                    frappe.log_error(
                        title=f"PLE Backfill Failed for {doctype} {name}",
                        message=frappe.get_traceback()
                    )
            frappe.db.commit()
            print(f"   ✔ Batch {(i//batch_size)+1}: processed {len(batch)} docs")

        print(f"✓ Done {doctype}: {created_count} created, {error_count} errors")