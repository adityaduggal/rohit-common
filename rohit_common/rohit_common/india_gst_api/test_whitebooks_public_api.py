#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for gst_public_api.py's WhiteBooks.in functions (T4, docs/
designs/gst-asp-migration-whitebooks.md) — request wiring only, mocked
(frappe, requests, whitebooks_provider), no live site or WhiteBooks
credentials required.

The response shape these functions return is an UNVERIFIED ASSUMPTION (see
the module note in gst_public_api.py above search_gstin_whitebooks()) — these
tests prove the request is built correctly and the raw JSON response is
returned as-is; they do not prove WhiteBooks' actual response matches what
get_arn_status() expects. That needs a real WhiteBooks sandbox call (The
Assignment).

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_whitebooks_public_api.py -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import gst_public_api


def _fake_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestSearchGstinWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_builds_request_with_caller_gstin_headers_and_base_url(
        self, mock_frappe, mock_requests, mock_wb
    ):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {"Authorization": "Bearer tok"}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(
            200, {"gstin": "27AAACT2727Q1ZW", "sts": "Active"}
        )

        result = gst_public_api.search_gstin_whitebooks("27AAACT2727Q1ZW")

        self.assertEqual(result["sts"], "Active")
        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/gstin-search"))
        self.assertEqual(mock_requests.get.call_args.kwargs["params"], {"gstin": "27AAACT2727Q1ZW"})
        self.assertEqual(mock_requests.get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_defaults_to_caller_gstin_when_none_given(self, mock_frappe, mock_requests, mock_wb):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(200, {})

        gst_public_api.search_gstin_whitebooks(None)

        self.assertEqual(
            mock_requests.get.call_args.kwargs["params"], {"gstin": "06AAACR1567J1ZC"}
        )

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_uses_call_with_token_retry_for_the_public_gst_family(
        self, mock_frappe, mock_requests, mock_wb
    ):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(200, {})

        gst_public_api.search_gstin_whitebooks("27AAACT2727Q1ZW")

        args, kwargs = mock_wb.call_with_token_retry.call_args
        self.assertEqual(args[1], "gst")


class TestTrackReturnWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_builds_request_with_gstin_and_formatted_fiscal_year(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(200, {"EFiledlist": []})

        gst_public_api.track_return_whitebooks("27AAACT2727Q1ZW", "2017-2018")

        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/return-track"))
        params = mock_requests.get.call_args.kwargs["params"]
        self.assertEqual(params["gstin"], "27AAACT2727Q1ZW")
        self.assertEqual(params["fy"], "2017-18")
        self.assertNotIn("type", params)

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_includes_type_of_return_when_given(self, mock_requests, mock_wb):
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(200, {"EFiledlist": []})

        gst_public_api.track_return_whitebooks("27AAACT2727Q1ZW", "2017-2018", type_of_return="R1")

        params = mock_requests.get.call_args.kwargs["params"]
        self.assertEqual(params["type"], "R1")

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.getdate")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_response_still_parses_via_get_arn_status(self, mock_requests, mock_wb, mock_getdate):
        """Guards the shared-parser assumption: get_arn_status() (vendor-
        agnostic, reused unchanged) must still work against whatever
        track_return_whitebooks() returns — same EFiledlist shape."""
        mock_getdate.side_effect = lambda v: v
        mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in/gst"
        mock_wb.get_headers.return_value = {}
        mock_wb.PUBLIC_GST = "gst"
        mock_wb.call_with_token_retry.side_effect = lambda fn, api: fn()
        mock_requests.get.return_value = _fake_response(
            200,
            {"EFiledlist": [{"rtntype": "R1", "ret_prd": "072026", "arn": "ARN123",
                              "status": "Filed", "dof": "2026-08-15", "mof": "Online"}]},
        )

        result = gst_public_api.track_return_whitebooks("27AAACT2727Q1ZW", "2026-2027")
        arn, status, dof, mof = gst_public_api.get_arn_status(result, "R1", "072026")

        self.assertEqual(arn, "ARN123")
        self.assertEqual(status, "Filed")


if __name__ == "__main__":
    unittest.main()
