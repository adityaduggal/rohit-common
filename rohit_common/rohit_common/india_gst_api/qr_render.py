#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Renders the e-Invoice QR from the raw IRP SignedQRCode string
(Sales Invoice.signed_qr_code), for print formats and the PNG backfill.

The parameters must stay the same as einv.attach_qrcode(), which made every
historical qrcode_image PNG. Then the printed QR is pixel-identical to the
old PNG, and qr_backfill.matches_original() can prove a decode is correct.
"""
import io

from pyqrcode import create as qrcreate

QR_ERROR_LEVEL = "L"
QR_SCALE = 2
QR_QUIET_ZONE = 1


def render_einvoice_qr_png(signed_qr_code: str) -> bytes:
    qr_image = io.BytesIO()
    qrcreate(signed_qr_code, error=QR_ERROR_LEVEL).png(
        qr_image, scale=QR_SCALE, quiet_zone=QR_QUIET_ZONE
    )
    return qr_image.getvalue()


def get_einvoice_qr_data_uri(signed_qr_code: str) -> str:
    """Jinja method (hooks.py jenv) for print formats: an <img src> value."""
    if not signed_qr_code:
        return ""
    base64_png = qrcreate(signed_qr_code, error=QR_ERROR_LEVEL).png_as_base64_str(
        scale=QR_SCALE, quiet_zone=QR_QUIET_ZONE
    )
    return f"data:image/png;base64,{base64_png}"
