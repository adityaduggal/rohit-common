#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for webhook.py (T9, docs/designs/gst-asp-migration-whitebooks.md)
— signature verification, IP allowlist, idempotency dedupe, and the
end-to-end entry point wiring. All mocked (frappe) — no live WhiteBooks
webhook call needed, since none of this is registered with WhiteBooks yet
(see the module docstring's two blocking dependencies).

Rate limiting itself (frappe.rate_limiter.rate_limit) is Frappe's own
tested code, not re-tested here — these tests confirm the decorator is
applied, not that Frappe's rate limiter works correctly.

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_webhook.py -v
"""
import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import webhook


class TestCheckIpAllowlist(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_empty_allowlist_is_not_enforced(self, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(whitebooks_webhook_ip_allowlist="")
        mock_frappe.local = SimpleNamespace(request_ip="203.0.113.5")

        webhook.check_ip_allowlist()  # must not raise

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_allowed_ip_passes(self, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(
            whitebooks_webhook_ip_allowlist="203.0.113.5, 198.51.100.1"
        )
        mock_frappe.local = SimpleNamespace(request_ip="198.51.100.1")

        webhook.check_ip_allowlist()  # must not raise

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_disallowed_ip_is_rejected(self, mock_frappe):
        mock_frappe.get_single.return_value = SimpleNamespace(
            whitebooks_webhook_ip_allowlist="203.0.113.5"
        )
        mock_frappe.local = SimpleNamespace(request_ip="192.0.2.1")
        mock_frappe.PermissionError = PermissionError
        mock_frappe.throw.side_effect = PermissionError

        with self.assertRaises(PermissionError):
            webhook.check_ip_allowlist()


class TestVerifyWebhookSignature(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_valid_signature_accepted(self, mock_frappe):
        secret = "shh-its-a-secret"
        rset = SimpleNamespace(get_password=MagicMock(return_value=secret))
        mock_frappe.get_single.return_value = rset
        body = b'{"submission_id": "abc123"}'
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        self.assertTrue(webhook.verify_webhook_signature(body, signature))

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_wrong_signature_rejected(self, mock_frappe):
        rset = SimpleNamespace(get_password=MagicMock(return_value="shh-its-a-secret"))
        mock_frappe.get_single.return_value = rset
        body = b'{"submission_id": "abc123"}'

        self.assertFalse(webhook.verify_webhook_signature(body, "0" * 64))

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_tampered_body_rejected(self, mock_frappe):
        secret = "shh-its-a-secret"
        rset = SimpleNamespace(get_password=MagicMock(return_value=secret))
        mock_frappe.get_single.return_value = rset
        original_body = b'{"submission_id": "abc123", "irn": "IRN-REAL"}'
        signature = hmac.new(secret.encode("utf-8"), original_body, hashlib.sha256).hexdigest()
        tampered_body = b'{"submission_id": "abc123", "irn": "IRN-FAKE"}'

        self.assertFalse(webhook.verify_webhook_signature(tampered_body, signature))

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_missing_signature_header_rejected(self, mock_frappe):
        self.assertFalse(webhook.verify_webhook_signature(b"body", None))
        self.assertFalse(webhook.verify_webhook_signature(b"body", ""))

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_unconfigured_secret_fails_closed(self, mock_frappe):
        """A blank secret must reject every request, not silently allow
        unsigned calls — per the module's 'fails closed' design."""
        rset = SimpleNamespace(get_password=MagicMock(return_value=None))
        mock_frappe.get_single.return_value = rset

        self.assertFalse(webhook.verify_webhook_signature(b"body", "any-signature-at-all"))


class TestProcessWebhookResult(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_unknown_submission_id_logs_error_and_does_not_raise(self, mock_frappe):
        mock_frappe.db.get_value.return_value = None

        webhook.process_webhook_result("unknown-id", {"irn": "IRN123"})

        mock_frappe.log_error.assert_called_once()
        mock_frappe.db.set_value.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_success_payload_updates_status_and_irn(self, mock_frappe):
        mock_frappe.db.get_value.return_value = SimpleNamespace(name="LOG-0001", status="Submitted")

        webhook.process_webhook_result("sub-123", {"irn": "IRN123", "status": "success"})

        mock_frappe.db.set_value.assert_called_once_with(
            "E-Invoice Submission Log", "LOG-0001", {"status": "Success", "irn": "IRN123"}
        )
        mock_frappe.db.commit.assert_called_once()

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_failure_payload_updates_status_and_error(self, mock_frappe):
        mock_frappe.db.get_value.return_value = SimpleNamespace(name="LOG-0002", status="Submitted")

        webhook.process_webhook_result("sub-456", {"error": "GSTIN mismatch"})

        mock_frappe.db.set_value.assert_called_once_with(
            "E-Invoice Submission Log",
            "LOG-0002",
            {"status": "Failed", "error_message": "GSTIN mismatch"},
        )

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_duplicate_delivery_for_already_success_is_not_reprocessed(self, mock_frappe):
        """Guards the webhook-idempotency requirement — a replayed delivery
        for an already-resolved submission must not double-apply."""
        mock_frappe.db.get_value.return_value = SimpleNamespace(name="LOG-0003", status="Success")

        webhook.process_webhook_result("sub-789", {"irn": "IRN123"})

        mock_frappe.db.set_value.assert_not_called()
        mock_frappe.db.commit.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_duplicate_delivery_for_already_failed_is_not_reprocessed(self, mock_frappe):
        mock_frappe.db.get_value.return_value = SimpleNamespace(name="LOG-0004", status="Failed")

        webhook.process_webhook_result("sub-999", {"irn": "IRN123"})

        mock_frappe.db.set_value.assert_not_called()


class TestWhitebooksEinvoiceWebhookEndpoint(unittest.TestCase):
    """Tests the whitelisted entry point's own wiring — order of checks,
    and that it calls through to the already-tested helper functions above
    rather than re-implementing their logic inline."""

    def _make_request(self, body, signature=None):
        request = MagicMock()
        request.get_data.return_value = body
        request.headers = {"X-WhiteBooks-Signature": signature} if signature else {}
        return request

    @patch("rohit_common.rohit_common.india_gst_api.webhook.process_webhook_result")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.verify_webhook_signature")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.check_ip_allowlist")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_happy_path_calls_process_webhook_result(
        self, mock_frappe, mock_check_ip, mock_verify_sig, mock_process
    ):
        body = b'{"submission_id": "abc123", "irn": "IRN123"}'
        mock_frappe.request = self._make_request(body, "sig")
        mock_frappe.parse_json.return_value = {"submission_id": "abc123", "irn": "IRN123"}
        mock_verify_sig.return_value = True

        result = webhook.whitebooks_einvoice_webhook.__wrapped__()

        mock_check_ip.assert_called_once()
        mock_verify_sig.assert_called_once_with(body, "sig")
        mock_process.assert_called_once_with("abc123", {"submission_id": "abc123", "irn": "IRN123"})
        self.assertEqual(result, {"status": "ok"})

    @patch("rohit_common.rohit_common.india_gst_api.webhook.process_webhook_result")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.verify_webhook_signature")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.check_ip_allowlist")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_invalid_signature_throws_before_processing(
        self, mock_frappe, mock_check_ip, mock_verify_sig, mock_process
    ):
        mock_frappe.request = self._make_request(b"{}", "bad-sig")
        mock_frappe.PermissionError = PermissionError
        mock_frappe.throw.side_effect = PermissionError
        mock_verify_sig.return_value = False

        with self.assertRaises(PermissionError):
            webhook.whitebooks_einvoice_webhook.__wrapped__()

        mock_process.assert_not_called()

    @patch("rohit_common.rohit_common.india_gst_api.webhook.process_webhook_result")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.verify_webhook_signature")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.check_ip_allowlist")
    @patch("rohit_common.rohit_common.india_gst_api.webhook.frappe")
    def test_missing_submission_id_throws_before_processing(
        self, mock_frappe, mock_check_ip, mock_verify_sig, mock_process
    ):
        mock_frappe.request = self._make_request(b'{"irn": "IRN123"}', "sig")
        mock_frappe.parse_json.return_value = {"irn": "IRN123"}
        mock_frappe.throw.side_effect = ValueError
        mock_verify_sig.return_value = True

        with self.assertRaises(ValueError):
            webhook.whitebooks_einvoice_webhook.__wrapped__()

        mock_process.assert_not_called()

    def test_endpoint_is_whitelisted_with_allow_guest(self):
        # frappe.whitelist(allow_guest=True) doesn't wrap the function or
        # set attributes on it — it registers the function by identity in
        # two module-level lists and returns it unchanged. This is a real
        # (unmocked) check against frappe's actual global registries,
        # confirming registration actually happened at import time.
        import frappe

        fn = webhook.whitebooks_einvoice_webhook
        self.assertIn(fn, frappe.whitelisted)
        self.assertIn(fn, frappe.guest_methods)

    def test_endpoint_is_rate_limited(self):
        # The rate_limit decorator wraps the function with functools.wraps,
        # so __wrapped__ points back to the original — confirms the
        # decorator is actually applied, without re-testing Frappe's own
        # rate limiter behavior.
        fn = webhook.whitebooks_einvoice_webhook
        self.assertTrue(hasattr(fn, "__wrapped__"))


if __name__ == "__main__":
    unittest.main()
