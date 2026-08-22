#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for gst_public_api.py's WhiteBooks.in functions (T4, docs/
designs/gst-asp-migration-whitebooks.md) — request wiring only, mocked
(frappe, requests, whitebooks_provider), no live site or WhiteBooks
credentials required.

Auth model confirmed 2026-08-22 against WhiteBooks' "GST-API" Postman
collection: PUBLIC_GST has no OAuth2 token endpoint at all — every call
sends client_id/client_secret directly as headers (whitebooks_provider.
get_static_client_headers()) plus a registered email query param
(whitebooks_provider.get_registered_email()). Endpoint paths confirmed as
/public/search and /public/rettrack (rooted, no /gst prefix).

Response *body* shape is still an UNVERIFIED ASSUMPTION (see the module
note in gst_public_api.py above search_gstin_whitebooks()) — these tests
prove the request is built correctly and the raw JSON response is returned
as-is; they do not prove WhiteBooks' actual response matches what
get_arn_status() expects. That needs a real WhiteBooks sandbox call.

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


def _configure_wb(mock_wb):
    mock_wb.PUBLIC_GST = "gst"
    mock_wb.get_base_url.return_value = "https://apisandbox.whitebooks.in"
    mock_wb.get_static_client_headers.return_value = {
        "client_id": "cid",
        "client_secret": "csecret",
    }
    mock_wb.get_registered_email.return_value = "gsp@rigpl.com"


class TestSearchGstinWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_builds_request_with_static_headers_email_and_gstin(
        self, mock_frappe, mock_requests, mock_wb
    ):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        _configure_wb(mock_wb)
        mock_requests.get.return_value = _fake_response(
            200, {"gstin": "27AAACT2727Q1ZW", "sts": "Active"}
        )

        result = gst_public_api.search_gstin_whitebooks("27AAACT2727Q1ZW")

        self.assertEqual(result["sts"], "Active")
        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/public/search"))
        self.assertEqual(
            mock_requests.get.call_args.kwargs["params"],
            {"email": "gsp@rigpl.com", "gstin": "27AAACT2727Q1ZW"},
        )
        self.assertEqual(
            mock_requests.get.call_args.kwargs["headers"],
            {"client_id": "cid", "client_secret": "csecret"},
        )

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_defaults_to_caller_gstin_when_none_given(self, mock_frappe, mock_requests, mock_wb):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        _configure_wb(mock_wb)
        mock_requests.get.return_value = _fake_response(200, {})

        gst_public_api.search_gstin_whitebooks(None)

        self.assertEqual(
            mock_requests.get.call_args.kwargs["params"]["gstin"], "06AAACR1567J1ZC"
        )

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    def test_does_not_use_oauth2_token_machinery(self, mock_frappe, mock_requests, mock_wb):
        """PUBLIC_GST has no token endpoint - confirms this call path never
        touches get_headers()/get_token()/call_with_token_retry()."""
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        _configure_wb(mock_wb)
        mock_requests.get.return_value = _fake_response(200, {})

        gst_public_api.search_gstin_whitebooks("27AAACT2727Q1ZW")

        mock_wb.get_headers.assert_not_called()
        mock_wb.get_token.assert_not_called()
        mock_wb.call_with_token_retry.assert_not_called()
        mock_wb.get_static_client_headers.assert_called_once_with("gst")


class TestTrackReturnWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_builds_request_with_gstin_email_and_formatted_fiscal_year(
        self, mock_requests, mock_wb
    ):
        _configure_wb(mock_wb)
        mock_requests.get.return_value = _fake_response(200, {"EFiledlist": []})

        gst_public_api.track_return_whitebooks("27AAACT2727Q1ZW", "2017-2018")

        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.endswith("/public/rettrack"))
        params = mock_requests.get.call_args.kwargs["params"]
        self.assertEqual(params["gstin"], "27AAACT2727Q1ZW")
        self.assertEqual(params["fy"], "2017-18")
        self.assertEqual(params["email"], "gsp@rigpl.com")
        self.assertNotIn("type", params)

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.whitebooks_provider")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_includes_type_of_return_when_given(self, mock_requests, mock_wb):
        _configure_wb(mock_wb)
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
        _configure_wb(mock_wb)
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
