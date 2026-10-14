# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe

def execute():
    frappe.reload_doc("Custom", "DocType", "Client Script")
    frappe.reload_doc("Accounts", "DocType", "POS Invoice")
    frappe.reload_doc("Accounts", "DocType", "POS Invoice Item")
    remove_accounts_dashboard_shortcut()


ERPNEXT_DELETE_ACCOUNTS_DASHBOARD = "execute:frappe.delete_doc_if_exists('Dashboard', 'Accounts')"


def remove_accounts_dashboard_shortcut():
    # ERPNext v13 patch deletes the v12 Dashboard "Accounts", but the v12 Accounting desk
    # page still has a shortcut to it, which blocks the delete with LinkExistsError.
    # Run only until that patch is logged: v13 re-creates a standard "Accounts" dashboard
    # and its shortcut, which must survive later migrates.
    if frappe.db.exists("Patch Log", {"patch": ERPNEXT_DELETE_ACCOUNTS_DASHBOARD}):
        return
    if not frappe.db.exists("Dashboard", "Accounts"):
        return
    # Before the frappe rename patch runs the doctype is still "Desk Shortcut".
    # Check the DocType record, not db.table_exists, which spans every schema on the server.
    for shortcut_doctype in ("Workspace Shortcut", "Desk Shortcut"):
        if frappe.db.exists("DocType", shortcut_doctype):
            frappe.db.delete(shortcut_doctype, {"type": "Dashboard", "link_to": "Accounts"})
