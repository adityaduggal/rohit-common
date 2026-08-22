#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for eway_bill_api.py's WhiteBooks.in functions (T5, docs/
designs/gst-asp-migration-whitebooks.md) — request wiring only (plumbing,
not business rules — see Premise 1 / TODOS.md), all mocked (requests,
whitebooks_provider), no live site or WhiteBooks credentials required.

The request/response shapes these functions send and expect are UNVERIFIED
ASSUMPTIONS (see the module note in eway_bill_api.py above
generate_ewb_whitebooks()) — the endpoint paths themselves are confirmed
from WhiteBooks' own docs, but the JSON body shape is not. These tests only
prove the HTTP wiring is correct.

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_whitebooks_eway.py -v
"""
import unittest
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import eway_bill_api


def _fake_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestGenerateEwbWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_posts_payload_to_generate_ewb_endpoint(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {"Authorization": "Bearer tok"}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {"ewayBillNo": "EWB123"})

        result = eway_bill_api.generate_ewb_whitebooks({"docNo": "SINV-0001"})

        self.assertEqual(result["ewayBillNo"], "EWB123")
        called_url = mock_requests.post.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/generate-ewb"))
        self.assertEqual(mock_requests.post.call_args.kwargs["json"], {"docNo": "SINV-0001"})
        self.assertEqual(mock_requests.post.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_uses_call_with_token_retry_for_the_eway_family(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        eway_bill_api.generate_ewb_whitebooks({})

        args, kwargs = mock_wb.call_with_token_retry.call_args
        self.assertEqual(args[1], "eway")


class TestCancelEwbWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_posts_ewb_no_to_cancel_endpoint(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {"status": "cancelled"})

        result = eway_bill_api.cancel_ewb_whitebooks("EWB123")

        self.assertEqual(result["status"], "cancelled")
        called_url = mock_requests.post.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/cancel"))
        self.assertEqual(mock_requests.post.call_args.kwargs["json"], {"ewbNo": "EWB123"})

    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_includes_reason_when_given(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        eway_bill_api.cancel_ewb_whitebooks("EWB123", reason="Order cancelled")

        self.assertEqual(
            mock_requests.post.call_args.kwargs["json"],
            {"ewbNo": "EWB123", "reason": "Order cancelled"},
        )

    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_omits_reason_when_not_given(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.post.return_value = _fake_response(200, {})

        eway_bill_api.cancel_ewb_whitebooks("EWB123")

        self.assertNotIn("reason", mock_requests.post.call_args.kwargs["json"])


class TestUpdatePartBWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_puts_vehicle_details_with_ewb_no_to_update_part_b_endpoint(
        self, mock_requests, mock_wb
    ):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.put.return_value = _fake_response(200, {"status": "updated"})

        result = eway_bill_api.update_part_b_whitebooks(
            "EWB123", {"vehicleNo": "MH12AB1234", "transMode": 1}
        )

        self.assertEqual(result["status"], "updated")
        called_url = mock_requests.put.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/update-part-b"))
        sent_body = mock_requests.put.call_args.kwargs["json"]
        self.assertEqual(sent_body["ewbNo"], "EWB123")
        self.assertEqual(sent_body["vehicleNo"], "MH12AB1234")

    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.eway_bill_api.requests")
    def test_does_not_mutate_caller_vehicle_details_dict(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/eway"
        mock_wb.get_headers.return_value = {}
        mock_wb.EWAY = "eway"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.put.return_value = _fake_response(200, {})
        original = {"vehicleNo": "MH12AB1234"}

        eway_bill_api.update_part_b_whitebooks("EWB123", original)

        self.assertNotIn("ewbNo", original)


if __name__ == "__main__":
    unittest.main()
