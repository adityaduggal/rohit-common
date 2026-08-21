#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
TaxPro GSP Public API (Search Taxpayer / Track Return) session auth.

TaxPro moved the Public API from aspid+password query-string auth to a
certificate-based session scheme effective 2025-03-01 (see
gsthelp.charteredinfo.com/ucl/{search_taxpayer,getkey_api}.htm). This flow:

1. RSA-SHA256-sign `aspid+timestamp` with the ASP's registered private key.
2. POST to GetKey to obtain `enc_key` (AES-encrypted AspEK) + `session_id`.
3. Decrypt `enc_key` with a key derived from AspPassword to get raw AspEK bytes.
4. AES/ECB/PKCS7-encrypt AspPassword using AspEK for the `asp-secret` header
   on subsequent Search/TrackReturn calls.

UNVERIFIED ASSUMPTION: TaxPro's docs describe the encryption algorithm
(AES/ECB/PKCS7) but not the exact derivation of an AES key from the plain
AspPassword string for step 3. `_aes_key_from_password` uses MD5(password),
a convention seen in comparable GSP client SDKs, but this has not been
confirmed against a live GetKey response. Verify against TaxPro sandbox
once a private key is deployed (issue #6) — this is an explicit acceptance
criterion of issue #7, not yet closed.
"""
import base64
import hashlib
import uuid
from datetime import datetime

import frappe
import requests
from Crypto.Cipher import AES
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TIMEOUT = 15
SESSION_CACHE_KEY = "gsp_public_api_session"
DEFAULT_VALIDITY_MIN = 20


def _get_settings():
    return frappe.get_single("Rohit Settings")


def _request_ip():
    return getattr(frappe.local, "request_ip", None) or "127.0.0.1"


def _new_txn_id():
    return uuid.uuid4().hex


def _pkcs7_pad(data, block_size=16):
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def _pkcs7_unpad(data):
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16 or pad_len > len(data):
        raise ValueError("Invalid PKCS7 padding while decrypting TaxPro GSP response")
    return data[:-pad_len]


def _aes_key_from_password(password):
    """Derive a 16-byte AES key from AspPassword. See module docstring caveat."""
    return hashlib.md5(password.encode("utf-8")).digest()


def _aes_encrypt_bytes(plaintext_bytes, key):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(_pkcs7_pad(plaintext_bytes))


def _aes_decrypt_bytes(ciphertext_bytes, key):
    cipher = AES.new(key, AES.MODE_ECB)
    return _pkcs7_unpad(cipher.decrypt(ciphertext_bytes))


def encrypt_with_key(plaintext, key):
    """AES/ECB/PKCS7-encrypt a UTF-8 string with a raw key, base64-encoded output."""
    return base64.b64encode(_aes_encrypt_bytes(plaintext.encode("utf-8"), key)).decode("ascii")


def decrypt_enc_key(enc_key_b64, asp_password):
    """Decrypt GetKey's enc_key (base64) using AspPassword-derived key.

    Returns raw AspEK bytes (NOT text — treat as opaque key material).
    """
    key = _aes_key_from_password(asp_password)
    return _aes_decrypt_bytes(base64.b64decode(enc_key_b64), key)


def encrypt_asp_secret(asp_password, asp_ek_bytes):
    """AES/ECB/PKCS7-encrypt AspPassword using raw AspEK bytes as the key."""
    return base64.b64encode(_aes_encrypt_bytes(asp_password.encode("utf-8"), asp_ek_bytes)).decode("ascii")


def get_getkey_timestamp():
    """ddMMyyyyHHmmssFFFFFF per TaxPro's GetKey docs."""
    return datetime.now().strftime("%d%m%Y%H%M%S%f")


def sign_getkey_request(aspid, timestamp, private_key_path):
    """RSA-SHA256-sign aspid+timestamp with the ASP's PEM private key, base64-encoded."""
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )
    message = (aspid + timestamp).encode("utf-8")
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def get_public_api_base_url(sandbox):
    return "https://gstsandbox.charteredinfo.com" if sandbox else "https://gstapi.charteredinfo.com"


def _fetch_new_session(rset):
    aspid = rset.tax_pro_asp_id
    asp_password = rset.tax_pro_password
    private_key_path = getattr(rset, "asp_private_key_path", None)
    if not private_key_path:
        frappe.throw(
            "Rohit Settings.asp_private_key_path is not configured or not yet "
            "synced to this site — run `bench --site <sitename> migrate`, then "
            "set the field. See docs/taxpro-asp-cert-setup.md (issue #6)"
        )

    timestamp = get_getkey_timestamp()
    signed_content = sign_getkey_request(aspid, timestamp, private_key_path)
    sandbox = bool(rset.sandbox_mode)
    url = get_public_api_base_url(sandbox) + "/aspapi/v1.0/getKey"
    headers = {
        "aspid": aspid,
        "txn": _new_txn_id(),
        "Content-Type": "application/json; charset=utf-8",
        "ip-usr": _request_ip(),
    }
    body = {"timestamp": timestamp, "signed_content": signed_content}
    resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("status_cd")) != "1":
        frappe.throw(f"TaxPro GetKey failed: {data.get('message') or data}")

    asp_ek = decrypt_enc_key(data["enc_key"], asp_password)
    validity_min = int(data.get("validity_min") or DEFAULT_VALIDITY_MIN)
    session = {
        "session_id": data["session_id"],
        "asp_ek_b64": base64.b64encode(asp_ek).decode("ascii"),
        "fetched_at": datetime.now().isoformat(),
        "validity_min": validity_min,
    }
    frappe.cache().set_value(SESSION_CACHE_KEY, session, expires_in_sec=validity_min * 60)
    return session


def get_session(force_refresh=False):
    """Returns a cached (or freshly fetched) session dict: session_id, asp_ek_b64, ..."""
    if not force_refresh:
        cached = frappe.cache().get_value(SESSION_CACHE_KEY)
        if cached:
            return cached
    return _fetch_new_session(_get_settings())


def build_public_api_headers(action, gstin, searchgstin=None, fiscal_year=None, type_of_return=None):
    """Headers + resolved request info for a Search/TrackReturn Public API call.

    Retries once with a forced session refresh if the first attempt's cached
    session turns out to be stale (caller passes retry_on_denied=True logic
    at the request layer — see gst_public_api.py).
    """
    rset = _get_settings()
    session = get_session()
    asp_ek = base64.b64decode(session["asp_ek_b64"])
    asp_secret = encrypt_asp_secret(rset.tax_pro_password, asp_ek)
    sandbox = bool(rset.sandbox_mode)
    headers = {
        "aspid": rset.tax_pro_asp_id,
        "asp-secret": asp_secret,
        "session-id": session["session_id"],
        "txn": _new_txn_id(),
        "ip-usr": _request_ip(),
        "Content-Type": "application/json; charset=utf-8",
    }
    return {
        "headers": headers,
        "base_url": get_public_api_base_url(sandbox),
        "sandbox": sandbox,
    }


def invalidate_session():
    """Drop the cached session — call after a REQUEST_DENIED/session-invalid response."""
    frappe.cache().delete_value(SESSION_CACHE_KEY)
