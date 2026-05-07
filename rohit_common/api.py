import frappe

@frappe.whitelist()
def get_accounts_settings_value(fieldname):
    # Ignore permissions to allow fetching this value from Accounts Settings directly
    return frappe.db.get_single_value("Accounts Settings", fieldname)
