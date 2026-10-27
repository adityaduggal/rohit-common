# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Ltd. and Contributors
# See license.txt
"""
Tests for GSTR2A RIGPL against real GSTR2A documents on the site. Only the GST Network download and
realtime messages are patched; every test rolls back.

Run: bench --site <sitename> run-tests --module rohit_common.rohit_common.doctype.gstr2a_rigpl.test_gstr2a_rigpl
"""
from __future__ import unicode_literals

import datetime
import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.doctype.gstr2a_rigpl import gstr2a_rigpl as gstr2a
from rohit_common.rohit_common.doctype.gstr2a_rigpl.gstr2a_rigpl import GSTR2ARIGPL
from rohit_common.utils.query_guard import assert_max_queries

MODULE = "rohit_common.rohit_common.doctype.gstr2a_rigpl.gstr2a_rigpl"


def largest_gstr2a():
    rows = frappe.db.sql("""SELECT parent FROM `tabGSTR2 Return Invoices` WHERE parenttype = 'GSTR2A RIGPL'
        GROUP BY parent ORDER BY COUNT(*) DESC LIMIT 1""")
    return rows[0][0] if rows else None


class TestWhitelisting(unittest.TestCase):
    def test_button_methods_are_whitelisted(self):
        for method in ("clear_table", "get_gstr2a_data", "analyse_data", "reset_matching", "get_gstr2b_data"):
            self.assertIn(getattr(GSTR2ARIGPL, method), frappe.whitelisted, method)


class TestParseGstr2a(unittest.TestCase):
    def test_one_row_per_invoice_item(self):
        entry = {"ctin": "07AAACR1567J1ZC", "cfs": "Y", "cfs3b": "N", "fldtr1": "11-Aug-25", "flprdr1": "072025",
                 "inv": [{"inum": "INV-1", "idt": "05-07-2025", "val": 236, "rchrg": "N", "inv_typ": "R",
                          "itms": [{"itm_det": {"txval": 100, "iamt": 18, "rt": 18}},
                                   {"itm_det": {"txval": 100, "iamt": 18, "rt": 18}}]}]}

        rows = gstr2a.update_gstin_data(frappe._dict(), entry)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["supplier_invoice_no"], "INV-1")
        self.assertEqual(rows[0]["supplier_invoice_date"], datetime.date(2025, 7, 5))
        self.assertEqual(rows[0]["filing_date_gstr1"], datetime.date(2025, 8, 11))
        self.assertEqual((rows[0]["filing_status_gstr1"], rows[0]["filing_status_gstr3b"]), (1, 0))
        self.assertEqual(rows[0]["invoice_type"], "R-Regular B2B Invoices")

    def test_entry_without_documents_gives_no_rows(self):
        self.assertEqual(gstr2a.update_gstin_data(frappe._dict(), {"ctin": "07AAACR1567J1ZC"}), [])


class RealDocTestCase(unittest.TestCase):
    def setUp(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")
        name = largest_gstr2a()
        if not name:
            self.skipTest("Needs a GSTR2A RIGPL document with invoices")
        self.doc = frappe.get_doc("GSTR2A RIGPL", name)

    def tearDown(self):
        frappe.db.rollback()


class TestLinkDocs(RealDocTestCase):
    def test_query_count_does_not_grow_with_rows(self):
        for d in self.doc.invoices:
            d.linked_document_type = d.linked_document_name = None
        with assert_max_queries(6, test_case=self):
            self.doc.link_docs()

    def test_newly_linked_rows_get_linked_values(self):
        for d in self.doc.invoices:
            d.linked_document_type = d.linked_document_name = None
            d.linked_doc_status = None
        self.doc.link_docs()
        linked = [d for d in self.doc.invoices if d.linked_document_name]
        if not linked:
            self.skipTest("No row links to a Purchase Invoice")
        for d in linked:
            self.assertIn(d.linked_doc_status, ("Draft", "Submitted"))
            pi = frappe.db.get_value("Purchase Invoice", d.linked_document_name, ["base_total", "supplier"], as_dict=1)
            self.assertEqual(d.linked_doc_taxable_value, pi.base_total)
            self.assertEqual(d.party, pi.supplier)


class TestGstr2b(RealDocTestCase):
    def reply(self, inv_no, ctin, supprd):
        return {"status_cd": "1", "data": {"gendt": "14-08-2025", "docdata": {
            "b2b": [{"ctin": ctin, "supprd": supprd, "inv": [{"inum": inv_no}]}]}}}

    def first_b2b_row(self):
        row = next((d for d in self.doc.invoices if d.note_type == "Invoice" and d.supplier_invoice_no), None)
        if not row:
            self.skipTest("No invoice row in the GSTR2A document")
        return row

    def test_marks_matched_rows_with_one_update(self):
        row = self.first_b2b_row()
        self.doc.gstr2b_gen_date = None
        with patch(f"{MODULE}.get_gstr2b", return_value=self.reply(row.supplier_invoice_no, row.party_gstin,
                                                                    self.doc.return_period)):
            # match (1) + parent date (1) + row update (1) + reload (parent and child table)
            with assert_max_queries(8, test_case=self):
                self.doc.get_gstr2b_data()

        self.assertEqual(frappe.db.get_value("GSTR2 Return Invoices", row.name, "gstr2b_date"), datetime.date(2025, 8, 14))
        self.assertEqual(self.doc.gstr2b_gen_date, datetime.date(2025, 8, 14))

    def test_unknown_document_changes_nothing(self):
        row = self.first_b2b_row()
        self.doc.gstr2b_gen_date = None
        before = frappe.db.get_value("GSTR2 Return Invoices", row.name, "gstr2b_date")
        with patch(f"{MODULE}.get_gstr2b", return_value=self.reply("NO-SUCH-INVOICE", row.party_gstin,
                                                                    self.doc.return_period)):
            with self.assertRaises(frappe.ValidationError):
                self.doc.get_gstr2b_data()

        self.assertEqual(frappe.db.get_value("GSTR2 Return Invoices", row.name, "gstr2b_date"), before)


class TestFetchJob(RealDocTestCase):
    def test_job_replaces_rows_and_saves(self):
        self.doc.disable_gst_update = 0
        self.doc.db_update()
        entry = {"ctin": self.doc.invoices[0].party_gstin, "cfs": "Y", "inv": [
            {"inum": "TEST-INV-1", "idt": "05-07-2025", "val": 118, "inv_typ": "R",
             "itms": [{"itm_det": {"txval": 100, "iamt": 18, "rt": 18}}]}]}
        with patch(f"{MODULE}.get_gstr2a", return_value={"b2b": [entry]}) as api, \
                patch.object(frappe, "publish_realtime") as notify:
            gstr2a.fetch_gstr2a_job(self.doc.name)

        self.assertEqual(api.call_args.kwargs["sections"]["b2b"], "b2b")
        self.assertEqual(notify.call_args.args[1]["indicator"], "green")
        saved = frappe.get_doc(self.doc.doctype, self.doc.name)
        self.assertEqual([d.supplier_invoice_no for d in saved.invoices], ["TEST-INV-1"])
