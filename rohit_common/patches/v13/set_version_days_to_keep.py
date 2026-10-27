import frappe
from frappe.utils import cint

from rohit_common.rohit_common.scheduled_tasks.auto_delete_version import DEFAULT_DAYS_TO_KEEP


def execute():
    """
    Auto Delete from Version rows without Days to Keep used to mean 1 day. Rohit Settings now
    needs it to save, so fill it with Max Days to Keep Version, which the job also falls back to.
    """
    max_days = cint(frappe.db.get_single_value("Rohit Settings", "max_days_to_keep_version"))
    frappe.db.sql("""UPDATE `tabGlobal Search DocType` SET days_to_keep = %(days)s
        WHERE parent = 'Rohit Settings' AND parentfield = 'auto_delete_from_version'
        AND IFNULL(days_to_keep, 0) < 1""", {"days": max_days or DEFAULT_DAYS_TO_KEEP})
