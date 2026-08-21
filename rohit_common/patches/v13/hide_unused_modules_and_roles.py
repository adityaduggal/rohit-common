# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import frappe

from rohit_common.utils.workspace_hide import reapply_hidden_workspaces

# All 9 ERPNext domains were deactivated manually via Domain Settings before
# this patch was written (near-zero real usage - turned on during initial
# 2017 setup and never trimmed). Domain Settings is pure site data, untouched
# by app updates, so no patch step is needed for that part.

# Loan Management and Quality Management modules have zero transactional data
# on this site and no Domain of their own, so Domain Settings can't hide them;
# their workspaces are hidden separately via reapply_hidden_workspaces().
# Stripping these roles from whichever users hold them is the one-time part
# of that cleanup - no one should need them if the modules are unused.
ROLES_TO_STRIP = ["Loan Manager", "Quality Manager"]


def execute():
	"""
	One-time cleanup of unused-module clutter for users. Hides the Loan
	Management/Quality Management workspaces (see
	rohit_common/utils/workspace_hide.py, also wired as an after_migrate hook
	since bench migrate re-syncs erpnext's standard workspace fixtures and
	would otherwise silently undo this) and removes their roles from users.
	"""
	reapply_hidden_workspaces()

	for role in ROLES_TO_STRIP:
		frappe.db.delete("Has Role", {"role": role, "parenttype": "User"})

	frappe.db.commit()
