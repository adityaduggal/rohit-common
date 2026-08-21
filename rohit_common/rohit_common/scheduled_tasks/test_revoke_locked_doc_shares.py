# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import unittest

import frappe
from frappe.utils import add_days, nowdate

from rohit_common.rohit_common.scheduled_tasks.revoke_locked_doc_shares import execute

TEST_ROLE = "Test Revoke Shares Bypass Role"
BYPASS_USER = "test-revoke-shares-bypass@example.com"
PLAIN_USER = "test-revoke-shares-plain@example.com"


class TestRevokeLockedDocShares(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Role", TEST_ROLE):
            frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert(
                ignore_permissions=True
            )
        for email in (BYPASS_USER, PLAIN_USER):
            if not frappe.db.exists("User", email):
                frappe.get_doc(
                    {
                        "doctype": "User",
                        "email": email,
                        "first_name": email.split("@")[0],
                        "send_welcome_email": 0,
                        "roles": [{"role": TEST_ROLE}] if email == BYPASS_USER else [],
                    }
                ).insert(ignore_permissions=True)

    def setUp(self):
        self.invoice_name = frappe.db.get_value("Sales Invoice", {}, "name")
        if not self.invoice_name:
            self.skipTest("No Sales Invoice exists on this site to test against")

        self.settings = frappe.get_single("Rohit Settings")
        self._original_locked_doctypes = [d.as_dict() for d in self.settings.locked_doctypes]
        self._original_bypass_role = self.settings.transaction_lock_bypass_role
        self.settings.set("locked_doctypes", [])
        self.settings.transaction_lock_bypass_role = TEST_ROLE
        self.settings.append(
            "locked_doctypes", {"document_type": "Sales Invoice", "days_to_keep": 30}
        )
        self.settings.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Rohit Settings")

        frappe.db.set_value("Sales Invoice", self.invoice_name, "posting_date", add_days(nowdate(), -60))
        frappe.db.delete(
            "DocShare", {"share_doctype": "Sales Invoice", "share_name": self.invoice_name}
        )
        for user in (BYPASS_USER, PLAIN_USER):
            frappe.get_doc(
                {
                    "doctype": "DocShare",
                    "share_doctype": "Sales Invoice",
                    "share_name": self.invoice_name,
                    "user": user,
                    "read": 1,
                }
            ).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.db.delete(
            "DocShare", {"share_doctype": "Sales Invoice", "share_name": self.invoice_name}
        )
        self.settings = frappe.get_single("Rohit Settings")
        self.settings.set("locked_doctypes", self._original_locked_doctypes)
        self.settings.transaction_lock_bypass_role = self._original_bypass_role
        self.settings.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Rohit Settings")

    def test_revokes_share_for_plain_user_on_locked_doc(self):
        execute()
        self.assertFalse(
            frappe.db.exists(
                "DocShare",
                {
                    "share_doctype": "Sales Invoice",
                    "share_name": self.invoice_name,
                    "user": PLAIN_USER,
                },
            )
        )

    def test_keeps_share_for_bypass_role_user(self):
        execute()
        self.assertTrue(
            frappe.db.exists(
                "DocShare",
                {
                    "share_doctype": "Sales Invoice",
                    "share_name": self.invoice_name,
                    "user": BYPASS_USER,
                },
            )
        )

    def test_keeps_share_when_doc_not_locked(self):
        frappe.db.set_value("Sales Invoice", self.invoice_name, "posting_date", nowdate())
        execute()
        self.assertTrue(
            frappe.db.exists(
                "DocShare",
                {
                    "share_doctype": "Sales Invoice",
                    "share_name": self.invoice_name,
                    "user": PLAIN_USER,
                },
            )
        )
