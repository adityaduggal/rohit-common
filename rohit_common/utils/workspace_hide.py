# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import frappe

HIDDEN_DOMAIN = "Hidden"
HIDDEN_WORKSPACES = ["Loans", "Quality"]


def ensure_hidden_domain():
	"""
	Creates a Domain record that is never added to Domain Settings' active_domains
	list. Workspace.restrict_to_domain can point to it to hide a workspace from
	every user's sidebar - frappe.desk.desktop.get_desk_sidebar_items() filters
	on `restrict_to_domain in frappe.get_active_domains()` - reusing Frappe's own
	domain-gating mechanism instead of writing new hiding logic.
	"""
	if not frappe.db.exists("Domain", HIDDEN_DOMAIN):
		frappe.get_doc({"doctype": "Domain", "domain": HIDDEN_DOMAIN}).insert(ignore_permissions=True)


def reapply_hidden_workspaces():
	"""
	erpnext ships Loan Management's and Quality Management's Workspace docs
	("Loans", "Quality") as standard records with restrict_to_domain unset -
	neither module has a Domain of its own (unlike Agriculture, Healthcare,
	etc.), so Domain Settings can't hide them. bench migrate re-syncs standard
	workspace fixtures and would silently reset restrict_to_domain back to None,
	undoing a one-time edit - so this is wired as an after_migrate hook to keep
	the hide in place across updates.
	"""
	ensure_hidden_domain()
	for workspace_name in HIDDEN_WORKSPACES:
		if frappe.db.exists("Workspace", workspace_name):
			frappe.db.set_value(
				"Workspace", workspace_name, "restrict_to_domain", HIDDEN_DOMAIN,
				update_modified=False,
			)
	frappe.db.commit()
