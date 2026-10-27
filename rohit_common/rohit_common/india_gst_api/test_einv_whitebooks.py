#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Tests for einv.py on WhiteBooks (issues #17, #19):
- generate_irn(): success, duplicate IRN (2150), rejection, and the optional
  e-Way Bill from the IRN. whitebooks_provider.einvoice_request is mocked.
- update_irn_details() on the real site: it saves irn, ack_no, ack_date and
  signed_qr_code and makes no QR PNG File.
- The Domestic Invoice print draws the QR from signed_qr_code.
- TestSandboxRoundTrip runs against the WhiteBooks sandbox only when the site is
  in the sandbox and site_config has whitebooks_sandbox_test_invoice (a
  submitted Sales Invoice that has no IRN yet).
- The item list: Items Synopsis rows with GST HSN Code descriptions, the item-wise
  switch, and a query count that does not grow with the rows.

Writes run in one transaction that is rolled back (SiteTestCase).

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_einv_whitebooks
"""
import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.india_gst_api import einv
from rohit_common.rohit_common.india_gst_api.common import use_gst_sandbox
from rohit_common.rohit_common.scheduled_tasks.test_auto_einvoice_tasks import SiteTestCase
from rohit_common.utils.query_guard import assert_max_queries

EINV = "rohit_common.rohit_common.india_gst_api.einv"
IRN_REPLY = {"Irn": "IRN123", "AckNo": 112010000000001, "AckDt": "2026-10-27 10:00:00",
             "SignedQRCode": "eyJhbGciOi.signed.qr"}


@patch(f"{EINV}.auto_ewb_needed", return_value=False)
@patch(f"{EINV}.update_irn_details")
@patch(f"{EINV}.gen_einv_json", return_value='{"Version": "1.1"}')
@patch(f"{EINV}.whitebooks_provider.einvoice_request")
class TestGenerateIrn(unittest.TestCase):
    def test_success_saves_the_irn(self, mock_request, _json, mock_update, _ewb):
        mock_request.return_value = {"status_cd": "Sucess", "data": IRN_REPLY}

        einv.generate_irn("Sales Invoice", "SINV-0001")

        mock_request.assert_called_once_with("POST", "GENERATE", body='{"Version": "1.1"}')
        mock_update.assert_called_once_with("Sales Invoice", "SINV-0001", IRN_REPLY)

    def test_duplicate_irn_fetches_the_existing_one(self, mock_request, _json, mock_update, _ewb):
        mock_request.return_value = {
            "status_cd": "0", "status_desc": '[{"ErrorCode":"2150","ErrorMessage":"Duplicate IRN"}]'}
        with patch(f"{EINV}.get_irn_by_doc", return_value=IRN_REPLY) as mock_lookup:
            einv.generate_irn("Sales Invoice", "SINV-0001")

        mock_lookup.assert_called_once_with("Sales Invoice", "SINV-0001")
        mock_update.assert_called_once_with("Sales Invoice", "SINV-0001", IRN_REPLY)

    def test_rejection_throws_with_the_codes(self, mock_request, _json, mock_update, _ewb):
        mock_request.return_value = {
            "status_cd": "0", "status_desc": '[{"ErrorCode":"2172","ErrorMessage":"Invalid Buyer GSTIN"}]'}

        with self.assertRaisesRegex(frappe.ValidationError, "2172"):
            einv.generate_irn("Sales Invoice", "SINV-0001")
        mock_update.assert_not_called()

    def test_ewb_failure_keeps_the_irn_and_logs(self, mock_request, _json, mock_update, mock_ewb_needed):
        mock_request.return_value = {"status_cd": "Sucess", "data": IRN_REPLY}
        mock_ewb_needed.return_value = True
        with patch(f"{EINV}.generate_ewb_by_irn", side_effect=frappe.ValidationError("No vehicle")), \
                patch(f"{EINV}.frappe.db") as mock_db, patch(f"{EINV}.frappe.log_error") as mock_log:
            einv.generate_irn("Sales Invoice", "SINV-0001")  # must not raise

        mock_update.assert_called_once()
        mock_db.rollback.assert_called_once()
        self.assertEqual(mock_log.call_args.args[1], einv.EWB_FAILURE_TITLE + "SINV-0001")


class TestSandboxSeller(unittest.TestCase):
    SELLER = {"Gstin": "06AAACR1567J1ZC", "LglNm": "Rohit Industries", "Stcd": "06", "Pin": 121003,
              "Loc": "Faridabad", "Addr1": "Plot 1"}

    @patch(f"{EINV}.get_default_gstin", return_value="29AAGCB1286Q000")
    def test_sample_gstin_gets_its_state_and_bengaluru_pincode(self, _gstin):
        seller = einv.sandbox_seller(self.SELLER)
        self.assertEqual((seller.Gstin, seller.Stcd, seller.Pin, seller.Loc),
                         ("29AAGCB1286Q000", "29", 560001, "Bengaluru"))
        self.assertEqual((seller.LglNm, seller.Addr1), ("Rohit Industries", "Plot 1"))
        self.assertEqual(self.SELLER["Gstin"], "06AAACR1567J1ZC")  # input not changed

    @patch(f"{EINV}.get_default_gstin", return_value="27AAGCB1286Q7ZY")
    def test_other_sandbox_gstin_gets_only_its_state(self, _gstin):
        seller = einv.sandbox_seller(self.SELLER)
        self.assertEqual((seller.Gstin, seller.Stcd, seller.Pin), ("27AAGCB1286Q7ZY", "27", 121003))


class TestUpdateIrnDetails(SiteTestCase):
    def get_invoice(self):
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1})
        if not name:
            self.skipTest("Needs one submitted Sales Invoice")
        return name

    def qr_files(self, name):
        return frappe.get_all("File", filters={"attached_to_doctype": "Sales Invoice",
            "attached_to_name": name, "attached_to_field": "qrcode_image", "creation": [">=", self.started]})

    def test_saves_irn_and_signed_qr_code_without_a_png(self):
        name = self.get_invoice()

        einv.update_irn_details("Sales Invoice", name, dict(IRN_REPLY, EwbNo=331001234567))

        saved = frappe.db.get_value("Sales Invoice", name,
            ["irn", "ack_no", "ack_date", "signed_qr_code", "ewaybill"], as_dict=1)
        self.assertEqual(saved, {"irn": "IRN123", "ack_no": "112010000000001",
            "ack_date": "2026-10-27 10:00:00", "signed_qr_code": "eyJhbGciOi.signed.qr",
            "ewaybill": "331001234567"})
        self.assertFalse(self.qr_files(name))

    def test_missing_qr_code_is_fetched_by_irn(self):
        name = self.get_invoice()
        reply = dict(IRN_REPLY, SignedQRCode=None)
        with patch(f"{EINV}.get_irn_details", return_value={"SignedQRCode": "from-getirn"}) as mock_get:
            einv.update_irn_details("Sales Invoice", name, reply)

        mock_get.assert_called_once_with("IRN123")
        self.assertEqual(frappe.db.get_value("Sales Invoice", name, "signed_qr_code"), "from-getirn")

    def test_no_qr_code_at_all_saves_nothing(self):
        name = self.get_invoice()
        before = frappe.db.get_value("Sales Invoice", name, "irn")
        with patch(f"{EINV}.get_irn_details", return_value={}):
            with self.assertRaises(frappe.ValidationError):
                einv.update_irn_details("Sales Invoice", name, dict(IRN_REPLY, SignedQRCode=None))
        self.assertEqual(frappe.db.get_value("Sales Invoice", name, "irn"), before)


class TestAutoEwbNeeded(SiteTestCase):
    def test_follows_the_checkbox_and_the_limit(self):
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "base_grand_total": [">", 1000]})
        if not name:
            self.skipTest("Needs a submitted Sales Invoice over 1000")
        frappe.db.set_value("Sales Invoice", name, "ewaybill", None, update_modified=False)
        settings = {"auto_generate_ewb_from_irn": 1, "eway_bill_limit": 1}
        frappe.db.set_value("Rohit Settings", "Rohit Settings", settings)
        self.assertTrue(einv.auto_ewb_needed("Sales Invoice", name))

        frappe.db.set_value("Rohit Settings", "Rohit Settings", "eway_bill_limit", 10 ** 12)
        self.assertFalse(einv.auto_ewb_needed("Sales Invoice", name))

        frappe.db.set_value("Rohit Settings", "Rohit Settings", settings)
        frappe.db.set_value("Sales Invoice", name, "ewaybill", "331001234567", update_modified=False)
        self.assertFalse(einv.auto_ewb_needed("Sales Invoice", name))

        frappe.db.set_value("Rohit Settings", "Rohit Settings", "auto_generate_ewb_from_irn", 0)
        frappe.db.set_value("Sales Invoice", name, "ewaybill", None, update_modified=False)
        self.assertFalse(einv.auto_ewb_needed("Sales Invoice", name))


class TestPrintDrawsQrFromSignedQrCode(SiteTestCase):
    def test_domestic_invoice_print_has_the_qr_image(self):
        if not frappe.db.exists("Print Format", "Domestic Invoice"):
            self.skipTest("Needs the Domestic Invoice print format")
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "is_return": 0})
        if not name:
            self.skipTest("Needs one submitted Sales Invoice")
        frappe.db.set_value("Sales Invoice", name, {"signed_qr_code": "eyJhbGciOi.signed.qr",
            "qrcode_image": None}, update_modified=False)

        html = frappe.get_print("Sales Invoice", name, print_format="Domestic Invoice")

        self.assertIn('src="data:image/png;base64,', html)


class TestSandboxRoundTrip(SiteTestCase):
    """Real WhiteBooks sandbox calls. The IRN stays on the sandbox, and the
    invoice changes are rolled back."""

    def setUp(self):
        super().setUp()
        self.name = frappe.conf.get("whitebooks_sandbox_test_invoice")
        if not (self.name and use_gst_sandbox()):
            self.skipTest("Set whitebooks_sandbox_test_invoice in site_config on a sandbox site")
        frappe.db.set_value("Sales Invoice", self.name, {"irn": None, "ack_no": None, "ack_date": None,
            "signed_qr_code": None}, update_modified=False)

    def test_generate_then_duplicate_both_save_the_signed_qr_code(self):
        with patch(f"{EINV}.auto_ewb_needed", return_value=False):
            einv.generate_irn("Sales Invoice", self.name)
            first = frappe.db.get_value("Sales Invoice", self.name, ["irn", "signed_qr_code"], as_dict=1)
            self.assertTrue(first.irn and first.signed_qr_code)

            frappe.db.set_value("Sales Invoice", self.name, {"irn": None, "signed_qr_code": None},
                                update_modified=False)
            einv.generate_irn("Sales Invoice", self.name)  # duplicate IRN path

        second = frappe.db.get_value("Sales Invoice", self.name, ["irn", "signed_qr_code"], as_dict=1)
        self.assertEqual(second.irn, first.irn)
        self.assertTrue(second.signed_qr_code)
        self.assertFalse(frappe.get_all("File", filters={"attached_to_name": self.name,
            "attached_to_field": "qrcode_image", "creation": [">=", self.started]}))


def sent_hsn_texts(rows):
    return {row.PrdDesc for row in rows}


class TestEinvoiceItems(SiteTestCase):
    """get_einv_item_details() lists the Items Synopsis with GST HSN Code descriptions,
    unless Rohit Settings asks for item-wise details. Real invoices, rolled back."""

    def invoices_with_synopsis(self, limit):
        """Submitted invoices whose synopsis has fewer rows than the item table"""
        names = [row[0] for row in frappe.db.sql("""SELECT si.name FROM `tabSales Invoice` si
            WHERE si.docstatus = 1 AND
            (SELECT COUNT(*) FROM `tabSales Invoice Item` i WHERE i.parent = si.name
                AND i.parentfield = 'items_synopsis') BETWEEN 1 AND
            (SELECT COUNT(*) FROM `tabSales Invoice Item` i WHERE i.parent = si.name
                AND i.parentfield = 'items') - 1
            ORDER BY si.posting_date DESC LIMIT %s""", (limit,))]
        if len(names) < limit:
            self.skipTest(f"Needs {limit} submitted Sales Invoices with an Items Synopsis")
        return names

    def set_itemwise(self, value):
        frappe.db.set_value("Rohit Settings", "Rohit Settings", "einvoice_itemwise_details", value)

    def test_synopsis_rows_with_hsn_descriptions_and_no_item_text(self):
        self.set_itemwise(0)
        name = self.invoices_with_synopsis(1)[0]
        doc = frappe.get_doc("Sales Invoice", name)

        rows, val_dt = einv.get_einv_item_details("Sales Invoice", name)

        self.assertEqual(len(rows), len(doc.items_synopsis))
        self.assertLess(len(rows), len(doc.items))
        for row, synopsis in zip(rows, doc.items_synopsis):
            hsn_desc = frappe.db.get_value("GST HSN Code", synopsis.gst_hsn_code, "description")
            self.assertEqual(row.PrdDesc, (hsn_desc or "")[:299])
            self.assertEqual(row.TotAmt, round(abs(synopsis.base_amount), 2))
        sent = " ".join(row.PrdDesc for row in rows)
        for item in doc.items:
            if item.description and item.description not in sent_hsn_texts(rows):
                self.assertNotIn(item.description, sent)
        self.assertAlmostEqual(sum(row.AssAmt for row in rows), val_dt.AssVal, delta=1)

    def test_checkbox_sends_the_item_table(self):
        self.set_itemwise(1)
        name = self.invoices_with_synopsis(1)[0]

        rows, _ = einv.get_einv_item_details("Sales Invoice", name)

        items = frappe.get_doc("Sales Invoice", name).items
        self.assertEqual([row.TotAmt for row in rows], [round(abs(item.base_amount), 2) for item in items])

    def test_stale_synopsis_throws_instead_of_sending_prices(self):
        self.set_itemwise(0)
        name = self.invoices_with_synopsis(1)[0]
        synopsis = frappe.db.get_value("Sales Invoice Item", {"parent": name, "parentfield": "items_synopsis"})
        frappe.db.set_value("Sales Invoice Item", synopsis, "base_amount", 1, update_modified=False)

        with self.assertRaises(frappe.ValidationError):
            einv.get_einv_item_details("Sales Invoice", name)

    def test_synopsis_builder_fetches_tariffs_in_one_query(self):
        from rohit_common.rohit_common.validations.sales_invoice import get_item_synopsis
        doc = frappe.get_doc("Sales Invoice", self.invoices_with_synopsis(1)[0])
        get_item_synopsis(doc)  # warm the meta cache; count only the per-call queries

        with assert_max_queries(1, test_case=self):
            it_list, _ = get_item_synopsis(doc)

        self.assertEqual(sum(row.base_amount for row in it_list), sum(item.base_amount for item in doc.items))

    def test_query_count_does_not_grow_with_rows(self):
        self.set_itemwise(1)
        counts = []
        for name in self.invoices_with_synopsis(2):
            einv.get_einv_item_details("Sales Invoice", name)  # warm the caches
            with assert_max_queries(100, test_case=self) as guard:
                einv.get_einv_item_details("Sales Invoice", name)
            counts.append((guard.count, len(frappe.get_doc("Sales Invoice", name).items)))
        (first, first_rows), (second, second_rows) = counts
        if first_rows == second_rows:
            self.skipTest("Needs two invoices with a different number of items")
        self.assertEqual(first, second, f"queries per run {counts} (count, items)")


if __name__ == "__main__":
    unittest.main()
