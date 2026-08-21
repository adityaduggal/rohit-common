#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

app_name = "rohit_common"
app_title = "Rohit ERPNext Extensions (Common)"
app_publisher = "Rohit Industries Ltd."
app_description = "Rohit ERPNext Extensions (Common)"
app_icon = "icon-paper-clip"
app_color = "#007AFF"
app_email = "aditya@rigpl.com"
app_url = "https://github.com/adityaduggal/rohit_common"
app_version = "0.0.1"
app_license = "GPLv3"
hide_in_installer = True

# Fixtures help https://frappeframework.com/docs/v13/user/en/python-api/hooks#fixtures
fixtures = []

override_whitelisted_methods = {  # Below mentod would also take into account the search fields
    # mentioned in the Customize form view
    "frappe.core.doctype.file.file.get_files_by_search_text": "rohit_common.core.file.get_files_by_search_text"
}

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/rohit_common/css/rohit_common.css"
# app_include_js = ["/assets/rohit_common/js/myapp.min.js"]

# include js, css files in header of web template
# web_include_css = "/assets/rohit_common/css/rohit_common.css"
# web_include_js = "/assets/rohit_common/js/rohit_common.js"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#   "Role": "home_page"
# }

# Installation
# ------------

# before_install = "rohit_common.install.before_install"
# after_install = "rohit_common.install.after_install"
before_migrate = [
    "rohit_common.before_migrate_patches.execute"
]

# Re-applies restrict_to_domain on the Loan Management/Quality Management
# workspaces after every migrate, since bench migrate re-syncs erpnext's
# standard workspace fixtures and would otherwise silently reset it back to
# None. See rohit_common/utils/workspace_hide.py.
after_migrate = [
    "rohit_common.utils.workspace_hide.reapply_hidden_workspaces"
]

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "rohit_common.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# Transaction view-lock: doctypes here get has_permission +
# permission_query_conditions checks against Rohit Settings.locked_doctypes.
# The doctype list here MUST stay in sync with
# rohit_common.rohit_common.validations.transaction_lock.LOCKED_DOCTYPE_DATE_FIELDS
# (that dict is the source of truth for which doctypes have a known date
# field; adding a doctype to only one of the two does nothing).
_TRANSACTION_LOCK_MODULE = (
    "rohit_common.rohit_common.validations.transaction_lock"
)
permission_query_conditions = {
    "Sales Invoice": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_sales_invoice",
    "Purchase Invoice": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_purchase_invoice",
    "POS Invoice": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_pos_invoice",
    "Journal Entry": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_journal_entry",
    "Payment Entry": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_payment_entry",
    "GL Entry": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_gl_entry",
    "Delivery Note": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_delivery_note",
    "Purchase Receipt": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_purchase_receipt",
    "Stock Entry": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_stock_entry",
    "Quotation": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_quotation",
    "Sales Order": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_sales_order",
    "Purchase Order": f"{_TRANSACTION_LOCK_MODULE}.get_permission_query_conditions_purchase_order",
}
has_permission = {
     "File": "rohit_common.core.file.custom_file_permissions",
     "Sales Invoice": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Purchase Invoice": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "POS Invoice": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Journal Entry": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Payment Entry": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "GL Entry": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Delivery Note": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Purchase Receipt": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Stock Entry": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Quotation": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Sales Order": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
     "Purchase Order": f"{_TRANSACTION_LOCK_MODULE}.has_permission",
}

# Javascripts for Standard Documents to Override Forms Script
# -----------
doctype_js = {
    "Address": "public/js/address.js",
    "Asset": "public/js/asset.js",
    "Contact": "public/js/contact.js",
    "Sales Taxes and Charges Template": "public/js/stct.js",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Address": {
        "autoname": "rohit_common.rohit_common.validations.address.autoname",
        "validate": "rohit_common.rohit_common.validations.address.validate",
    },
    "Asset": {
        "validate": "rohit_common.rohit_common.validations.asset.validate",
        "autoname": "rohit_common.rohit_common.validations.asset.autoname",
    },
    "Asset Category": {
        "validate": "rohit_common.rohit_common.validations.asset_category.validate"
    },
    "Contact": {
        "autoname": "rohit_common.rohit_common.validations.contact.autoname",
        "validate": "rohit_common.rohit_common.validations.contact.validate",
    },
    "Customer": {
        "autoname": "rohit_common.rohit_common.validations.customer.autoname",
        "validate": "rohit_common.rohit_common.validations.customer.validate",
    },
    "DocShare": {
        "validate": "rohit_common.rohit_common.validations.docshare.validate",
        "on_trash": "rohit_common.rohit_common.validations.docshare.on_trash",
    },
    "File": {
        "before_insert": "rohit_common.core.file.before_insert",
        "validate": "rohit_common.core.file.validate",
        "on_trash": "rohit_common.core.file.on_trash",
    },
    "Payment Terms Template": {
        "validate": "rohit_common.rohit_common.validations.payment_terms_template.validate"
    },
    "Sales Invoice": {
        "validate": "rohit_common.rohit_common.validations.sales_invoice.validate",
        "on_update_after_submit": "rohit_common.rohit_common.validations.sales_invoice.on_update",
        "on_submit": "rohit_common.rohit_common.validations.sales_invoice.on_submit",
    },
    "Sales Taxes and Charges Template": {
        "validate": "rohit_common.rohit_common.validations.stc_template.validate"
    },
    "Purchase Invoice": {
        "validate": "rohit_common.rohit_common.validations.purchase_invoice.validate"
    },
    "Supplier": {
        "autoname": "rohit_common.rohit_common.validations.supplier.autoname",
        "validate": "rohit_common.rohit_common.validations.supplier.validate",
    },
    "User": {"validate": "rohit_common.rohit_common.validations.user.validate"},
    #   "*": {
    #       "on_update": "method",
    #       "on_cancel": "method",
    #       "on_trash": "method"
    #   }
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "10 2 * * *": [
            "rohit_common.rohit_common.scheduled_tasks.auto_update_gstin_status.enqueue_gstin_update"
            # Runs everyday at 2:10 AM
        ],
        # Runs every 15 mins below jobs
        "*/15 * * * *": [
            "rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.enq_inv_sub",
            "rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.enq_einv_create",
        ],
    },
    "all": [
        "rohit_common.rohit_common.scheduled_tasks.auto_refresh_gstin_auth_code.execute"
    ],
    "daily": [
        "rohit_common.rohit_common.scheduled_tasks.auto_update_from_erp.update_export_invoices",
        "rohit_common.rohit_common.scheduled_tasks.revoke_locked_doc_shares.execute",
    ],
    "hourly": [
        "rohit_common.rohit_common.scheduled_tasks.delete_unneeded_files.check_correct_folders",
        "rohit_common.utils.background_doc_processing.enqueue_bg",
    ],
    "weekly_long": [
        "rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.get_unposted_invoices",
        "rohit_common.rohit_common.scheduled_tasks.auto_delete_version.enqueue_deletion",
        "rohit_common.rohit_common.scheduled_tasks.delete_unneeded_files.execute",
    ],
    "monthly": ["rohit_common.rohit_common.scheduled_tasks.email_queue_delete.execute"],
}

# Testing
# -------

# before_tests = "rohit_common.install.before_tests"
