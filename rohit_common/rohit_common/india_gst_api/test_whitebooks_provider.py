#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for whitebooks_provider.py: base-URL selection, credentials, the
reply envelope, and the e-Invoice / e-Way Bill clients (authenticate once,
cache, re-authenticate once on an expired token, no URL in network errors).
frappe and requests are mocked, so no site or WhiteBooks credentials are needed.
The request shapes are the ones in WhiteBooks' Postman collections.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_whitebooks_provider
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import requests

from rohit_common.rohit_common.india_gst_api import common
from rohit_common.rohit_common.india_gst_api import whitebooks_provider as wb

WB = "rohit_common.rohit_common.india_gst_api.whitebooks_provider"


def _fake_settings(sandbox_mode=0, **overrides):
    defaults = dict(
        sandbox_mode=sandbox_mode,
        gstin="06AAACR1567J1ZC",
        eway_bill_id="prod-api-user",
        whitebooks_sandbox_gstin="29AAGCB1286Q000",
        whitebooks_sandbox_api_username="sandbox-api-user",
        whitebooks_gst_email="gsp@rigpl.com",
        whitebooks_gst_ip_address="10.0.0.1",
        whitebooks_einv_client_id="einv-prod-id",
        whitebooks_einv_sandbox_client_id="einv-sandbox-id",
        whitebooks_gst_client_id="gst-prod-id",
        whitebooks_gst_sandbox_client_id="gst-sandbox-id",
        whitebooks_eway_client_id="eway-prod-id",
        whitebooks_eway_sandbox_client_id="eway-sandbox-id",
    )
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    ns.get_password = MagicMock(side_effect=lambda field, raise_exception=True: f"secret-for-{field}")
    return ns


class _FakeCache:
    def __init__(self):
        self.values = {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def _raise(msg, *args, **kwargs):
    raise RuntimeError(msg)


def _mock_frappe(mock_frappe, settings):
    mock_frappe.get_single.return_value = settings
    mock_frappe.throw.side_effect = _raise
    mock_frappe._dict = frappe._dict
    cache = _FakeCache()
    mock_frappe.cache.return_value = cache
    return cache


def _reply(body):
    resp = MagicMock()
    resp.json.return_value = body
    return resp


class TestGetBaseUrl(unittest.TestCase):
    @patch(f"{WB}.is_developer_mode", return_value=False)
    @patch(f"{WB}.frappe")
    def test_sandbox_mode_uses_sandbox_host(self, mock_frappe, _dev_mode):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        self.assertEqual(wb.get_base_url(wb.EINVOICE), "https://apisandbox.whitebooks.in/einvoice")

    @patch(f"{WB}.is_developer_mode", return_value=False)
    @patch(f"{WB}.frappe")
    def test_production_mode_uses_production_host(self, mock_frappe, _dev_mode):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=0)
        self.assertEqual(wb.get_base_url(wb.EWAY), "https://api.whitebooks.in/ewaybillapi/v1.03")

    @patch(f"{WB}.is_developer_mode", return_value=True)
    @patch(f"{WB}.frappe")
    def test_developer_mode_forces_sandbox_for_document_families(self, mock_frappe, _dev_mode):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=0)
        self.assertEqual(wb.get_base_url(wb.EINVOICE), "https://apisandbox.whitebooks.in/einvoice")
        self.assertEqual(wb.get_base_url(wb.EWAY), "https://apisandbox.whitebooks.in/ewaybillapi/v1.03")

    @patch(f"{WB}.is_developer_mode", return_value=True)
    @patch(f"{WB}.frappe")
    def test_developer_mode_leaves_public_gst_on_the_checkbox(self, mock_frappe, _dev_mode):
        """Public GST is read-only lookups, so developer_mode does not force it."""
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=0)
        self.assertEqual(wb.get_base_url(wb.PUBLIC_GST), "https://api.whitebooks.in")

    @patch(f"{WB}.frappe")
    def test_unknown_api_family_raises(self, mock_frappe):
        mock_frappe.throw.side_effect = _raise
        with self.assertRaises(RuntimeError):
            wb.get_base_url("not-a-real-family")


class TestUseGstSandbox(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.common.frappe")
    def test_developer_mode_in_site_config_forces_sandbox(self, mock_frappe):
        mock_frappe.conf = {"developer_mode": 1}
        self.assertTrue(common.use_gst_sandbox(SimpleNamespace(sandbox_mode=0)))

    @patch("rohit_common.rohit_common.india_gst_api.common.frappe")
    def test_checkbox_decides_without_developer_mode(self, mock_frappe):
        mock_frappe.conf = {}
        self.assertFalse(common.use_gst_sandbox(SimpleNamespace(sandbox_mode=0)))
        self.assertTrue(common.use_gst_sandbox(SimpleNamespace(sandbox_mode=1)))


class TestStaticHeadersAndEmail(unittest.TestCase):
    @patch(f"{WB}.frappe")
    def test_returns_client_id_and_secret_as_headers(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        self.assertEqual(wb.get_static_client_headers(wb.PUBLIC_GST), {
            "client_id": "gst-sandbox-id",
            "client_secret": "secret-for-whitebooks_gst_sandbox_client_secret",
        })

    @patch(f"{WB}.frappe")
    def test_one_registered_email_for_every_family(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings()
        self.assertEqual({wb.get_registered_email(api) for api in wb.API_FAMILIES}, {"gsp@rigpl.com"})

    @patch(f"{WB}.frappe")
    def test_throws_when_email_not_configured(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(whitebooks_gst_email=None)
        mock_frappe.throw.side_effect = _raise
        with self.assertRaises(RuntimeError):
            wb.get_registered_email(wb.EINVOICE)


class TestEnvelope(unittest.TestCase):
    def test_success_spellings(self):
        for status in ("1", 1, "Sucess", "Success"):
            self.assertTrue(wb.is_success({"status_cd": status}), status)
        self.assertFalse(wb.is_success({"status_cd": "0"}))

    def test_einvoice_codes_in_status_desc(self):
        resp = {"status_cd": "0", "status_desc": '[{"ErrorCode":"2150","ErrorMessage":"Duplicate IRN"}]'}
        self.assertEqual(wb.error_codes(resp), ["2150"])

    def test_eway_codes_in_error_message(self):
        resp = {"status_cd": "0", "error": {"message": '{"errorCodes":"238,"}'}}
        self.assertEqual(wb.error_codes(resp), ["238"])

    def test_gst_returns_error_code(self):
        resp = {"status_cd": "0", "error": {"errorCode": "RET11416", "errorMessage": "No data"}}
        self.assertEqual(wb.error_codes(resp), ["RET11416"])

    def test_unwrap_parses_json_text_data(self):
        self.assertEqual(wb.unwrap({"status_cd": "1", "data": '{"ewayBillNo": 101}'}, "x"),
                         {"ewayBillNo": 101})

    @patch(f"{WB}.frappe")
    def test_unwrap_throws_with_the_codes(self, mock_frappe):
        mock_frappe.throw.side_effect = _raise
        with self.assertRaisesRegex(RuntimeError, "Invalid GSTIN"):
            wb.unwrap({"status_cd": "0", "status_desc": "Invalid GSTIN"}, "IRN generation")


@patch(f"{WB}.is_developer_mode", return_value=False)
@patch(f"{WB}.requests.request")
@patch(f"{WB}.frappe")
class TestEinvoiceRequest(unittest.TestCase):
    AUTH = {"status_cd": "Sucess", "data": {"AuthToken": "tok-1", "TokenExpiry": None}}

    def test_authenticates_then_sends_token_and_api_user(self, mock_frappe, mock_request, _dev):
        cache = _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1))
        mock_request.side_effect = [_reply(self.AUTH), _reply({"status_cd": "1", "data": {"Irn": "X"}})]

        resp = wb.einvoice_request("POST", "GENERATE", body='{"Version": "1.1"}')

        self.assertEqual(resp["data"], {"Irn": "X"})
        auth, call = mock_request.call_args_list
        self.assertEqual(auth.args, ("GET", "https://apisandbox.whitebooks.in/einvoice/authenticate"))
        self.assertEqual(auth.kwargs["headers"]["password"],
                         "secret-for-whitebooks_sandbox_api_password")
        self.assertEqual(call.args, ("POST", "https://apisandbox.whitebooks.in/einvoice/type/GENERATE/version/V1_03"))
        headers = call.kwargs["headers"]
        self.assertEqual((headers["auth-token"], headers["username"], headers["gstin"]),
                         ("tok-1", "sandbox-api-user", "29AAGCB1286Q000"))
        self.assertNotIn("password", headers)
        self.assertEqual(call.kwargs["params"], {"email": "gsp@rigpl.com"})
        self.assertEqual(call.kwargs["data"], '{"Version": "1.1"}')
        self.assertIn("tok-1", cache.values.values())

    def test_cached_token_is_reused(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1))
        mock_request.side_effect = [_reply(self.AUTH), _reply({"status_cd": "1"}), _reply({"status_cd": "1"})]

        wb.einvoice_request("GET", "GETIRN", params={"param1": "a"})
        wb.einvoice_request("GET", "GETIRN", params={"param1": "b"})

        self.assertEqual(mock_request.call_count, 3)

    def test_expired_token_authenticates_again_once(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1))
        expired = {"status_cd": "0", "status_desc": '[{"ErrorCode":"1005","ErrorMessage":"Invalid Token"}]'}
        fresh = {"status_cd": "Sucess", "data": {"AuthToken": "tok-2"}}
        mock_request.side_effect = [_reply(self.AUTH), _reply(expired), _reply(fresh),
                                    _reply({"status_cd": "1", "data": {"Irn": "X"}})]

        resp = wb.einvoice_request("GET", "GETIRN", params={"param1": "a"})

        self.assertEqual(resp["data"], {"Irn": "X"})
        self.assertEqual(mock_request.call_args_list[-1].kwargs["headers"]["auth-token"], "tok-2")

    def test_production_uses_the_production_api_user(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=0))
        mock_request.side_effect = [_reply(self.AUTH), _reply({"status_cd": "1"})]

        wb.einvoice_request("GET", "GETIRN", params={"param1": "a"})

        auth = mock_request.call_args_list[0]
        self.assertEqual(auth.args[1], "https://api.whitebooks.in/einvoice/authenticate")
        self.assertEqual((auth.kwargs["headers"]["username"], auth.kwargs["headers"]["gstin"]),
                         ("prod-api-user", "06AAACR1567J1ZC"))
        self.assertEqual(auth.kwargs["headers"]["password"], "secret-for-eway_bill_password")

    def test_missing_api_user_throws_before_any_call(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1, whitebooks_sandbox_api_username=None))
        with self.assertRaisesRegex(RuntimeError, "GST API Username"):
            wb.einvoice_request("GET", "GETIRN")
        mock_request.assert_not_called()


@patch(f"{WB}.is_developer_mode", return_value=False)
@patch(f"{WB}.requests.request")
@patch(f"{WB}.frappe")
class TestEwayRequest(unittest.TestCase):
    def test_opens_session_once_and_sends_no_password_on_data_calls(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1))
        mock_request.side_effect = [_reply({"status_cd": "1"}), _reply({"status_cd": "1", "data": "[]"}),
                                    _reply({"status_cd": "1", "data": "[]"})]

        wb.eway_request("GET", "getewaybillsbydate", params={"date": "01/10/2026"})
        wb.eway_request("GET", "getewaybillsbydate", params={"date": "02/10/2026"})

        auth, first, second = mock_request.call_args_list
        self.assertEqual(auth.args[1], "https://apisandbox.whitebooks.in/ewaybillapi/v1.03/authenticate")
        self.assertEqual(auth.kwargs["params"]["username"], "sandbox-api-user")
        self.assertEqual(first.args[1],
                         "https://apisandbox.whitebooks.in/ewaybillapi/v1.03/ewayapi/getewaybillsbydate")
        self.assertEqual(first.kwargs["params"], {"date": "01/10/2026", "email": "gsp@rigpl.com"})
        self.assertNotIn("password", first.kwargs["headers"])

    def test_expired_session_opens_again_once(self, mock_frappe, mock_request, _dev):
        _mock_frappe(mock_frappe, _fake_settings(sandbox_mode=1))
        expired = {"status_cd": "0", "error": {"message": '{"errorCodes":"238"}'}}
        mock_request.side_effect = [_reply({"status_cd": "1"}), _reply(expired), _reply({"status_cd": "1"}),
                                    _reply({"status_cd": "1", "data": {"ewbNo": 1}})]

        resp = wb.eway_request("GET", "getewaybill", params={"ewbNo": 1})

        self.assertEqual(resp["data"], {"ewbNo": 1})
        self.assertEqual(mock_request.call_count, 4)


class TestSendHidesUrl(unittest.TestCase):
    @patch(f"{WB}.requests.request")
    @patch(f"{WB}.frappe")
    def test_network_error_does_not_show_the_query_string(self, mock_frappe, mock_request):
        mock_frappe.throw.side_effect = _raise
        url = "https://api.whitebooks.in/ewaybillapi/v1.03/authenticate"
        mock_request.side_effect = requests.ConnectionError(f"Max retries exceeded with url: {url}?password=SECRET")

        with self.assertRaises(RuntimeError) as ctx:
            wb._send("GET", url, {}, {"password": "SECRET"})

        self.assertIn("ConnectionError", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertIsNone(ctx.exception.__context__)


if __name__ == "__main__":
    unittest.main()
