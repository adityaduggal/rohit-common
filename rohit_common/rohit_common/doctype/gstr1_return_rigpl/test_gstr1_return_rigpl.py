# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Ltd. and Contributors
# See license.txt
"""
Tests for GSTR1 Return RIGPL against real Sales Invoices on the site. Only the GST Network download
(get_gstr1) and realtime messages are patched; every test rolls back.

Run: bench --site <sitename> run-tests --module rohit_common.rohit_common.doctype.gstr1_return_rigpl.test_gstr1_return_rigpl
"""
from __future__ import unicode_literals

import datetime
import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.doctype.gstr1_return_rigpl import gstr1_return_rigpl as gstr1
from rohit_common.rohit_common.doctype.gstr1_return_rigpl.gstr1_return_rigpl import GSTR1ReturnRIGPL
from rohit_common.rohit_common.india_gst_api.gst_public_api import get_arn_status
from rohit_common.utils.accounts_utils import build_hsn_summary
from rohit_common.utils.query_guard import assert_max_queries

MODULE = "rohit_common.rohit_common.doctype.gstr1_return_rigpl.gstr1_return_rigpl"


def busiest_b2b_period():
    """(company address, MMYYYY) of the period with the most B2B Sales Invoices."""
    rows = frappe.db.sql("""SELECT ad.name AS address, DATE_FORMAT(si.posting_date, '%m%Y') AS period
        FROM `tabSales Invoice` si JOIN `tabAddress` ad ON ad.gstin = si.company_gstin AND ad.is_your_company_address = 1
        WHERE si.docstatus = 1 AND si.billing_address_gstin != 'NA' AND si.posting_date >= '2021-04-01'
        AND si.posting_date < DATE_FORMAT(CURDATE(), '%Y-%m-01')
        GROUP BY ad.name, period ORDER BY COUNT(*) DESC LIMIT 1""", as_dict=1)
    return rows[0] if rows else None


def gst_b2b_entry(rows, chksum_prefix="CHK"):
    """The GST Network B2B entry that matches the given local rows of one receiver GSTIN."""
    return {"ctin": rows[0].receiver_gstin, "inv": [{
        "inum": d.invoice_number, "idt": d.invoice_date.strftime("%d-%m-%Y"), "val": d.total_invoice_value,
        "flag": "U", "updby": "S", "chksum": f"{chksum_prefix}{d.idx}"} for d in rows]}


class TestWhitelisting(unittest.TestCase):
    def test_button_methods_are_whitelisted(self):
        for method in ("get_details", "get_gstr1_details", "clear_all_tables"):
            self.assertIn(getattr(GSTR1ReturnRIGPL, method), frappe.whitelisted, method)


class TestArnStatus(unittest.TestCase):
    def test_reads_whitebooks_data_envelope(self):
        reply = {"status_cd": "1", "data": {"EFiledlist": [
            {"rtntype": "GSTR3B", "ret_prd": "072025", "arn": "WRONG"},
            {"rtntype": "GSTR1", "ret_prd": "072025", "arn": "AA0607250012345", "status": "Filed",
             "dof": "05-08-2025", "mof": "ONLINE"}]}}

        arn, status, dof, mof = get_arn_status(reply, "GSTR1", "072025")

        self.assertEqual((arn, status, mof), ("AA0607250012345", "Filed", "ONLINE"))
        self.assertEqual(dof, datetime.date(2025, 8, 5))

    def test_failed_reply_throws(self):
        with self.assertRaises(frappe.ValidationError):
            get_arn_status({"status_cd": "0", "status_desc": "Invalid GSTIN"}, "GSTR1", "072025")


class TestBuildHsnSummary(unittest.TestCase):
    def test_groups_by_hsn_and_uom_and_allocates_tax_per_row(self):
        items = [
            frappe._dict(parent="SI-1", gst_hsn_code="8207", stock_uom="Nos", qty=2, base_net_amount=100.0),
            frappe._dict(parent="SI-1", gst_hsn_code="7204", stock_uom="Kg", qty=5, base_net_amount=200.0),
            frappe._dict(parent="SI-2", gst_hsn_code="8207", stock_uom="Nos", qty=1, base_net_amount=50.0),
            frappe._dict(parent="SI-2", gst_hsn_code="8207", stock_uom="Kg", qty=3, base_net_amount=30.0),
        ]
        net_total = {"SI-1": 300.0, "SI-2": 80.0}
        # (tax_rate, sgst, cgst, igst, cess)
        taxes = {"SI-1": (18, 0, 0, 54.0, 0), "SI-2": (18, 7.2, 7.2, 0, 0)}

        summary = build_hsn_summary(items, net_total, taxes)

        self.assertEqual([(s.hsn, s.uom) for s in summary], [("7204", "Kg"), ("8207", "Nos"), ("8207", "Kg")])
        nos = summary[1]
        self.assertEqual(nos.total_quantity, 3)
        self.assertEqual(nos.total_taxable_value, 150.0)
        self.assertEqual(nos.igst, 18.0)
        self.assertEqual((nos.sgst, nos.cgst), (4.5, 4.5))
        self.assertEqual(nos.total_value, 177.0)

    def test_zero_net_total_gives_zero_tax(self):
        items = [frappe._dict(parent="SI-1", gst_hsn_code="8207", stock_uom="Nos", qty=1, base_net_amount=0.0)]
        summary = build_hsn_summary(items, {"SI-1": 0}, {"SI-1": (18, 0, 0, 10.0, 0)})
        self.assertEqual((summary[0].igst, summary[0].total_value), (0, 0.0))


class RealPeriodTestCase(unittest.TestCase):
    def setUp(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")
        period = busiest_b2b_period()
        if not period:
            self.skipTest("Needs submitted B2B Sales Invoices of a company address")
        frappe.db.delete("GSTR1 Return RIGPL", {"address": period.address, "return_period": period.period})
        self.doc = frappe.get_doc({"doctype": "GSTR1 Return RIGPL", "address": period.address,
                                   "gstin": frappe.db.get_value("Address", period.address, "gstin"),
                                   "return_period": period.period}).insert()

    def tearDown(self):
        frappe.db.rollback()


class TestGenerateGstr1(RealPeriodTestCase):
    def test_query_count_does_not_grow_with_rows(self):
        # The first run loads DocType meta and caches from the DB (about 90 queries in a fresh process).
        # Count the second run, which is what a warm worker does.
        self.doc.generate_gstr1()
        self.doc.clear_all_tables()
        with assert_max_queries(15, test_case=self):
            self.doc.generate_gstr1()
        self.assertGreater(len(self.doc.b2b_invoices), 1)
        self.doc.filing_status = "Filed"
        # Warm the meta of the doctypes these two read (Journal Entry Account, Dynamic Link, Address, items).
        self.doc.validate_si_tables()
        self.doc.generate_hsn_summary()
        with assert_max_queries(8, test_case=self):
            self.doc.validate_si_tables()
        with assert_max_queries(8, test_case=self):
            self.doc.generate_hsn_summary()
        self.assertTrue(self.doc.hsn_summary)

    def test_rows_carry_invoice_values(self):
        self.doc.generate_gstr1()
        row = self.doc.b2b_invoices[0]
        si = frappe.get_doc("Sales Invoice", row.document_number)
        self.assertEqual(row.total_invoice_value, si.base_grand_total)
        self.assertEqual(row.taxable_value, si.base_net_total)
        self.assertEqual(row.receiver_gstin, si.billing_address_gstin)

    def test_validate_keeps_unsaved_rows(self):
        # Before the fix, validate() reloaded the doc once it was fully validated and lost the new rows.
        self.doc.get_details()
        self.doc.reload()
        self.assertTrue(self.doc.b2b_invoices)


class TestReconcile(RealPeriodTestCase):
    def setUp(self):
        super().setUp()
        self.doc.get_details()
        self.doc.reload()
        gstin = self.doc.b2b_invoices[0].receiver_gstin
        # Keep one receiver GSTIN so the reconciliation covers a single, fully known B2B entry.
        for tbl in gstr1.SI_TABLES:
            self.doc.set(tbl, [d for d in self.doc.get(tbl) if tbl == "b2b_invoices" and d.receiver_gstin == gstin])
        self.doc.filing_status = "Filed"
        self.doc.arn_number = "TEST-ARN"
        self.doc.save()
        self.rows = self.doc.b2b_invoices

    def test_matching_b2b_sets_status_and_checksum(self):
        errors = self.doc.apply_gst_network_data({"b2b": [gst_b2b_entry(self.rows)]})

        self.assertEqual(errors, [])
        for d in self.rows:
            self.assertEqual((d.invoice_status, d.uploaded_by, d.invoice_checksum), ("U-Uploaded", "S-Supplier", f"CHK{d.idx}"))

    def test_any_mismatch_changes_no_row(self):
        entry = gst_b2b_entry(self.rows)
        entry["inv"][0]["val"] = self.rows[0].total_invoice_value + 10

        errors = self.doc.apply_gst_network_data({"b2b": [entry], "at": [{"pos": "07"}]})

        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("Advances Tax" in e for e in errors))
        self.assertTrue(all(not d.invoice_checksum for d in self.rows))

    def test_gst_data_for_empty_table_is_an_error(self):
        errors = self.doc.apply_gst_network_data({"b2b": [gst_b2b_entry(self.rows)], "exp": [{"inv": []}]})
        self.assertEqual(len(errors), 1, errors)

    def unregistered_address(self):
        address = frappe.db.sql("""SELECT a.name, s.state_code_numeric FROM `tabAddress` a
            JOIN `tabState` s ON s.name = a.state_rigpl WHERE a.gstin = 'NA' LIMIT 1""", as_dict=1)
        if not address:
            self.skipTest("Needs an unregistered Address with a State")
        return address[0].name, str(address[0].state_code_numeric).zfill(2)

    def add_b2cs_rows(self, table, address):
        self.doc.set("b2b_invoices", [])
        for idx, (taxable, igst) in enumerate(((100.0, 18.0), (50.0, 6.0)), start=1):
            self.doc.append(table, {"name": f"test-{table}-{idx}", "receiver_address": address,
                                    "taxable_value": taxable, "igst": igst, "sgst": 0, "cgst": 0, "cess": 0})

    def test_b2cs_compares_state_totals_across_rates(self):
        address, pos = self.unregistered_address()
        self.add_b2cs_rows("b2c_invoices", address)
        gst = [{"sply_ty": "INTER", "pos": pos, "rt": 18, "txval": 100, "iamt": 18, "flag": "U", "chksum": "B2CS"},
               {"sply_ty": "INTER", "pos": pos, "rt": 12, "txval": 50, "iamt": 6, "flag": "U", "chksum": "B2CS2"}]

        errors = self.doc.apply_gst_network_data({"b2cs": gst})

        self.assertEqual(errors, [])
        self.assertTrue(all(d.invoice_checksum == "B2CS" for d in self.doc.b2c_invoices))

    def test_b2cs_allows_rounding_up_to_one_rupee(self):
        # The old int() comparison failed 149.99 against 150.
        address, pos = self.unregistered_address()
        self.add_b2cs_rows("b2c_invoices", address)
        self.doc.b2c_invoices[0].taxable_value = 99.99
        rounded = [{"sply_ty": "INTER", "pos": pos, "txval": 150, "iamt": 24, "flag": "U", "chksum": "R"}]
        self.assertEqual(self.doc.apply_gst_network_data({"b2cs": rounded}), [])

        off = [{"sply_ty": "INTER", "pos": pos, "txval": 152, "iamt": 24, "flag": "U", "chksum": "R"}]
        errors = self.doc.apply_gst_network_data({"b2cs": off})
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("Taxable", errors[0])

    def test_b2csa_sums_amounts_per_rate(self):
        address, pos = self.unregistered_address()
        self.add_b2cs_rows("b2csa_invoices", address)
        gst = [{"omon": "042025", "sply_ty": "INTER", "pos": pos, "flag": "U", "chksum": "B2CSA",
                "itms": [{"rt": 18, "txval": 100, "iamt": 18}, {"rt": 12, "txval": 50, "iamt": 6}]}]

        errors = self.doc.apply_gst_network_data({"b2csa": gst})

        self.assertEqual(errors, [])
        self.assertTrue(all(d.invoice_checksum == "B2CSA" for d in self.doc.b2csa_invoices))

    def test_amendments_with_empty_table_are_an_error(self):
        errors = self.doc.apply_gst_network_data({"b2b": [gst_b2b_entry(self.rows)],
                                                  "b2ba": [{"ctin": "07AAACR1567J1ZC", "inv": []}]})
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("B2B Amendments", errors[0])

    def test_get_details_keeps_amendment_rows(self):
        self.doc.append("b2ba_invoices", {"document_type": "Sales Invoice", "invoice_number": "MANUAL-1",
                                          "receiver_address": self.rows[0].receiver_address})
        self.doc.get_details()
        self.assertEqual([d.invoice_number for d in self.doc.b2ba_invoices], ["MANUAL-1"])

    def test_job_saves_once_when_everything_matches(self):
        reply = {"b2b": [gst_b2b_entry(self.rows)]}
        with patch(f"{MODULE}.get_gstr1", return_value=reply) as api, \
                patch.object(frappe, "publish_realtime") as notify:
            gstr1.reconcile_gstr1_job(self.doc.name)

        api.assert_called_once()
        self.assertEqual(notify.call_args.args[1]["indicator"], "green")
        saved = frappe.get_doc(self.doc.doctype, self.doc.name)
        self.assertEqual(saved.fully_validated, 1)
        self.assertTrue(all(d.invoice_checksum for d in saved.b2b_invoices))

    def test_job_with_mismatch_keeps_reply_and_changes_nothing(self):
        entry = gst_b2b_entry(self.rows)
        entry["inv"][0]["val"] = self.rows[0].total_invoice_value + 10
        # The job rolls back on a mismatch; keep this test's fixture by not really rolling back.
        with patch(f"{MODULE}.get_gstr1", return_value={"b2b": [entry]}), \
                patch.object(frappe, "publish_realtime") as notify, \
                patch.object(frappe.db, "rollback") as rollback:
            gstr1.reconcile_gstr1_job(self.doc.name)

        rollback.assert_called_once()
        self.assertEqual(notify.call_args.args[1]["indicator"], "red")
        saved = frappe.get_doc(self.doc.doctype, self.doc.name)
        self.assertIn('"b2b"', saved.json_reply)
        self.assertTrue(all(not d.invoice_checksum for d in saved.b2b_invoices))
