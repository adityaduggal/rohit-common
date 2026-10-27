#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Tests for the WhiteBooks GST taxpayer client (gst_api.py) on the real site. Rohit Settings and a
Rohit GST Settings row are set up in the DB; only the HTTP call (requests) is patched. Every test
rolls back.

Run: bench --site <sitename> run-tests --module rohit_common.rohit_common.india_gst_api.test_gst_api
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import set_encrypted_password

from rohit_common.rohit_common.india_gst_api import gst_api

REQUESTS = "rohit_common.rohit_common.india_gst_api.gst_api.requests"
GSTIN = "29AABCT1332L1ZU"


def fake_response(json_body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_body
    return resp


class GstApiTestCase(unittest.TestCase):
    def setUp(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")
        frappe.db.set_value("Rohit Settings", "Rohit Settings", {
            "sandbox_mode": 1,
            "whitebooks_gst_sandbox_client_id": "test-cid",
            "whitebooks_gst_email": "gsp@example.com",
            "whitebooks_gst_ip_address": "10.1.2.3",
        })
        set_encrypted_password("Rohit Settings", "Rohit Settings", "test-secret", "whitebooks_gst_sandbox_client_secret")
        frappe.db.delete("GST Registration Details", {"gst_registration_number": GSTIN})
        self.row = frappe.get_doc({
            "doctype": "GST Registration Details",
            "parent": "Rohit GST Settings",
            "parenttype": "Rohit GST Settings",
            "parentfield": "gst_registration_details",
            "idx": 999,
            "gst_registration_number": GSTIN,
            "gst_username": "tp_user",
            "whitebooks_txn": "TXN-1",
            "api_access_authorized": 1,
            "validity_of_token": now_datetime() + datetime.timedelta(hours=2),
            "update_token_every_mins": 300,
            "no_of_times_token_updated": 3,
        })
        self.row.db_insert()

    def tearDown(self):
        frappe.db.rollback()

    def reg_value(self, field):
        return frappe.db.get_value("GST Registration Details", self.row.name, field)


class TestReturnDownloads(GstApiTestCase):
    @patch(REQUESTS)
    def test_sends_session_headers_and_unwraps_data(self, mock_requests):
        mock_requests.get.side_effect = [
            fake_response({"status_cd": "1", "data": {"b2b": [{"ctin": "07AAACR1567J1ZC"}]}}),
            fake_response({"status_cd": "1", "data": {"txpd": [{"pos": "07"}]}}),
        ]

        result = gst_api.get_gstr1(GSTIN, "072025", {"b2b": "b2b", "txp": "txpd"})

        self.assertEqual(result, {"b2b": [{"ctin": "07AAACR1567J1ZC"}], "txp": [{"pos": "07"}]})
        first, second = mock_requests.get.call_args_list
        self.assertEqual(first.kwargs["url"], "https://apisandbox.whitebooks.in/gstr1/b2b")
        self.assertEqual(second.kwargs["url"], "https://apisandbox.whitebooks.in/gstr1/txp")
        self.assertEqual(first.kwargs["headers"], {
            "client_id": "test-cid", "client_secret": "test-secret", "gst_username": "tp_user",
            "state_cd": "29", "ip_address": "10.1.2.3", "txn": "TXN-1"})
        self.assertEqual(first.kwargs["params"], {"gstin": GSTIN, "retperiod": "072025", "email": "gsp@example.com"})

    @patch(REQUESTS)
    def test_no_data_error_code_gives_empty_section(self, mock_requests):
        mock_requests.get.return_value = fake_response(
            {"status_cd": "0", "status_desc": "No invoices found", "error": {"error_cd": "RET13510"}})

        self.assertEqual(gst_api.get_gstr2a(GSTIN, "072025", {"b2b": "b2b"}), {"b2b": []})
        self.assertTrue(mock_requests.get.call_args.kwargs["url"].endswith("/gstr2a/b2b"))

    @patch(REQUESTS)
    def test_other_error_throws_with_raw_response(self, mock_requests):
        mock_requests.get.return_value = fake_response(
            {"status_cd": "0", "status_desc": "Invalid Session", "error": {"error_cd": "AUTH4033"}})

        with self.assertRaises(frappe.ValidationError) as ctx:
            gst_api.get_gstr1(GSTIN, "072025", {"b2b": "b2b"})
        self.assertIn("AUTH4033", str(ctx.exception))

    @patch(REQUESTS)
    def test_expired_session_throws_without_api_call(self, mock_requests):
        frappe.db.set_value("GST Registration Details", self.row.name, "validity_of_token",
                            now_datetime() - datetime.timedelta(minutes=1))

        with self.assertRaises(frappe.ValidationError):
            gst_api.get_gstr1(GSTIN, "072025", {"b2b": "b2b"})
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_missing_ip_address_throws(self, mock_requests):
        frappe.db.set_value("Rohit Settings", "Rohit Settings", "whitebooks_gst_ip_address", "")

        with self.assertRaises(frappe.ValidationError):
            gst_api.get_gstr1(GSTIN, "072025", {"b2b": "b2b"})
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_gstr2b_uses_rtnprd(self, mock_requests):
        mock_requests.get.return_value = fake_response({"status_cd": "1", "data": {"gendt": "14-08-2025"}})

        resp = gst_api.get_gstr2b(GSTIN, "072025")

        self.assertEqual(resp["data"]["gendt"], "14-08-2025")
        self.assertTrue(mock_requests.get.call_args.kwargs["url"].endswith("/gstr2b/all"))
        self.assertEqual(mock_requests.get.call_args.kwargs["params"]["rtnprd"], "072025")


class TestOtp(GstApiTestCase):
    @patch(REQUESTS)
    def test_otp_request_stores_txn_and_revokes_access(self, mock_requests):
        mock_requests.get.return_value = fake_response({"status_cd": "1", "header": {"txn": "TXN-NEW"}})

        gst_api.get_gst_otp(GSTIN)

        self.assertNotIn("txn", mock_requests.get.call_args.kwargs["headers"])
        self.assertTrue(mock_requests.get.call_args.kwargs["url"].endswith("/authentication/otprequest"))
        self.assertEqual(self.reg_value("whitebooks_txn"), "TXN-NEW")
        self.assertEqual(self.reg_value("api_access_authorized"), 0)

    @patch(REQUESTS)
    def test_otp_request_without_txn_in_reply_throws(self, mock_requests):
        mock_requests.get.return_value = fake_response({"status_cd": "1"})

        with self.assertRaises(frappe.ValidationError):
            gst_api.get_gst_otp(GSTIN)
        self.assertEqual(self.reg_value("whitebooks_txn"), "TXN-1")

    @patch(REQUESTS)
    def test_rejects_filter_shaped_arguments(self, mock_requests):
        for bad in (["!=", ""], {"gst_registration_number": ["!=", ""]}, ""):
            with self.assertRaises(frappe.ValidationError):
                gst_api.get_gst_otp(bad)
            with self.assertRaises(frappe.ValidationError):
                gst_api.authenticate_gst_otp(GSTIN, bad, self.row.name)
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_rejects_row_of_another_gstin(self, mock_requests):
        with self.assertRaises(frappe.ValidationError):
            gst_api.authenticate_gst_otp(GSTIN, "575757", "some-other-row")
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_rejects_non_digit_otp(self, mock_requests):
        with self.assertRaises(frappe.ValidationError):
            gst_api.authenticate_gst_otp(GSTIN, "57a757", self.row.name)
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_valid_otp_activates_session(self, mock_requests):
        frappe.db.set_value("GST Registration Details", self.row.name, "api_access_authorized", 0)
        mock_requests.get.return_value = fake_response({"status_cd": "1", "data": {"auth_token": "AT-1"}})

        gst_api.authenticate_gst_otp(GSTIN, "575757", self.row.name)

        call = mock_requests.get.call_args
        self.assertTrue(call.kwargs["url"].endswith("/authentication/authtoken"))
        self.assertEqual(call.kwargs["params"]["otp"], "575757")
        self.assertEqual(call.kwargs["headers"]["txn"], "TXN-1")
        self.assertEqual(self.reg_value("api_access_authorized"), 1)
        self.assertEqual(self.reg_value("authorization_token"), "AT-1")
        self.assertGreater(get_datetime(self.reg_value("validity_of_token")),
                           now_datetime() + datetime.timedelta(minutes=gst_api.TOKEN_VALIDITY_MINS - 5))


class TestRefreshToken(GstApiTestCase):
    def load_row(self):
        return frappe.get_doc("GST Registration Details", self.row.name)

    @patch(REQUESTS)
    def test_not_due_makes_no_call(self, mock_requests):
        gst_api.check_for_refresh_token(self.load_row())
        mock_requests.get.assert_not_called()

    @patch(REQUESTS)
    def test_due_refresh_extends_validity(self, mock_requests):
        frappe.db.set_value("GST Registration Details", self.row.name, "update_token_every_mins", 0)
        mock_requests.get.return_value = fake_response({"status_cd": "1"})

        gst_api.check_for_refresh_token(self.load_row())

        self.assertTrue(mock_requests.get.call_args.kwargs["url"].endswith("/authentication/refreshtoken"))
        self.assertEqual(self.reg_value("no_of_times_token_updated"), 4)
        self.assertGreater(get_datetime(self.reg_value("validity_of_token")),
                           now_datetime() + datetime.timedelta(hours=5))

    @patch(REQUESTS)
    def test_revoking_error_removes_access(self, mock_requests):
        frappe.db.set_value("GST Registration Details", self.row.name, "update_token_every_mins", 0)
        mock_requests.get.return_value = fake_response({"status_cd": "0", "error": {"error_cd": "AUTH4037"}})

        gst_api.check_for_refresh_token(self.load_row())

        self.assertEqual(self.reg_value("api_access_authorized"), 0)

    @patch(REQUESTS)
    def test_expired_session_is_revoked_without_call(self, mock_requests):
        frappe.db.set_value("GST Registration Details", self.row.name, "validity_of_token",
                            now_datetime() - datetime.timedelta(minutes=1))

        gst_api.check_for_refresh_token(self.load_row())

        mock_requests.get.assert_not_called()
        self.assertEqual(self.reg_value("api_access_authorized"), 0)


if __name__ == "__main__":
    unittest.main()
