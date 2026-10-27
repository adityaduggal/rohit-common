#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Historical e-Invoice QR code backfill (issue #17, T7 of
docs/designs/gst-asp-migration-whitebooks.md).

`Sales Invoice.qrcode_image` holds a rendered PNG for every historical
e-invoice; the raw `SignedQRCode` string that PNG encodes was never
persisted (the Charteredinfo-era `attach_qrcode()`, removed 2026-10-27, kept
only the PNG). This module decodes the PNGs
back into `signed_qr_code`. Runbook: docs/qr-backfill-runbook.md.

A decode is accepted only if re-rendering the text with
qr_render.render_einvoice_qr_png() gives a pixel-identical PNG — that proves
the QR the print formats draw from `signed_qr_code` is the same QR as before.

Dependencies are pip-only (zxing-cpp, Pillow, pyqrcode, pypng — all in
requirements.txt); check_dependencies() fails loudly with install steps.
Imports are local so this module imports cleanly without them.
"""
import importlib
import random
import sys
from collections import defaultdict

import frappe

MIN_VALID_QR_LENGTH = 50
# Module name -> pip package name, as listed in requirements.txt.
REQUIRED_PACKAGES = {"zxingcpp": "zxing-cpp", "PIL": "Pillow", "pyqrcode": "pyqrcode", "png": "pypng"}
FILE_URL_FOLDERS = (("/private/files/", "private"), ("/files/", "public"))


def check_dependencies():
    missing = []
    for module_name, package in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(package)
    if missing:
        frappe.throw(
            f"Missing Python packages: {', '.join(missing)}. Install them, then migrate again "
            "(the patch is not marked as done, so it runs again):\n"
            "    cd <bench-root>\n"
            "    bench setup requirements --python\n"
            "    # or: ./env/bin/pip install -e apps/rohit_common\n"
            "    bench --site <site> migrate",
            title="E-Invoice QR backfill: missing Python packages",
        )


def _decode_bytes_to_text(png_bytes):
    """Decode a QR code PNG's bytes to its encoded text, or None if no QR
    code was found. The historical PNGs have a 1-module quiet zone, so a
    white border is added as a safety margin for the detector."""
    from io import BytesIO

    import zxingcpp
    from PIL import Image, ImageOps

    image = ImageOps.expand(Image.open(BytesIO(png_bytes)).convert("L"), border=8, fill=255)
    results = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    if not results:
        return None
    return results[0].text


def matches_original(text, png_bytes):
    """True if text re-renders to exactly the original PNG's pixels."""
    from io import BytesIO

    from PIL import Image

    from .qr_render import render_einvoice_qr_png

    original = Image.open(BytesIO(png_bytes))
    rendered = Image.open(BytesIO(render_einvoice_qr_png(text)))
    return (
        original.size == rendered.size
        and original.convert("1").tobytes() == rendered.convert("1").tobytes()
    )


def _site_path_for(file_url):
    """Disk path of a site file URL, or None if the URL is not a plain file
    directly under /files/ or /private/files/ (no subfolders, no '..')."""
    for prefix, folder in FILE_URL_FOLDERS:
        if file_url.startswith(prefix):
            file_name = file_url[len(prefix):]
            if file_name and "/" not in file_name and file_name not in (".", ".."):
                return frappe.get_site_path(folder, "files", file_name)
    return None


def decode_qr_image(file_url):
    """Read the PNG at file_url and decode it to a verified SignedQRCode.
    Returns (decoded_text_or_None, error_or_None) — never raises, so a
    single bad file doesn't abort a bulk backfill run."""
    path = _site_path_for(file_url or "")
    if not path:
        return None, f"unsupported file url: {file_url}"
    try:
        with open(path, "rb") as png_file:
            png_bytes = png_file.read()
    except FileNotFoundError:
        return None, "file missing on disk"
    except OSError as e:
        return None, f"could not read file: {e}"

    try:
        decoded = _decode_bytes_to_text(png_bytes)
    except Exception as e:
        return None, f"decode error: {e}"

    if decoded is None:
        return None, "no QR code detected in image"
    if not is_valid_signed_qr(decoded):
        return None, "failed structural validation"
    if not matches_original(decoded, png_bytes):
        return None, "re-rendered QR does not match the original PNG"
    return decoded, None


def is_valid_signed_qr(text):
    """Best-effort structural sanity check; matches_original() is the real proof."""
    if not text or not isinstance(text, str):
        return False
    return len(text) >= MIN_VALID_QR_LENGTH


def _candidate_invoices():
    """Sales Invoices with a QR PNG attached but no raw signed_qr_code yet."""
    return frappe.get_all(
        "Sales Invoice",
        filters={"qrcode_image": ["is", "set"], "signed_qr_code": ["in", ["", None]]},
        fields=["name", "qrcode_image"],
        order_by="name",
    )


def sample_decode_check(sample_size=50):
    """Manual pre-check: decode a random sample of real historical PNGs and
    report the success rate, without writing anything.

    Returns a dict: {sampled, decoded, decode_rate, failures: [{name, error}]}.
    """
    check_dependencies()
    candidates = _candidate_invoices()
    sample = random.sample(candidates, min(sample_size, len(candidates)))

    decoded_count = 0
    failures = []
    for row in sample:
        decoded, error = decode_qr_image(row["qrcode_image"])
        if decoded is not None:
            decoded_count += 1
        else:
            failures.append({"name": row["name"], "error": error})

    sampled = len(sample)
    decode_rate = (decoded_count / sampled) if sampled else 0.0
    print(f"QR backfill sample check: {decoded_count}/{sampled} decoded and verified ({decode_rate:.1%}).")
    return {
        "sampled": sampled,
        "decoded": decoded_count,
        "decode_rate": decode_rate,
        "failures": failures,
    }


def backfill_signed_qr_code():
    """Decode every candidate invoice's QR PNG and write signed_qr_code via
    db.set_value (no hooks fire; modified is not touched). Idempotent: only
    invoices with an empty signed_qr_code are selected, so a re-run after
    restoring missing files only touches the rows still left.

    Commits after each invoice, so an interrupted run keeps its work and the
    next run continues from there. Failures don't raise; they go into the
    returned report and one Error Log entry.

    Returns a dict: {total, backfilled, failed, failures: [{name, error}]}.
    """
    check_dependencies()
    candidates = _candidate_invoices()
    total = len(candidates)
    backfilled = 0
    failures = []
    print(f"QR backfill: {total} invoices to backfill", flush=True)

    for index, row in enumerate(candidates, start=1):
        decoded, error = decode_qr_image(row["qrcode_image"])
        if decoded is not None:
            frappe.db.set_value(
                "Sales Invoice", row["name"], "signed_qr_code", decoded, update_modified=False
            )
            frappe.db.commit()
            backfilled += 1
        else:
            failures.append({"name": row["name"], "error": error})
        _print_progress(index, total, backfilled, len(failures))

    if total:
        sys.stdout.write("\n")
    if failures:
        _log_failures(failures)

    print(
        f"QR backfill complete: {backfilled}/{total} invoices backfilled, {len(failures)} failed"
        + (" (see Error Log, title 'QR backfill: invoices not backfilled')." if failures else "."),
        flush=True,
    )
    return {
        "total": total,
        "backfilled": backfilled,
        "failed": len(failures),
        "failures": failures,
    }


def _print_progress(index, total, backfilled, failed):
    """One live status line, rewritten in place after every invoice."""
    sys.stdout.write(
        f"\rQR backfill: {index}/{total} ({index * 100 // total}%) processed, "
        f"{backfilled} backfilled, {failed} failed"
    )
    sys.stdout.flush()


def _log_failures(failures):
    """One Error Log entry for the whole run, grouped by reason — not one
    entry per invoice, which would be thousands when files are missing."""
    by_error = defaultdict(list)
    for failure in failures:
        by_error[failure["error"]].append(failure["name"])

    message = "\n\n".join(
        f"{error} ({len(names)}):\n{', '.join(names)}" for error, names in by_error.items()
    )
    frappe.log_error(title="QR backfill: invoices not backfilled", message=message)
    frappe.db.commit()
