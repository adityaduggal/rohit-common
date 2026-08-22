#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Historical e-Invoice QR code backfill (T7, docs/designs/
gst-asp-migration-whitebooks.md).

`Sales Invoice.qrcode_image` holds a rendered PNG for every historical
e-invoice; the raw `SignedQRCode` string that PNG encodes was never
persisted anywhere (see einv.py's `attach_qrcode()`) and now has a home in
`signed_qr_code` (T6). This module decodes the existing PNGs back to text.

**Two-step process, not one patch — full manual runbook:
docs/qr-backfill-runbook.md.** Summary: `sample_decode_check()` first,
against real production data via bench console; only if it reports >= 95%
does `backfill_signed_qr_code()` (called by
`patches/v13/backfill_signed_qr_code.py`) get run. **This decision has NOT
been made as of 2026-08-22** — this module was written without access to a
live bench/site, so the sample check has never been run against real data.

**System dependency**: decoding needs `pyzbar` (added to requirements.txt)
which in turn needs the system-level `zbar` shared library (`libzbar0` on
Debian/Ubuntu, `zbar` via Homebrew) — a pip install of `pyzbar` alone is not
enough. Confirm `zbar` can be installed on the target bench before relying
on this — flagged, not yet confirmed, per the design doc's own note on this.

**Validation caveat**: `is_valid_signed_qr()` is a best-effort STRUCTURAL
sanity check (non-trivial length, decodable as UTF-8 text) — NOT a
cryptographic or schema validation against the real IRP-signed-QR format.
This repo doesn't have a confirmed reference sample of what a genuine
SignedQRCode payload looks like once decoded; tighten this once one is
available (e.g. from a real WhiteBooks sandbox e-invoice response, per The
Assignment).
"""
import random

import frappe

MIN_VALID_QR_LENGTH = 50


def _decode_bytes_to_text(png_bytes):
    """Decode a QR code PNG's bytes to its encoded text, or None if no QR
    code was found / it didn't decode. Imports are local so this module can
    be imported even on a machine without pyzbar/Pillow/zbar installed —
    only decode_qr_image() and its callers need them."""
    from io import BytesIO

    from PIL import Image
    from pyzbar.pyzbar import decode

    image = Image.open(BytesIO(png_bytes))
    results = decode(image)
    if not results:
        return None
    return results[0].data.decode("utf-8", errors="strict")


def decode_qr_image(file_url):
    """Fetch the File at file_url and decode its QR code to text.
    Returns (decoded_text_or_None, error_or_None) — never raises, so a
    single bad file doesn't abort a bulk backfill run."""
    try:
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        content = file_doc.get_content()
    except Exception as e:
        return None, f"could not read file content: {e}"

    try:
        decoded = _decode_bytes_to_text(content)
    except Exception as e:
        return None, f"decode error: {e}"

    if decoded is None:
        return None, "no QR code detected in image"
    return decoded, None


def is_valid_signed_qr(text):
    """Best-effort structural sanity check — see module docstring caveat.
    Not a real schema/signature validation."""
    if not text or not isinstance(text, str):
        return False
    if len(text) < MIN_VALID_QR_LENGTH:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _candidate_invoices():
    """Sales Invoices with a QR PNG attached but no raw signed_qr_code yet."""
    return frappe.get_all(
        "Sales Invoice",
        filters={"qrcode_image": ["is", "set"], "signed_qr_code": ["in", ["", None]]},
        fields=["name", "qrcode_image"],
    )


def sample_decode_check(sample_size=50):
    """Manual pre-check (see module docstring) — decode a random sample of
    real historical qrcode_image PNGs and report the success rate. Run this
    via bench console before deciding whether to run the bulk backfill.

    Returns a dict: {sampled, decoded, decode_rate, failures: [{name, error}]}.
    """
    candidates = _candidate_invoices()
    sample = random.sample(candidates, min(sample_size, len(candidates)))

    decoded_count = 0
    failures = []
    for row in sample:
        decoded, error = decode_qr_image(row["qrcode_image"])
        if decoded is not None and is_valid_signed_qr(decoded):
            decoded_count += 1
        else:
            failures.append({"name": row["name"], "error": error or "failed structural validation"})

    sampled = len(sample)
    decode_rate = (decoded_count / sampled) if sampled else 0.0
    report = {
        "sampled": sampled,
        "decoded": decoded_count,
        "decode_rate": decode_rate,
        "failures": failures,
    }
    print(
        f"QR backfill sample check: {decoded_count}/{sampled} decoded cleanly "
        f"({decode_rate:.1%}). {'PROCEED with backfill' if decode_rate >= 0.95 else 'DO NOT proceed — see design doc Option (b)'}."
    )
    return report


def backfill_signed_qr_code():
    """The actual bulk backfill — decode every candidate invoice's QR PNG
    and write signed_qr_code via db.set_value (patch-context write, no
    hooks fire; the transaction view-lock is unaffected — it's a read-time
    check, see the design doc's T7 correction). Per-invoice failures are
    logged (not silently skipped) and returned in the report so they're
    visible/reviewable, per the design's "not silently skipped" success
    criterion.

    Returns a dict: {total, backfilled, failed, failures: [{name, error}]}.
    """
    candidates = _candidate_invoices()
    backfilled = 0
    failures = []

    for row in candidates:
        decoded, error = decode_qr_image(row["qrcode_image"])
        if decoded is not None and is_valid_signed_qr(decoded):
            frappe.db.set_value(
                "Sales Invoice", row["name"], "signed_qr_code", decoded, update_modified=False
            )
            backfilled += 1
        else:
            failure_reason = error or "failed structural validation"
            failures.append({"name": row["name"], "error": failure_reason})
            frappe.log_error(
                title="QR backfill: invoice not backfilled",
                message=f"{row['name']}: {failure_reason}",
            )

    frappe.db.commit()

    report = {
        "total": len(candidates),
        "backfilled": backfilled,
        "failed": len(failures),
        "failures": failures,
    }
    print(
        f"QR backfill complete: {backfilled}/{len(candidates)} invoices backfilled, "
        f"{len(failures)} failed (see Error Log, title 'QR backfill: invoice not backfilled')."
    )
    return report
