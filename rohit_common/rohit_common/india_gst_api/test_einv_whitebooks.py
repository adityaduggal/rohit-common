#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for einv.py's WhiteBooks.in e-invoice functions (T3, docs/
designs/gst-asp-migration-whitebooks.md) — request wiring, response
handling, and the duplicate-IRN idempotency path — all mocked (frappe,
requests, whitebooks_provider), no live site or WhiteBooks credentials
required.

Also covers the description-substitution regression: get_einv_item_details()
(the shared, vendor-agnostic payload builder — untouched by this migration
per Premise 3) must keep sending the HSN code's generic description instead
of the item's real description. This guards against a future refactor
silently dropping that privacy behavior, regardless of which HTTP layer
calls it.

The response envelope these functions parse (_parse_generate_irn_response,
WHITEBOOKS_DUPLICATE_IRN_ERROR_CODE) is an UNVERIFIED ASSUMPTION — see the
module note in einv.py above generate_irn_whitebooks(). These tests prove
the code behaves correctly against that assumed shape; they do not prove
the assumption itself is correct. That needs a real WhiteBooks sandbox call
(The Assignment).

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_einv_whitebooks.py -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import einv


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


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


class TestGenerateIrnWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.einv.update_irn_details")
    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    def test_success_updates_irn_details(
        self, mock_requests, mock_wb, mock_gen_json, mock_update
    ):
        mock_gen_json.return_value = '{"fake": "payload"}'
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {"Authorization": "Bearer tok"}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(
            200, {"data": {"Irn": "IRN123", "AckNo": "ACK1", "AckDt": "2026-08-22",
                            "SignedQRCode": "qr-payload"}}
        )

        einv.generate_irn_whitebooks("Sales Invoice", "SINV-0001")

        mock_update.assert_called_once_with(
            "Sales Invoice", "SINV-0001",
            {"Irn": "IRN123", "AckNo": "ACK1", "AckDt": "2026-08-22", "SignedQRCode": "qr-payload"},
        )
        called_url = mock_requests.post.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/generate"))
        self.assertEqual(mock_requests.post.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    @patch("rohit_common.rohit_common.india_gst_api.einv.get_irn_details_whitebooks_by_doc")
    @patch("rohit_common.rohit_common.india_gst_api.einv.update_irn_details")
    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    def test_duplicate_irn_looks_up_existing_and_updates(
        self, mock_requests, mock_wb, mock_gen_json, mock_update, mock_lookup
    ):
        mock_gen_json.return_value = '{"fake": "payload"}'
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(
            409, {"error_code": "2150", "message": "duplicate IRN"}
        )
        mock_lookup.return_value = {"Irn": "EXISTING-IRN"}

        einv.generate_irn_whitebooks("Sales Invoice", "SINV-0001")

        mock_lookup.assert_called_once_with("Sales Invoice", "SINV-0001")
        mock_update.assert_called_once_with("Sales Invoice", "SINV-0001", {"Irn": "EXISTING-IRN"})

    @patch("rohit_common.rohit_common.india_gst_api.einv.update_irn_details")
    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_non_duplicate_failure_logs_and_throws(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json, mock_update
    ):
        mock_gen_json.return_value = '{"fake": "payload"}'
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(
            500, {"error_code": "SERVER_ERROR"}, text="internal error"
        )
        mock_frappe.throw.side_effect = RuntimeError
        mock_frappe.get_desk_link.return_value = "Sales Invoice SINV-0001"

        with self.assertRaises(RuntimeError):
            einv.generate_irn_whitebooks("Sales Invoice", "SINV-0001")

        mock_frappe.log_error.assert_called_once()
        mock_update.assert_not_called()


class TestGenerateIrnWhitebooksBulk(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_generates_unique_submission_id_per_invoice(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        mock_frappe.generate_hash.side_effect = ["sid-1", "sid-2", "sid-3"]
        mock_gen_json.return_value = "{}"
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        submission_ids, _ = einv.generate_irn_whitebooks_bulk(
            "Sales Invoice", ["SINV-1", "SINV-2", "SINV-3"]
        )

        self.assertEqual(
            submission_ids, {"SINV-1": "sid-1", "SINV-2": "sid-2", "SINV-3": "sid-3"}
        )
        self.assertEqual(len(set(submission_ids.values())), 3)

    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_embeds_reference_id_in_each_invoice_payload(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        mock_frappe.generate_hash.side_effect = ["sid-1", "sid-2"]
        mock_gen_json.side_effect = ['{"DocDtls": {"No": "SINV-1"}}', '{"DocDtls": {"No": "SINV-2"}}']
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        einv.generate_irn_whitebooks_bulk("Sales Invoice", ["SINV-1", "SINV-2"])

        sent_body = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(len(sent_body["invoices"]), 2)
        self.assertEqual(sent_body["invoices"][0]["_referenceId"], "sid-1")
        self.assertEqual(sent_body["invoices"][1]["_referenceId"], "sid-2")

    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_posts_single_bulk_request_to_bulk_generate_endpoint(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        mock_frappe.generate_hash.side_effect = ["sid-1", "sid-2"]
        mock_gen_json.return_value = "{}"
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        einv.generate_irn_whitebooks_bulk("Sales Invoice", ["SINV-1", "SINV-2"])

        self.assertEqual(mock_requests.post.call_count, 1)
        called_url = mock_requests.post.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/bulk-generate"))

    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_partial_batch_maps_rejections_back_to_correct_invoice(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        """Guards the partial-batch-failure requirement: some invoices
        accepted, some rejected, in the same bulk call."""
        mock_frappe.generate_hash.side_effect = ["sid-1", "sid-2", "sid-3"]
        mock_gen_json.return_value = "{}"
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(
            200,
            {"rejected": [{"referenceId": "sid-2", "error": "Invalid GSTIN"}]},
        )

        submission_ids, immediate_rejections = einv.generate_irn_whitebooks_bulk(
            "Sales Invoice", ["SINV-1", "SINV-2", "SINV-3"]
        )

        self.assertEqual(immediate_rejections, {"SINV-2": "Invalid GSTIN"})
        self.assertNotIn("SINV-1", immediate_rejections)
        self.assertNotIn("SINV-3", immediate_rejections)
        self.assertEqual(len(submission_ids), 3)

    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_no_rejections_means_all_accepted(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        mock_frappe.generate_hash.side_effect = ["sid-1", "sid-2"]
        mock_gen_json.return_value = "{}"
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        _, immediate_rejections = einv.generate_irn_whitebooks_bulk(
            "Sales Invoice", ["SINV-1", "SINV-2"]
        )

        self.assertEqual(immediate_rejections, {})

    @patch("rohit_common.rohit_common.india_gst_api.einv.gen_einv_json")
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    @patch("rohit_common.rohit_common.india_gst_api.einv.frappe")
    def test_unknown_reference_id_in_rejection_is_ignored_not_crashed(
        self, mock_frappe, mock_requests, mock_wb, mock_gen_json
    ):
        """A rejection for a referenceId we didn't send (shouldn't happen,
        but the response shape is unverified) must not raise."""
        mock_frappe.generate_hash.side_effect = ["sid-1"]
        mock_gen_json.return_value = "{}"
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(
            200, {"rejected": [{"referenceId": "not-a-real-sid", "error": "?"}]}
        )

        submission_ids, immediate_rejections = einv.generate_irn_whitebooks_bulk(
            "Sales Invoice", ["SINV-1"]
        )

        self.assertEqual(immediate_rejections, {})
        self.assertEqual(len(submission_ids), 1)


class TestParseGenerateIrnResponse(unittest.TestCase):
    def test_unwraps_data_key_when_present(self):
        result = einv._parse_generate_irn_response({"data": {"Irn": "X"}})
        self.assertEqual(result, {"Irn": "X"})

    def test_falls_back_to_bare_body_when_no_data_key(self):
        result = einv._parse_generate_irn_response({"Irn": "X"})
        self.assertEqual(result, {"Irn": "X"})


class TestGetIrnDetailsWhitebooksByDoc(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.einv.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.einv.requests")
    def test_builds_lookup_request_with_doc_no(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/einvoice"
        mock_wb.get_headers.return_value = {}
        mock_wb.EINVOICE = "einvoice"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(200, {"Irn": "LOOKED-UP-IRN"})

        result = einv.get_irn_details_whitebooks_by_doc("Sales Invoice", "SINV-0001")

        self.assertEqual(result, {"Irn": "LOOKED-UP-IRN"})
        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/lookup"))
        self.assertEqual(mock_requests.get.call_args.kwargs["params"], {"docNo": "SINV-0001"})


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
