import frappe
from frappe.utils.password import set_encrypted_password

from rohit_common.rohit_common.india_gst_api.common import SANDBOX_GSTIN

SETTINGS = "Rohit Settings"
# Charteredinfo, WhiteBooks-webhook and sandbox API user fields removed from Rohit
# Settings (issue #19). One GST API user pair now serves the site's environment.
REMOVED_FIELDS = ("tax_pro_asp_id", "tax_pro_password", "tax_pro_asp_secret", "api_link",
                  "sandbox_api_link", "access_token", "access_token_time",
                  "whitebooks_webhook_secret", "whitebooks_webhook_ip_allowlist",
                  "whitebooks_sandbox_api_username", "whitebooks_sandbox_api_password")
SUBMISSION_LOG = "E-Invoice Submission Log"


def execute():
    """
    e-Invoice and e-Way Bill move to WhiteBooks only (issues #17, #19). In v13,
    patches run before migrate syncs the DocTypes, so eway_bill_password is still
    a Data field here and its value is plain text in tabSingles.

    1. Moves eway_bill_password into __Auth, because it becomes a Password field.
    2. Deletes the stored values of the removed Rohit Settings fields.
    3. Deletes the E-Invoice Submission Log DocType (the bulk/webhook path).
    4. Fills an empty Sandbox GSTIN with the WhiteBooks sample sandbox GSTIN.

    Safe to run again: a masked password is skipped, the deletes find nothing,
    and a Sandbox GSTIN that is set is kept.
    """
    move_password_to_auth("eway_bill_password")
    if not get_single("whitebooks_sandbox_gstin"):
        set_single("whitebooks_sandbox_gstin", SANDBOX_GSTIN)
    frappe.db.delete("Singles", {"doctype": SETTINGS, "field": ["in", REMOVED_FIELDS]})
    frappe.db.sql("DELETE FROM `__Auth` WHERE doctype = %s AND fieldname IN %s",
                  (SETTINGS, REMOVED_FIELDS))
    frappe.db.delete("Global Search DocType", {"parent": SETTINGS, "document_type": SUBMISSION_LOG})
    if frappe.db.exists("DocType", SUBMISSION_LOG):
        frappe.delete_doc("DocType", SUBMISSION_LOG, force=1, ignore_permissions=True)
    frappe.db.commit()


def move_password_to_auth(fieldname):
    plain = get_single(fieldname)
    if not plain or set(plain) == {"*"}:
        return
    set_encrypted_password(SETTINGS, SETTINGS, plain, fieldname)
    set_single(fieldname, "*" * len(plain))


def get_single(field):
    """Raw tabSingles value. The field may not be in the DocType yet."""
    rows = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype = %s AND field = %s",
                         (SETTINGS, field))
    return rows[0][0] if rows else None


def set_single(field, value):
    frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype = %s AND field = %s", (SETTINGS, field))
    frappe.db.sql("INSERT INTO `tabSingles` (doctype, field, value) VALUES (%s, %s, %s)",
                  (SETTINGS, field, value))
