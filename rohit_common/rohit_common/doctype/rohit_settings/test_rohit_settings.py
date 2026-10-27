# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Ltd. and Contributors
# See license.txt
from __future__ import unicode_literals

import unittest

import frappe


class TestRohitSettings(unittest.TestCase):
    def setUp(self):
        self.settings = frappe.get_single("Rohit Settings")
        self._original_locked_doctypes = [d.as_dict() for d in self.settings.locked_doctypes]

    def tearDown(self):
        self.settings = frappe.get_single("Rohit Settings")
        self.settings.set("locked_doctypes", self._original_locked_doctypes)
        self.settings.save(ignore_permissions=True)

    def test_valid_lock_condition_saves(self):
        self.settings.set("locked_doctypes", [])
        self.settings.append(
            "locked_doctypes",
            {
                "document_type": "Sales Invoice",
                "days_to_keep": 30,
                "doctype_conditions": "outstanding_amount != 0",
            },
        )
        self.settings.save(ignore_permissions=True)
        self.assertEqual(len(self.settings.locked_doctypes), 1)

    def test_and_chained_lock_condition_saves(self):
        self.settings.set("locked_doctypes", [])
        self.settings.append(
            "locked_doctypes",
            {
                "document_type": "Sales Invoice",
                "days_to_keep": 700,
                "doctype_conditions": "outstanding_amount != 0 AND docstatus = 1",
            },
        )
        self.settings.save(ignore_permissions=True)
        self.assertEqual(len(self.settings.locked_doctypes), 1)

    def test_missing_document_type_throws(self):
        self.settings.set("locked_doctypes", [])
        self.settings.append("locked_doctypes", {"days_to_keep": 30})
        with self.assertRaises(frappe.ValidationError):
            self.settings.save(ignore_permissions=True)

    def test_zero_days_to_keep_throws(self):
        self.settings.set("locked_doctypes", [])
        self.settings.append(
            "locked_doctypes", {"document_type": "Sales Invoice", "days_to_keep": 0}
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.save(ignore_permissions=True)

    def test_malformed_condition_throws(self):
        self.settings.set("locked_doctypes", [])
        self.settings.append(
            "locked_doctypes",
            {
                "document_type": "Sales Invoice",
                "days_to_keep": 30,
                "doctype_conditions": "DROP TABLE tabUser",
            },
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.save(ignore_permissions=True)

    def test_file_deletion_policy_condition_must_parse(self):
        """The file auto-deletion job put this text straight into SQL and failed with 1064."""
        from rohit_common.rohit_common.doctype.rohit_settings.rohit_settings import RohitSettings

        bad = frappe._dict(document_type="Sales Invoice",
            doctype_conditions="docstatus==1 AND outstanding_amount == 0")
        with self.assertRaises(frappe.ValidationError):
            RohitSettings.validate_doctype_conditions(bad, "Auto Deletion Policy for Files")

        good = frappe._dict(document_type="Sales Invoice",
            doctype_conditions="docstatus = 1 AND outstanding_amount = 0")
        RohitSettings.validate_doctype_conditions(good, "Auto Deletion Policy for Files")

    def test_version_days_to_keep_must_be_set(self):
        from rohit_common.rohit_common.doctype.rohit_settings.rohit_settings import RohitSettings

        bad = frappe._dict(auto_delete_from_version=[
            frappe._dict(document_type="Route History", days_to_keep=0)])
        with self.assertRaises(frappe.ValidationError):
            RohitSettings.validate_version_days(bad)

        good = frappe._dict(auto_delete_from_version=[
            frappe._dict(document_type="Route History", days_to_keep=30)])
        RohitSettings.validate_version_days(good)
