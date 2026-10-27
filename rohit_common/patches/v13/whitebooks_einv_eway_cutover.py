import frappe
from frappe.utils.password import set_encrypted_password

SETTINGS = "Rohit Settings"
# Charteredinfo and WhiteBooks-webhook fields removed from Rohit Settings (issue #19)
REMOVED_FIELDS = ("tax_pro_asp_id", "tax_pro_password", "tax_pro_asp_secret", "api_link",
                  "sandbox_api_link", "access_token", "access_token_time",
                  "whitebooks_webhook_secret", "whitebooks_webhook_ip_allowlist")
SUBMISSION_LOG = "E-Invoice Submission Log"


def execute():
    """
    e-Invoice and e-Way Bill move to WhiteBooks only (issues #17, #19). In v13,
    patches run before migrate syncs the DocTypes, so eway_bill_password is still
    a Data field here and its value is plain text in tabSingles.

    1. Moves eway_bill_password into __Auth, because it becomes a Password field.
    2. Deletes the stored values of the removed Rohit Settings fields.
    3. Deletes the E-Invoice Submission Log DocType (the bulk/webhook path).

    Safe to run again: a masked password is skipped, and the deletes find nothing.
    """
    move_password_to_auth("eway_bill_password")
    frappe.db.delete("Singles", {"doctype": SETTINGS, "field": ["in", REMOVED_FIELDS]})
    frappe.db.sql("DELETE FROM `__Auth` WHERE doctype = %s AND fieldname IN %s",
                  (SETTINGS, REMOVED_FIELDS))
    frappe.db.delete("Global Search DocType", {"parent": SETTINGS, "document_type": SUBMISSION_LOG})
    if frappe.db.exists("DocType", SUBMISSION_LOG):
        frappe.delete_doc("DocType", SUBMISSION_LOG, force=1, ignore_permissions=True)
    frappe.db.commit()


def move_password_to_auth(fieldname):
    rows = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype = %s AND field = %s",
                         (SETTINGS, fieldname))
    plain = rows[0][0] if rows else None
    if not plain or set(plain) == {"*"}:
        return
    set_encrypted_password(SETTINGS, SETTINGS, plain, fieldname)
    frappe.db.sql("UPDATE `tabSingles` SET value = %s WHERE doctype = %s AND field = %s",
                  ("*" * len(plain), SETTINGS, fieldname))
