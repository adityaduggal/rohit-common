#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for search_gstin()/track_return() URL-building and the
REQUEST_DENIED retry-once logic, using mocks for frappe.get_single,
gsp_session.build_public_api_headers, and requests.get — no live site or
TaxPro credentials required.

Full end-to-end verification against TaxPro's real sandbox (issues #8, #9
acceptance criteria) still needs a bench site with `asp_private_key_path`
configured per docs/taxpro-asp-cert-setup.md (#6) — that's a separate,
manual verification step, not covered by these mocked tests.

Run: /home/aditya/v12/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_gst_public_api.py -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import gst_public_api


FAKE_API_INFO = {
    "headers": {
        "aspid": "TESTASPID",
        "asp-secret": "fake-secret",
        "session-id": "fake-session",
        "txn": "fake-txn",
        "ip-usr": "127.0.0.1",
        "Content-Type": "application/json; charset=utf-8",
    },
    "base_url": "https://gstsandbox.charteredinfo.com",
    "sandbox": True,
}


def _fake_response(json_body):
    resp = MagicMock()
    resp.json.return_value = json_body
    return resp


class TestSearchGstin(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_builds_new_commonapi_v1_1_search_url_and_passes_headers(
        self, mock_requests, mock_gsp_session, mock_frappe
    ):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        mock_requests.get.return_value = _fake_response(
            {"status_cd": "1", "gstin": "27AAACT2727Q1ZW", "sts": "Active"}
        )

        result = gst_public_api.search_gstin("27AAACT2727Q1ZW")

        self.assertEqual(result["sts"], "Active")
        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.startswith("https://gstsandbox.charteredinfo.com/commonapi/v1.1/search?"))
        self.assertIn("Action=TP", called_url)
        self.assertIn("Gstin=06AAACR1567J1ZC", called_url)
        self.assertIn("SearchGstin=27AAACT2727Q1ZW", called_url)
        self.assertEqual(mock_requests.get.call_args.kwargs["headers"], FAKE_API_INFO["headers"])
        # No old aspid=/password= query-string auth left in the URL.
        self.assertNotIn("password=", called_url)

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_defaults_to_caller_gstin_when_none_given(self, mock_requests, mock_gsp_session, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        mock_requests.get.return_value = _fake_response({"status_cd": "1"})

        gst_public_api.search_gstin(None)

        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertIn("SearchGstin=06AAACR1567J1ZC", called_url)

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_retries_once_on_request_denied_then_succeeds(self, mock_requests, mock_gsp_session, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        mock_requests.get.side_effect = [
            _fake_response({"status": "REQUEST_DENIED", "error_message": "session expired"}),
            _fake_response({"status_cd": "1", "gstin": "27AAACT2727Q1ZW"}),
        ]

        result = gst_public_api.search_gstin("27AAACT2727Q1ZW")

        self.assertEqual(result["status_cd"], "1")
        self.assertEqual(mock_requests.get.call_count, 2)
        mock_gsp_session.invalidate_session.assert_called_once()

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_gives_up_after_one_retry_still_denied(self, mock_requests, mock_gsp_session, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(gstin="06AAACR1567J1ZC")
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        denied = {"status": "REQUEST_DENIED", "error_message": "still denied"}
        mock_requests.get.side_effect = [_fake_response(denied), _fake_response(denied)]

        result = gst_public_api.search_gstin("27AAACT2727Q1ZW")

        self.assertEqual(result["status"], "REQUEST_DENIED")
        self.assertEqual(mock_requests.get.call_count, 2)
        mock_gsp_session.invalidate_session.assert_called_once()


class TestTrackReturn(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_builds_new_commonapi_v1_0_returns_url(self, mock_requests, mock_gsp_session, mock_frappe):
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        mock_requests.get.return_value = _fake_response({"EFiledlist": []})

        gst_public_api.track_return("27AAACT2727Q1ZW", "2017-2018")

        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertTrue(called_url.startswith("https://gstsandbox.charteredinfo.com/commonapi/v1.0/returns?"))
        self.assertIn("Action=RETTRACK", called_url)
        self.assertIn("Gstin=27AAACT2727Q1ZW", called_url)
        self.assertIn("fy=2017-18", called_url)
        self.assertNotIn("password=", called_url)

    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.frappe")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.gsp_session")
    @patch("rohit_common.rohit_common.india_gst_api.gst_public_api.requests")
    def test_includes_type_of_return_when_given(self, mock_requests, mock_gsp_session, mock_frappe):
        mock_gsp_session.build_public_api_headers.return_value = FAKE_API_INFO
        mock_requests.get.return_value = _fake_response({"EFiledlist": []})

        gst_public_api.track_return("27AAACT2727Q1ZW", "2017-2018", type_of_return="R1")

        called_url = mock_requests.get.call_args.kwargs["url"]
        self.assertIn("&type=R1", called_url)


if __name__ == "__main__":
    unittest.main()
