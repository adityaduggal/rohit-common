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
- The HSN description regression on the payload builder.

Writes run in one transaction that is rolled back (SiteTestCase).

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_einv_whitebooks
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.india_gst_api import einv
from rohit_common.rohit_common.india_gst_api.common import use_gst_sandbox
from rohit_common.rohit_common.scheduled_tasks.test_auto_einvoice_tasks import SiteTestCase

EINV = "rohit_common.rohit_common.india_gst_api.einv"
IRN_REPLY = {"Irn": "IRN123", "AckNo": 112010000000001, "AckDt": "2026-10-27 10:00:00",
             "SignedQRCode": "eyJhbGciOi.signed.qr"}


class _FakeFrappeDict(dict):
    """Minimal stand-in for frappe._dict — a real dict subclass with
    attribute access, so each frappe._dict({}) call in the code under test
    produces a genuinely independent instance. Using a bare MagicMock for
    frappe._dict is a footgun here: mock_frappe._dict({}) returns the SAME
    MagicMock (its .return_value) on every call, so multiple loop
    iterations in get_einv_item_details() would silently write into one
    shared object instead of one per line item."""

    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value


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


def _fake_hsn_doc(description, is_service=0):
    return SimpleNamespace(description=description, is_service=is_service)


def _fake_sales_invoice_with_items():
    item = SimpleNamespace(
        idx=1,
        description="SuperWidget X200 Cartridge — proprietary product name",
        gst_hsn_code="8443",
        qty=2,
        uom="Nos",
        base_rate=100.0,
        base_amount=200.0,
    )
    return SimpleNamespace(items=[item])


class TestDescriptionSubstitutionRegression(unittest.TestCase):
    """Guards the privacy behavior flagged in Premise 3: get_einv_item_details()
    must send the HSN code's generic description, never the item's real
    description, and must NOT combine/aggregate line items — one entry per
    row, full itemwise price/tax detail intact. See the design doc's
    corrected Premise 3 (2026-08-22)."""

    @patch("rohit_common.rohit_common.india_gst_api.einv.get_gst_based_uom")
    @patch("rohit_common.rohit_common.india_gst_api.einv.get_taxes_type")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_sends_hsn_description_not_item_description(
        self, mock_frappe, mock_get_taxes_type, mock_get_uom
    ):
        mock_frappe._dict = _FakeFrappeDict
        mock_frappe.get_doc.side_effect = lambda doctype, name: (
            _fake_sales_invoice_with_items()
            if doctype == "Sales Invoice"
            else _fake_hsn_doc("Machinery for printing — generic HSN description")
        )
        mock_get_taxes_type.return_value = {
            "tax_val": 200, "tot_val": 236, "cgst_amt": 18, "sgst_amt": 18,
            "igst_amt": 0, "discount_amt": 0, "other_amt": 0, "gst_per": 18,
            "cgst_per": 9, "sgst_per": 9, "igst_per": 0,
        }
        mock_get_uom.return_value = "NOS"

        itm_lst, val_dt = einv.get_einv_item_details("Sales Invoice", "SINV-0001")

        self.assertEqual(len(itm_lst), 1)
        self.assertEqual(itm_lst[0].PrdDesc, "Machinery for printing — generic HSN description")
        self.assertNotIn("SuperWidget", itm_lst[0].PrdDesc)
        # Not aggregated: itemwise price/tax fields are still populated per row.
        self.assertEqual(itm_lst[0].UnitPrice, 100.0)
        self.assertEqual(itm_lst[0].TotAmt, 200.0)
        self.assertEqual(itm_lst[0].GstRt, 18)

    @patch("rohit_common.rohit_common.india_gst_api.einv.get_gst_based_uom")
    @patch("rohit_common.rohit_common.india_gst_api.einv.get_taxes_type")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_one_row_per_line_item_not_combined_by_hsn(
        self, mock_frappe, mock_get_taxes_type, mock_get_uom
    ):
        item_a = SimpleNamespace(
            idx=1, description="Item A", gst_hsn_code="8443",
            qty=1, uom="Nos", base_rate=50.0, base_amount=50.0,
        )
        item_b = SimpleNamespace(
            idx=2, description="Item B", gst_hsn_code="8443",  # same HSN as item_a
            qty=1, uom="Nos", base_rate=75.0, base_amount=75.0,
        )
        sinv = SimpleNamespace(items=[item_a, item_b])
        mock_frappe._dict = _FakeFrappeDict
        mock_frappe.get_doc.side_effect = lambda doctype, name: (
            sinv if doctype == "Sales Invoice" else _fake_hsn_doc("Generic HSN text")
        )
        mock_get_taxes_type.return_value = {
            "tax_val": 125, "tot_val": 147.5, "cgst_amt": 11.25, "sgst_amt": 11.25,
            "igst_amt": 0, "discount_amt": 0, "other_amt": 0, "gst_per": 18,
            "cgst_per": 9, "sgst_per": 9, "igst_per": 0,
        }
        mock_get_uom.return_value = "NOS"

        itm_lst, _ = einv.get_einv_item_details("Sales Invoice", "SINV-0001")

        # Two distinct items sharing an HSN code stay as two rows, not one
        # combined row — the design doc's original "aggregation" claim was
        # wrong (corrected 2026-08-22); this asserts the actual behavior.
        self.assertEqual(len(itm_lst), 2)
        self.assertEqual(itm_lst[0].TotAmt, 50.0)
        self.assertEqual(itm_lst[1].TotAmt, 75.0)


if __name__ == "__main__":
    unittest.main()
