#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for whitebooks_provider.py's base-URL selection, per-family
OAuth2 token fetch/cache, header building, and the single-retry-on-401
pattern — all mocked (frappe, requests), no live site or WhiteBooks
credentials required.

Full end-to-end verification against WhiteBooks' real sandbox (The
Assignment in docs/designs/gst-asp-migration-whitebooks.md) is a separate,
manual step — these tests only prove the client behaves correctly against
whatever WhiteBooks actually returns, once that shape is confirmed.

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_whitebooks_provider.py -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import whitebooks_provider as wb


def _fake_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    return resp


def _fake_settings(sandbox_mode=0, **overrides):
    defaults = dict(
        sandbox_mode=sandbox_mode,
        whitebooks_einv_client_id="einv-prod-id",
        whitebooks_einv_sandbox_client_id="einv-sandbox-id",
        whitebooks_gst_client_id="gst-prod-id",
        whitebooks_gst_sandbox_client_id="gst-sandbox-id",
        whitebooks_eway_client_id="eway-prod-id",
        whitebooks_eway_sandbox_client_id="eway-sandbox-id",
    )
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)

    def _fake_password(field):
        return f"secret-for-{field}"

    ns.get_password = MagicMock(side_effect=_fake_password)
    return ns


def frappe_throw_side_effect(msg):
    raise RuntimeError(msg)


class TestGetBaseUrl(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_sandbox_mode_uses_sandbox_host(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        self.assertEqual(
            wb.get_base_url(wb.EINVOICE), "https://apisandbox.whitebooks.in/einvoice"
        )

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_production_mode_uses_production_host(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=0)
        self.assertEqual(wb.get_base_url(wb.EWAY), "https://api.whitebooks.in/eway")

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_public_gst_has_no_family_path_prefix(self, mock_frappe):
        """Confirmed 2026-08-22 via WhiteBooks' GST-API Postman collection:
        PUBLIC_GST paths (/public/search etc.) are rooted, not under /gst -
        the earlier /oauth/token 404 traced back to this being wrong."""
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        self.assertEqual(wb.get_base_url(wb.PUBLIC_GST), "https://apisandbox.whitebooks.in")

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_each_family_has_a_distinct_path(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        urls = {api: wb.get_base_url(api) for api in wb.API_FAMILIES}
        self.assertEqual(len(set(urls.values())), len(wb.API_FAMILIES))

    def test_unknown_api_family_raises(self):
        with patch(
            "rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe"
        ) as mock_frappe:
            mock_frappe.throw.side_effect = frappe_throw_side_effect
            with self.assertRaises(RuntimeError):
                wb.get_base_url("not-a-real-family")


class TestGetToken(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_fetches_and_caches_new_token_when_none_cached(self, mock_frappe, mock_requests):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_requests.post.return_value = _fake_response(
            200, {"access_token": "tok123", "token_type": "Bearer", "expires_in": 3600}
        )

        token = wb.get_token(wb.EINVOICE)

        self.assertEqual(token["access_token"], "tok123")
        mock_frappe.cache.return_value.set_value.assert_called_once()
        set_call = mock_frappe.cache.return_value.set_value.call_args
        self.assertEqual(set_call.args[0], "whitebooks_gsp_access_token_einvoice")
        self.assertEqual(set_call.kwargs["expires_in_sec"], 3600 - 30)

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_returns_cached_token_without_a_new_request(self, mock_frappe, mock_requests):
        mock_frappe.cache.return_value.get_value.return_value = {
            "access_token": "cached-tok",
            "token_type": "Bearer",
            "fetched_at": "2026-08-22T00:00:00",
            "expires_in": 3600,
        }

        token = wb.get_token(wb.EINVOICE)

        self.assertEqual(token["access_token"], "cached-tok")
        mock_requests.post.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_different_families_use_different_cache_keys(self, mock_frappe, mock_requests):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_requests.post.return_value = _fake_response(
            200, {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
        )

        wb.get_token(wb.EINVOICE)
        wb.get_token(wb.EWAY)

        cache_keys = {
            call.args[0] for call in mock_frappe.cache.return_value.get_value.call_args_list
        }
        self.assertEqual(
            cache_keys,
            {"whitebooks_gsp_access_token_einvoice", "whitebooks_gsp_access_token_eway"},
        )

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_force_refresh_ignores_cache(self, mock_frappe, mock_requests):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        mock_frappe.cache.return_value.get_value.return_value = {
            "access_token": "stale-tok",
            "token_type": "Bearer",
            "fetched_at": "2026-08-22T00:00:00",
            "expires_in": 3600,
        }
        mock_requests.post.return_value = _fake_response(
            200, {"access_token": "fresh-tok", "token_type": "Bearer", "expires_in": 3600}
        )

        token = wb.get_token(wb.EINVOICE, force_refresh=True)

        self.assertEqual(token["access_token"], "fresh-tok")
        mock_requests.post.assert_called_once()

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_sandbox_mode_uses_sandbox_credentials_for_that_family(self, mock_frappe, mock_requests):
        settings = _fake_settings(sandbox_mode=1)
        mock_frappe.get_single.return_value = settings
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_requests.post.return_value = _fake_response(
            200, {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
        )

        wb.get_token(wb.EWAY)

        called_body = mock_requests.post.call_args.kwargs["data"]
        self.assertEqual(called_body["client_id"], "eway-sandbox-id")
        self.assertEqual(
            called_body["client_secret"], "secret-for-whitebooks_eway_sandbox_client_secret"
        )
        self.assertEqual(called_body["grant_type"], "client_credentials")

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_production_mode_uses_production_credentials_for_that_family(
        self, mock_frappe, mock_requests
    ):
        settings = _fake_settings(sandbox_mode=0)
        mock_frappe.get_single.return_value = settings
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_requests.post.return_value = _fake_response(
            200, {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
        )

        wb.get_token(wb.PUBLIC_GST)

        called_body = mock_requests.post.call_args.kwargs["data"]
        self.assertEqual(called_body["client_id"], "gst-prod-id")
        self.assertEqual(
            called_body["client_secret"], "secret-for-whitebooks_gst_client_secret"
        )

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_missing_credentials_raises(self, mock_frappe, mock_requests):
        settings = _fake_settings(sandbox_mode=1, whitebooks_einv_sandbox_client_id=None)
        mock_frappe.get_single.return_value = settings
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_frappe.throw.side_effect = frappe_throw_side_effect

        with self.assertRaises(RuntimeError):
            wb.get_token(wb.EINVOICE)
        mock_requests.post.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_missing_access_token_in_response_raises(self, mock_frappe, mock_requests):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        mock_frappe.cache.return_value.get_value.return_value = None
        mock_requests.post.return_value = _fake_response(200, {"error": "invalid_client"})
        mock_frappe.throw.side_effect = frappe_throw_side_effect

        with self.assertRaises(RuntimeError):
            wb.get_token(wb.EINVOICE)

    def test_unknown_api_family_raises(self):
        with patch(
            "rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe"
        ) as mock_frappe:
            mock_frappe.throw.side_effect = frappe_throw_side_effect
            with self.assertRaises(RuntimeError):
                wb.get_token("not-a-real-family")


class TestGetHeaders(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.requests")
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_returns_bearer_authorization_header(self, mock_frappe, mock_requests):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)
        mock_frappe.cache.return_value.get_value.return_value = {
            "access_token": "abc123",
            "token_type": "Bearer",
            "fetched_at": "2026-08-22T00:00:00",
            "expires_in": 3600,
        }

        headers = wb.get_headers(wb.EINVOICE)

        self.assertEqual(headers["Authorization"], "Bearer abc123")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_unknown_api_family_raises(self):
        with patch(
            "rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe"
        ) as mock_frappe:
            mock_frappe.throw.side_effect = frappe_throw_side_effect
            with self.assertRaises(RuntimeError):
                wb.get_headers("not-a-real-family")


class TestGetStaticClientHeaders(unittest.TestCase):
    """PUBLIC_GST (confirmed 2026-08-22 via WhiteBooks' GST-API Postman
    collection) sends client_id/client_secret as headers directly - no
    OAuth2 token endpoint exists for this family."""

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_returns_client_id_and_secret_as_headers(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=1)

        headers = wb.get_static_client_headers(wb.PUBLIC_GST)

        self.assertEqual(headers, {
            "client_id": "gst-sandbox-id",
            "client_secret": "secret-for-whitebooks_gst_sandbox_client_secret",
        })

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_uses_production_credentials_when_not_sandbox(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(sandbox_mode=0)

        headers = wb.get_static_client_headers(wb.PUBLIC_GST)

        self.assertEqual(headers["client_id"], "gst-prod-id")


class TestGetRegisteredEmail(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_returns_configured_email(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(
            whitebooks_gst_email="gsp@rigpl.com"
        )

        self.assertEqual(wb.get_registered_email(wb.PUBLIC_GST), "gsp@rigpl.com")

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_throws_when_email_not_configured(self, mock_frappe):
        mock_frappe.get_single.return_value = _fake_settings(whitebooks_gst_email=None)
        mock_frappe.throw.side_effect = frappe_throw_side_effect

        with self.assertRaises(RuntimeError):
            wb.get_registered_email(wb.PUBLIC_GST)


class TestRefreshSession(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_deletes_cached_token_for_that_family(self, mock_frappe):
        wb.refresh_session(wb.EINVOICE)
        mock_frappe.cache.return_value.delete_value.assert_called_once_with(
            "whitebooks_gsp_access_token_einvoice"
        )

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_requires_api_name(self, mock_frappe):
        mock_frappe.throw.side_effect = frappe_throw_side_effect
        with self.assertRaises(RuntimeError):
            wb.refresh_session()


class TestCallWithTokenRetry(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_succeeds_first_try_no_retry(self, mock_frappe):
        request_fn = MagicMock(return_value=_fake_response(200, {"ok": True}))

        response = wb.call_with_token_retry(request_fn, wb.EINVOICE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request_fn.call_count, 1)
        mock_frappe.cache.return_value.delete_value.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_retries_once_on_401_then_succeeds(self, mock_frappe):
        request_fn = MagicMock(
            side_effect=[_fake_response(401), _fake_response(200, {"ok": True})]
        )

        response = wb.call_with_token_retry(request_fn, wb.EINVOICE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request_fn.call_count, 2)
        mock_frappe.cache.return_value.delete_value.assert_called_once_with(
            "whitebooks_gsp_access_token_einvoice"
        )

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_gives_up_after_one_retry_still_401(self, mock_frappe):
        request_fn = MagicMock(return_value=_fake_response(401))

        response = wb.call_with_token_retry(request_fn, wb.EINVOICE)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(request_fn.call_count, 2)
        mock_frappe.cache.return_value.delete_value.assert_called_once()

    @patch("rohit_common.rohit_common.india_gst_api.whitebooks_provider.frappe")
    def test_non_401_failure_not_retried(self, mock_frappe):
        request_fn = MagicMock(return_value=_fake_response(500))

        response = wb.call_with_token_retry(request_fn, wb.EINVOICE)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(request_fn.call_count, 1)
        mock_frappe.cache.return_value.delete_value.assert_not_called()


if __name__ == "__main__":
    unittest.main()
