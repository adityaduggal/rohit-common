import frappe

def execute():
    """
    Truncates `po_no` values exceeding 140 characters (or standard field length)
    in `tabSales Invoice` to avoid MySQL DataError 1406 during DocType schema sync.
    """
    # Check if column exists before attempting update
    if frappe.db.has_column("Sales Invoice", "po_no"):
        frappe.db.sql("""
            UPDATE `tabSales Invoice`
            SET `po_no` = LEFT(`po_no`, 140)
            WHERE LENGTH(`po_no`) > 140
        """)
        frappe.db.commit()