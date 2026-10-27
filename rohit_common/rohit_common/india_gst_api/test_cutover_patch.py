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
    set_single = staticmethod(cutover.set_single)
    single = staticmethod(cutover.get_single)

    def test_fills_an_empty_sandbox_gstin_and_keeps_a_set_one(self):
        self.set_single("whitebooks_sandbox_gstin", "")
        cutover.execute()
        self.assertEqual(self.single("whitebooks_sandbox_gstin"), "29AAGCB1286Q000")

        self.set_single("whitebooks_sandbox_gstin", "27AAGCB1286Q7ZY")
        cutover.execute()
        self.assertEqual(self.single("whitebooks_sandbox_gstin"), "27AAGCB1286Q7ZY")

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
