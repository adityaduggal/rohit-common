#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Tests for auto_update_gstin_status against real Address rows on the site. Only the
WhiteBooks API call, commit and sleep are patched; every test rolls back.

Run: bench --site <sitename> run-tests --module rohit_common.rohit_common.scheduled_tasks.test_auto_update_gstin_status
"""
import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.scheduled_tasks import auto_update_gstin_status as task

MODULE = "rohit_common.rohit_common.scheduled_tasks.auto_update_gstin_status"


def active_reply(gstin):
    return {"status_cd": "1", "data": {"gstin": gstin, "sts": "Active", "lgnm": "", "tradeNam": ""}}


def get_rows(names):
    return frappe.db.sql("""SELECT name, gstin, gst_validation_date FROM `tabAddress`
        WHERE name IN %(names)s ORDER BY gstin, name""", {"names": names}, as_dict=1)


class TestUpdateAddresses(unittest.TestCase):
    def setUp(self):
        frappe.db.rollback()
        shared = frappe.db.sql("""SELECT gstin FROM `tabAddress`
            WHERE gstin IS NOT NULL AND gstin != 'NA' AND disabled=0 AND country='India'
            GROUP BY gstin HAVING COUNT(*) > 1 LIMIT 1""")
        other = frappe.db.sql("""SELECT name, gstin FROM `tabAddress`
            WHERE gstin IS NOT NULL AND gstin != 'NA' AND disabled=0 AND country='India'
            AND gstin != %s LIMIT 1""", (shared[0][0] if shared else "",))
        if not shared or not other:
            self.skipTest("Needs 2 Addresses sharing a GSTIN plus 1 other Address")
        self.shared_gstin = shared[0][0]
        self.shared_names = frappe.get_all("Address", pluck="name",
            filters={"gstin": self.shared_gstin, "disabled": 0}, limit=2)
        self.other_name, self.other_gstin = other[0]
        patcher_commit = patch.object(frappe.db, "commit")
        patcher_sleep = patch(f"{MODULE}.time.sleep")
        patcher_commit.start()
        patcher_sleep.start()
        self.addCleanup(patcher_commit.stop)
        self.addCleanup(patcher_sleep.stop)

    def tearDown(self):
        frappe.db.rollback()

    def test_shared_gstin_calls_api_once(self):
        rows = get_rows(self.shared_names)
        with patch(f"{MODULE}.search_gstin_whitebooks", side_effect=active_reply) as api:
            saved, failed = task.update_addresses(rows, auto_days=60)
        api.assert_called_once_with(self.shared_gstin)
        self.assertEqual((saved, failed), (2, 0))
        for name in self.shared_names:
            self.assertEqual(frappe.db.get_value("Address", name, "gst_status"), "Active")

    def test_api_failure_rolls_back_only_that_address(self):
        title_before = frappe.db.get_value("Address", self.other_name, "address_title")

        def api(gstin):
            if gstin == self.other_gstin:
                # A write made before the failure must not leak into the next commit
                frappe.db.set_value("Address", self.other_name, "address_title", "ROLL ME BACK",
                    update_modified=False)
                raise frappe.ValidationError("WhiteBooks timeout")
            return active_reply(gstin)

        rows = get_rows(self.shared_names + [self.other_name])
        errors_before = frappe.db.count("Error Log")
        with patch(f"{MODULE}.search_gstin_whitebooks", side_effect=api):
            saved, failed = task.update_addresses(rows, auto_days=60)
        self.assertEqual((saved, failed), (2, 1))
        self.assertEqual(frappe.db.get_value("Address", self.other_name, "address_title"), title_before)
        self.assertEqual(frappe.db.count("Error Log"), errors_before + 1)
        for name in self.shared_names:
            self.assertEqual(frappe.db.get_value("Address", name, "gst_status"), "Active")

    def test_unset_auto_days_skips_job(self):
        with patch(f"{MODULE}.is_gstin_validation_disabled", return_value=False), \
                patch(f"{MODULE}.frappe.get_value", return_value=None), \
                patch(f"{MODULE}.update_addresses") as update:
            task.execute()
        update.assert_not_called()
