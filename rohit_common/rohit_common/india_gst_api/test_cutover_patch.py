#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Site test for patches/v13/whitebooks_einv_eway_cutover.py (issue #19): the
plain eway_bill_password moves into __Auth, a second run changes nothing, and
the removed Rohit Settings fields lose their stored values. Rolled back.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_cutover_patch
"""
import frappe
from frappe.utils.password import get_decrypted_password

from rohit_common.patches.v13 import whitebooks_einv_eway_cutover as cutover
from rohit_common.rohit_common.scheduled_tasks.test_auto_einvoice_tasks import SiteTestCase

SETTINGS = "Rohit Settings"


class TestCutoverPatch(SiteTestCase):
    def set_single(self, field, value):
        frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype = %s AND field = %s", (SETTINGS, field))
        frappe.db.sql("INSERT INTO `tabSingles` (doctype, field, value) VALUES (%s, %s, %s)",
                      (SETTINGS, field, value))

    def single(self, field):
        rows = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype = %s AND field = %s",
                             (SETTINGS, field))
        return rows[0][0] if rows else None

    def test_moves_the_plain_password_once(self):
        self.set_single("eway_bill_password", "plain-pass")

        cutover.execute()
        cutover.execute()

        self.assertEqual(get_decrypted_password(SETTINGS, SETTINGS, "eway_bill_password"), "plain-pass")
        self.assertEqual(self.single("eway_bill_password"), "*" * len("plain-pass"))

    def test_deletes_the_removed_fields(self):
        for field in ("tax_pro_asp_id", "api_link", "access_token"):
            self.set_single(field, "old")

        cutover.execute()

        self.assertEqual([self.single(f) for f in ("tax_pro_asp_id", "api_link", "access_token")],
                         [None, None, None])
        self.assertFalse(frappe.db.exists("DocType", cutover.SUBMISSION_LOG))
