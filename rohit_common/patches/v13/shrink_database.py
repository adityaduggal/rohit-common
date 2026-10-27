import frappe

from rohit_common.rohit_common.scheduled_tasks import db_housekeeping

# Tables that the clean-up shrinks the most. InnoDB keeps the freed pages until a rebuild.
TABLES_TO_OPTIMIZE = ("tabStock Ledger Entry", "tabVersion", "tabAccess Log", "__global_search")


def execute():
    """
    One-time run of the weekly DB housekeeping, then OPTIMIZE to give the space back to the
    disk. OPTIMIZE rebuilds the table online, but needs free disk about the table's size.
    Why the stock_queue trim is safe up to ERPNext v16: see db_housekeeping.trim_stock_queue().
    """
    db_housekeeping.execute()
    for table in TABLES_TO_OPTIMIZE:
        print(f"Optimizing {table}")
        frappe.db.sql(f"OPTIMIZE TABLE `{table}`")
