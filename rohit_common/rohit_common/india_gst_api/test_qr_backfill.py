#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for qr_backfill.py (T7, docs/designs/gst-asp-migration-whitebooks.md)
— decode wiring, structural validation, sample-check reporting, and the
bulk backfill's per-invoice failure handling. All mocked (frappe, and
qr_backfill.decode_qr_image itself for the higher-level tests) — no live
site, no real pyzbar/Pillow/zbar install required to run these.

decode_qr_image() itself is tested against a mocked pyzbar/PIL (patched
into qr_backfill._decode_bytes_to_text's local imports via sys.modules) —
these tests do NOT prove real QR PNGs decode correctly, only that the
wiring around whatever pyzbar/PIL return is correct. That needs a real
pyzbar/zbar install and real historical qrcode_image data (The Assignment
/ sample_decode_check(), which has not been run against production data
as of this commit — see the module docstring in qr_backfill.py).

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_qr_backfill.py -v
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.india_gst_api import qr_backfill


class TestIsValidSignedQr(unittest.TestCase):
    def test_rejects_empty_string(self):
        self.assertFalse(qr_backfill.is_valid_signed_qr(""))

    def test_rejects_none(self):
        self.assertFalse(qr_backfill.is_valid_signed_qr(None))

    def test_rejects_too_short(self):
        self.assertFalse(qr_backfill.is_valid_signed_qr("short"))

    def test_accepts_long_enough_text(self):
        self.assertTrue(qr_backfill.is_valid_signed_qr("x" * qr_backfill.MIN_VALID_QR_LENGTH))

    def test_rejects_non_string(self):
        self.assertFalse(qr_backfill.is_valid_signed_qr(12345))


class TestDecodeBytesToText(unittest.TestCase):
    """Tests the thin pyzbar/PIL wrapper directly, by injecting fake
    pyzbar/PIL modules into sys.modules for the duration of the test — the
    real imports happen inside the function, so this doesn't need the real
    packages installed. Proves the wiring (open the image, decode, take the
    first result, utf-8-decode its .data) is correct; does NOT prove real
    QR PNGs decode correctly — that needs the real libraries and real data."""

    def setUp(self):
        self._orig_modules = {}
        for name in ("PIL", "PIL.Image", "pyzbar", "pyzbar.pyzbar"):
            self._orig_modules[name] = sys.modules.get(name)

    def tearDown(self):
        for name, mod in self._orig_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def _install_fake_pyzbar(self, decode_return):
        fake_pil = types.ModuleType("PIL")
        fake_pil_image = types.ModuleType("PIL.Image")
        fake_pil_image.open = MagicMock(return_value="fake-opened-image")
        fake_pil.Image = fake_pil_image
        sys.modules["PIL"] = fake_pil
        sys.modules["PIL.Image"] = fake_pil_image

        fake_pyzbar_pkg = types.ModuleType("pyzbar")
        fake_pyzbar_mod = types.ModuleType("pyzbar.pyzbar")
        fake_pyzbar_mod.decode = MagicMock(return_value=decode_return)
        fake_pyzbar_pkg.pyzbar = fake_pyzbar_mod
        sys.modules["pyzbar"] = fake_pyzbar_pkg
        sys.modules["pyzbar.pyzbar"] = fake_pyzbar_mod
        return fake_pyzbar_mod

    def test_returns_decoded_utf8_text_from_first_result(self):
        fake_result = MagicMock()
        fake_result.data = "signed-qr-payload".encode("utf-8")
        self._install_fake_pyzbar([fake_result])

        result = qr_backfill._decode_bytes_to_text(b"fake-png-bytes")

        self.assertEqual(result, "signed-qr-payload")

    def test_returns_none_when_no_results(self):
        self._install_fake_pyzbar([])

        result = qr_backfill._decode_bytes_to_text(b"fake-png-bytes")

        self.assertIsNone(result)


class TestDecodeQrImage(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_returns_decoded_text_on_success(self, mock_frappe):
        fake_file = MagicMock()
        fake_file.get_content.return_value = b"fake-png-bytes"
        mock_frappe.get_doc.return_value = fake_file

        with patch(
            "rohit_common.rohit_common.india_gst_api.qr_backfill._decode_bytes_to_text",
            return_value="decoded-signed-qr-payload-text-here",
        ):
            decoded, error = qr_backfill.decode_qr_image("/files/qr.png")

        self.assertEqual(decoded, "decoded-signed-qr-payload-text-here")
        self.assertIsNone(error)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_returns_error_when_file_cannot_be_read(self, mock_frappe):
        mock_frappe.get_doc.side_effect = Exception("file not found")

        decoded, error = qr_backfill.decode_qr_image("/files/missing.png")

        self.assertIsNone(decoded)
        self.assertIn("could not read file content", error)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_returns_error_when_no_qr_detected(self, mock_frappe):
        fake_file = MagicMock()
        fake_file.get_content.return_value = b"not-actually-a-qr-code"
        mock_frappe.get_doc.return_value = fake_file

        with patch(
            "rohit_common.rohit_common.india_gst_api.qr_backfill._decode_bytes_to_text",
            return_value=None,
        ):
            decoded, error = qr_backfill.decode_qr_image("/files/blank.png")

        self.assertIsNone(decoded)
        self.assertIn("no QR code detected", error)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_returns_error_on_decode_exception(self, mock_frappe):
        fake_file = MagicMock()
        fake_file.get_content.return_value = b"corrupt-bytes"
        mock_frappe.get_doc.return_value = fake_file

        with patch(
            "rohit_common.rohit_common.india_gst_api.qr_backfill._decode_bytes_to_text",
            side_effect=ValueError("corrupt PNG"),
        ):
            decoded, error = qr_backfill.decode_qr_image("/files/corrupt.png")

        self.assertIsNone(decoded)
        self.assertIn("decode error", error)


class TestSampleDecodeCheck(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_reports_decode_rate_across_sample(self, mock_frappe, mock_decode):
        candidates = [{"name": f"SINV-{i:04d}", "qrcode_image": f"/files/{i}.png"} for i in range(10)]
        mock_frappe.get_all.return_value = candidates

        # 9 decode cleanly, 1 fails.
        good_text = "x" * 100
        mock_decode.side_effect = [
            (good_text, None) if i < 9 else (None, "no QR code detected")
            for i in range(10)
        ]

        report = qr_backfill.sample_decode_check(sample_size=10)

        self.assertEqual(report["sampled"], 10)
        self.assertEqual(report["decoded"], 9)
        self.assertAlmostEqual(report["decode_rate"], 0.9)
        self.assertEqual(len(report["failures"]), 1)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_caps_sample_at_available_candidates(self, mock_frappe, mock_decode):
        candidates = [{"name": "SINV-0001", "qrcode_image": "/files/1.png"}]
        mock_frappe.get_all.return_value = candidates
        mock_decode.return_value = ("x" * 100, None)

        report = qr_backfill.sample_decode_check(sample_size=50)

        self.assertEqual(report["sampled"], 1)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_structurally_invalid_decode_counts_as_failure(self, mock_frappe, mock_decode):
        candidates = [{"name": "SINV-0001", "qrcode_image": "/files/1.png"}]
        mock_frappe.get_all.return_value = candidates
        # Decoded something, but too short to be a real signed-QR payload.
        mock_decode.return_value = ("short", None)

        report = qr_backfill.sample_decode_check(sample_size=1)

        self.assertEqual(report["decoded"], 0)
        self.assertEqual(len(report["failures"]), 1)


class TestBackfillSignedQrCode(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_backfills_successful_decodes_via_db_set_value(self, mock_frappe, mock_decode):
        mock_frappe.get_all.return_value = [
            {"name": "SINV-0001", "qrcode_image": "/files/1.png"},
        ]
        mock_decode.return_value = ("x" * 100, None)

        report = qr_backfill.backfill_signed_qr_code()

        mock_frappe.db.set_value.assert_called_once_with(
            "Sales Invoice", "SINV-0001", "signed_qr_code", "x" * 100, update_modified=False
        )
        self.assertEqual(report["backfilled"], 1)
        self.assertEqual(report["failed"], 0)

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_logs_and_reports_per_invoice_failures_not_silent(self, mock_frappe, mock_decode):
        """Guards the design's 'not silently skipped' success criterion."""
        mock_frappe.get_all.return_value = [
            {"name": "SINV-0001", "qrcode_image": "/files/1.png"},
            {"name": "SINV-0002", "qrcode_image": "/files/2.png"},
        ]
        mock_decode.side_effect = [
            ("x" * 100, None),
            (None, "no QR code detected in image"),
        ]

        report = qr_backfill.backfill_signed_qr_code()

        self.assertEqual(report["backfilled"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["failures"][0]["name"], "SINV-0002")
        mock_frappe.log_error.assert_called_once()
        log_call = mock_frappe.log_error.call_args
        self.assertIn("SINV-0002", log_call.kwargs["message"])

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_commits_after_processing_all_candidates(self, mock_frappe, mock_decode):
        mock_frappe.get_all.return_value = [
            {"name": "SINV-0001", "qrcode_image": "/files/1.png"},
        ]
        mock_decode.return_value = ("x" * 100, None)

        qr_backfill.backfill_signed_qr_code()

        mock_frappe.db.commit.assert_called_once()

    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.decode_qr_image")
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_no_candidates_is_a_clean_no_op(self, mock_frappe, mock_decode):
        mock_frappe.get_all.return_value = []

        report = qr_backfill.backfill_signed_qr_code()

        self.assertEqual(report["total"], 0)
        mock_decode.assert_not_called()
        mock_frappe.db.set_value.assert_not_called()


class TestCandidateInvoicesQuery(unittest.TestCase):
    @patch("rohit_common.rohit_common.india_gst_api.qr_backfill.frappe")
    def test_filters_for_qr_image_set_and_signed_qr_code_empty(self, mock_frappe):
        mock_frappe.get_all.return_value = []

        qr_backfill._candidate_invoices()

        call_kwargs = mock_frappe.get_all.call_args.kwargs
        self.assertEqual(call_kwargs["filters"]["qrcode_image"], ["is", "set"])
        self.assertEqual(call_kwargs["filters"]["signed_qr_code"], ["in", ["", None]])


if __name__ == "__main__":
    unittest.main()
