#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Tests for qr_backfill.py and qr_render.py (issue #17), against the real
zxing-cpp / pyqrcode / Pillow libraries and a real Sales Invoice on the site.

backfill_signed_qr_code() commits per batch, so frappe.db.commit is patched
to a no-op and every test rolls back in tearDown.

Run: bench --site <site> run-tests --module rohit_common.rohit_common.india_gst_api.test_qr_backfill
"""
import base64
import os
import unittest
from io import BytesIO
from unittest.mock import patch

import frappe
from PIL import Image

from rohit_common.rohit_common.india_gst_api import qr_backfill
from rohit_common.rohit_common.india_gst_api.qr_render import (
    get_einvoice_qr_data_uri,
    render_einvoice_qr_png,
)

# Same shape and length (~945 chars) as a real IRP SignedQRCode JWT.
SIGNED_QR = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjQ0NDQwNUM3ODFFNDgyNTA3MkIzNENB" + "".join(
    f"{i:04d}abcdefXYZ-_" for i in range(60)
)
OTHER_QR = SIGNED_QR[:-1] + "Q"


def _pixels(png_bytes):
    image = Image.open(BytesIO(png_bytes))
    return image.size, image.convert("1").tobytes()


class TestQrRender(unittest.TestCase):
    def test_decode_round_trip_of_rendered_png(self):
        png_bytes = render_einvoice_qr_png(SIGNED_QR)

        self.assertEqual(qr_backfill._decode_bytes_to_text(png_bytes), SIGNED_QR)

    def test_rendered_png_has_historical_qrcode_image_shape(self):
        # einv.attach_qrcode() PNGs are 1-bit, 2px modules, 1-module quiet zone.
        image = Image.open(BytesIO(render_einvoice_qr_png(SIGNED_QR)))

        self.assertEqual(image.mode, "1")
        self.assertEqual(image.size[0] % 2, 0)

    def test_matches_original_only_for_the_same_text(self):
        png_bytes = render_einvoice_qr_png(SIGNED_QR)

        self.assertTrue(qr_backfill.matches_original(SIGNED_QR, png_bytes))
        self.assertFalse(qr_backfill.matches_original(OTHER_QR, png_bytes))

    def test_data_uri_is_pixel_identical_to_rendered_png(self):
        data_uri = get_einvoice_qr_data_uri(SIGNED_QR)
        prefix = "data:image/png;base64,"

        self.assertTrue(data_uri.startswith(prefix))
        self.assertEqual(
            _pixels(base64.b64decode(data_uri[len(prefix):])),
            _pixels(render_einvoice_qr_png(SIGNED_QR)),
        )

    def test_data_uri_is_empty_for_empty_code(self):
        self.assertEqual(get_einvoice_qr_data_uri(""), "")
        self.assertEqual(get_einvoice_qr_data_uri(None), "")


class TestCheckDependencies(unittest.TestCase):
    def test_raises_with_install_steps_when_a_package_is_missing(self):
        real_import = qr_backfill.importlib.import_module

        def fake_import(name):
            if name == "zxingcpp":
                raise ImportError(name)
            return real_import(name)

        with patch.object(qr_backfill.importlib, "import_module", side_effect=fake_import):
            with self.assertRaises(frappe.ValidationError) as ctx:
                qr_backfill.check_dependencies()

        self.assertIn("zxing-cpp", str(ctx.exception))
        self.assertIn("bench setup requirements", str(ctx.exception))

    def test_passes_when_all_packages_are_installed(self):
        qr_backfill.check_dependencies()


class QrFileTestCase(unittest.TestCase):
    """Writes real PNGs to the site's private files folder."""

    def setUp(self):
        self.written_paths = []

    def tearDown(self):
        frappe.db.rollback()
        for path in self.written_paths:
            if os.path.exists(path):
                os.remove(path)

    def write_png(self, signed_qr):
        file_name = f"QRCode_test_{frappe.generate_hash(length=10)}.png"
        path = frappe.get_site_path("private", "files", file_name)
        with open(path, "wb") as png_file:
            png_file.write(render_einvoice_qr_png(signed_qr))
        self.written_paths.append(path)
        return f"/private/files/{file_name}"


class TestDecodeQrImage(QrFileTestCase):
    def test_decodes_and_verifies_a_real_file(self):
        file_url = self.write_png(SIGNED_QR)

        self.assertEqual(qr_backfill.decode_qr_image(file_url), (SIGNED_QR, None))

    def test_missing_file(self):
        decoded, error = qr_backfill.decode_qr_image("/private/files/QRCode_does_not_exist.png")

        self.assertIsNone(decoded)
        self.assertEqual(error, "file missing on disk")

    def test_rejects_urls_outside_the_files_folders(self):
        for file_url in ("/private/files/../site_config.json", "/etc/passwd", "", None):
            decoded, error = qr_backfill.decode_qr_image(file_url)
            self.assertIsNone(decoded)
            self.assertIn("unsupported file url", error)

    def test_image_without_a_qr_code(self):
        file_name = f"QRCode_test_{frappe.generate_hash(length=10)}.png"
        path = frappe.get_site_path("private", "files", file_name)
        Image.new("1", (214, 214), 1).save(path)
        self.written_paths.append(path)

        decoded, error = qr_backfill.decode_qr_image(f"/private/files/{file_name}")

        self.assertIsNone(decoded)
        self.assertEqual(error, "no QR code detected in image")


@patch("frappe.db.commit", new=lambda: None)
class TestBackfillSignedQrCode(QrFileTestCase):
    def setUp(self):
        super().setUp()
        names = frappe.get_all("Sales Invoice", filters={"docstatus": 1}, pluck="name", limit=2)
        if len(names) < 2:
            self.skipTest("needs 2 submitted Sales Invoices on the site")
        self.si_ok, self.si_missing = names
        frappe.db.set_value(
            "Sales Invoice", self.si_ok,
            {"qrcode_image": self.write_png(SIGNED_QR), "signed_qr_code": None},
            update_modified=False,
        )
        frappe.db.set_value(
            "Sales Invoice", self.si_missing,
            {"qrcode_image": "/private/files/QRCode_test_missing.png", "signed_qr_code": None},
            update_modified=False,
        )
        # The real candidate query, limited to the two test invoices.
        real_candidates = qr_backfill._candidate_invoices
        test_names = {self.si_ok, self.si_missing}
        candidates_patch = patch.object(
            qr_backfill, "_candidate_invoices",
            lambda: [row for row in real_candidates() if row["name"] in test_names],
        )
        candidates_patch.start()
        self.addCleanup(candidates_patch.stop)

    def test_backfills_and_reports_failures(self):
        report = qr_backfill.backfill_signed_qr_code()

        self.assertEqual(frappe.db.get_value("Sales Invoice", self.si_ok, "signed_qr_code"), SIGNED_QR)
        self.assertFalse(frappe.db.get_value("Sales Invoice", self.si_missing, "signed_qr_code"))
        self.assertEqual((report["total"], report["backfilled"], report["failed"]), (2, 1, 1))
        self.assertEqual(
            report["failures"], [{"name": self.si_missing, "error": "file missing on disk"}]
        )

    def test_logs_one_error_log_entry_for_all_failures(self):
        with patch.object(qr_backfill.frappe, "log_error") as log_error:
            qr_backfill.backfill_signed_qr_code()

        log_error.assert_called_once()
        self.assertIn(self.si_missing, log_error.call_args.kwargs["message"])

    def test_second_run_only_retries_the_failed_invoice(self):
        qr_backfill.backfill_signed_qr_code()

        report = qr_backfill.backfill_signed_qr_code()

        self.assertEqual((report["total"], report["backfilled"]), (1, 0))

    def test_sample_check_writes_nothing(self):
        report = qr_backfill.sample_decode_check(sample_size=10)

        self.assertEqual((report["sampled"], report["decoded"]), (2, 1))
        self.assertFalse(frappe.db.get_value("Sales Invoice", self.si_ok, "signed_qr_code"))

    def test_print_format_draws_qr_from_signed_qr_code(self):
        qr_backfill.backfill_signed_qr_code()

        html = frappe.get_print("Sales Invoice", self.si_ok, print_format="Domestic Invoice")

        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn(get_einvoice_qr_data_uri(SIGNED_QR), html)
