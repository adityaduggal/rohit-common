#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for the pure crypto/signing helpers in gsp_session.py.

These run with plain `unittest` — no Frappe site/DB required — because they
only exercise `sign_getkey_request`, the AES pad/encrypt/decrypt helpers, and
`get_getkey_timestamp`, none of which touch `frappe.*`.

`get_session()` / `build_public_api_headers()` / `_fetch_new_session()` are
NOT covered here: they need `frappe.get_single`, `frappe.cache()`, and a live
(or recorded) TaxPro sandbox response. Those are integration-tested manually
against TaxPro sandbox per issue #7's acceptance criteria, and via
`test_gst_public_api.py` (bench test, requires a site) once #8/#9 land.

Run: /home/aditya/v12/env/bin/python -m pytest rohit_common/rohit_common/india_gst_api/test_gsp_session.py -v
"""
import base64
import os
import re
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from rohit_common.rohit_common.india_gst_api import gsp_session


class TestPKCS7Padding(unittest.TestCase):
    def test_pad_unpad_round_trip_various_lengths(self):
        for length in (0, 1, 15, 16, 17, 31, 32, 100):
            data = bytes(range(256))[:length] if length else b""
            padded = gsp_session._pkcs7_pad(data)
            self.assertEqual(len(padded) % 16, 0)
            self.assertEqual(gsp_session._pkcs7_unpad(padded), data)

    def test_pad_always_adds_at_least_one_byte(self):
        # A 16-byte-aligned input must still get a full extra block of padding
        # (PKCS7 requirement — otherwise unpad can't tell padding from data).
        data = b"A" * 16
        padded = gsp_session._pkcs7_pad(data)
        self.assertEqual(len(padded), 32)


class TestAESHelpers(unittest.TestCase):
    def test_encrypt_decrypt_round_trip_with_password_derived_key(self):
        password = "SomeTestAspPassword123"
        key = gsp_session._aes_key_from_password(password)
        self.assertEqual(len(key), 16)  # MD5 digest length -> valid AES-128 key

        plaintext = "hello-taxpro-gsp"
        ciphertext = gsp_session.encrypt_with_key(plaintext, key)
        decrypted = gsp_session._aes_decrypt_bytes(base64.b64decode(ciphertext), key)
        self.assertEqual(decrypted.decode("utf-8"), plaintext)

    def test_decrypt_enc_key_round_trip(self):
        # Simulate what TaxPro's GetKey response would contain: enc_key is
        # AspEK, AES/ECB/PKCS7-encrypted with a key derived from AspPassword.
        asp_password = "MyAspPassword"
        fake_asp_ek = os.urandom(16)  # what a real AspEK would look like
        key = gsp_session._aes_key_from_password(asp_password)
        enc_key_b64 = base64.b64encode(
            gsp_session._aes_encrypt_bytes(fake_asp_ek, key)
        ).decode("ascii")

        recovered = gsp_session.decrypt_enc_key(enc_key_b64, asp_password)
        self.assertEqual(recovered, fake_asp_ek)

    def test_encrypt_asp_secret_uses_asp_ek_as_key_directly(self):
        asp_ek_bytes = os.urandom(16)
        asp_password = "MyAspPassword"
        secret = gsp_session.encrypt_asp_secret(asp_password, asp_ek_bytes)
        # Round-trip: decrypting with the same key must recover AspPassword.
        recovered = gsp_session._aes_decrypt_bytes(base64.b64decode(secret), asp_ek_bytes)
        self.assertEqual(recovered.decode("utf-8"), asp_password)

    def test_wrong_key_does_not_silently_produce_original_plaintext(self):
        key = gsp_session._aes_key_from_password("password-one")
        wrong_key = gsp_session._aes_key_from_password("password-two")
        ciphertext = gsp_session.encrypt_with_key("secret-data", key)
        with self.assertRaises((ValueError, UnicodeDecodeError)):
            gsp_session._aes_decrypt_bytes(base64.b64decode(ciphertext), wrong_key).decode("utf-8")


class TestGetKeyTimestamp(unittest.TestCase):
    def test_format_is_ddmmyyyyhhmmssffffff(self):
        ts = gsp_session.get_getkey_timestamp()
        # 14 digits (ddMMyyyyHHmmss) + 6 digits (microseconds) = 20 digits total
        self.assertRegex(ts, r"^\d{20}$")
        day, month, year = ts[0:2], ts[2:4], ts[4:8]
        self.assertTrue(1 <= int(day) <= 31)
        self.assertTrue(1 <= int(month) <= 12)
        self.assertTrue(int(year) >= 2025)


class TestSignGetkeyRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        cls.tmp.write(cls.pem)
        cls.tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)

    def test_signature_verifies_against_public_key(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.exceptions import InvalidSignature

        aspid = "TESTASPID001"
        timestamp = gsp_session.get_getkey_timestamp()
        signed_content_b64 = gsp_session.sign_getkey_request(aspid, timestamp, self.tmp.name)
        signature = base64.b64decode(signed_content_b64)

        public_key = self.private_key.public_key()
        message = (aspid + timestamp).encode("utf-8")
        try:
            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            self.fail("signature did not verify against the matching public key")

    def test_signature_changes_with_different_timestamp(self):
        aspid = "TESTASPID001"
        sig1 = gsp_session.sign_getkey_request(aspid, "01012026000000000001", self.tmp.name)
        sig2 = gsp_session.sign_getkey_request(aspid, "01012026000000000002", self.tmp.name)
        self.assertNotEqual(sig1, sig2)

    def test_missing_private_key_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            gsp_session.sign_getkey_request("ASPID", "01012026000000000001", "/nonexistent/path.pem")


if __name__ == "__main__":
    unittest.main()
