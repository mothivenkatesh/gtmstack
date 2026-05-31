"""
Tests for api/_auth.py, the stateless HMAC token layer.

Pure crypto, no DB, no network. Covers the happy path, tamper rejection, expiry,
wrong-kind rejection, and fail-closed behaviour when APP_SECRET is unset.

Run:  python tests/test_auth.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import _auth  # noqa: E402


class AuthTests(unittest.TestCase):

    def setUp(self):
        os.environ["APP_SECRET"] = "test-secret-please-change"

    def tearDown(self):
        os.environ.pop("APP_SECRET", None)

    # ---- happy paths --------------------------------------------------------
    def test_magic_roundtrip(self):
        tok = _auth.magic_token("Founder@Stripe.com")
        self.assertEqual(_auth.read_magic(tok), "founder@stripe.com")  # normalised

    def test_session_roundtrip(self):
        tok = _auth.session_token(42, "a@b.com")
        s = _auth.read_session(tok)
        self.assertEqual(s, {"uid": 42, "email": "a@b.com"})

    # ---- kind isolation -----------------------------------------------------
    def test_magic_is_not_a_session(self):
        tok = _auth.magic_token("a@b.com")
        self.assertIsNone(_auth.read_session(tok))   # magic token rejected as session

    def test_session_is_not_a_magic(self):
        tok = _auth.session_token(1, "a@b.com")
        self.assertIsNone(_auth.read_magic(tok))

    # ---- tamper rejection ---------------------------------------------------
    def test_tampered_body_rejected(self):
        tok = _auth.session_token(1, "a@b.com")
        raw, sig = tok.rsplit(".", 1)
        forged = _auth._b64e(b'{"t":"sess","uid":999,"email":"x@y.com","exp":9999999999}')
        self.assertIsNone(_auth.verify(f"{forged}.{sig}"))

    def test_tampered_sig_rejected(self):
        tok = _auth.session_token(1, "a@b.com")
        raw, _sig = tok.rsplit(".", 1)
        self.assertIsNone(_auth.verify(f"{raw}.AAAA"))

    # ---- expiry -------------------------------------------------------------
    def test_expired_rejected(self):
        tok = _auth.sign({"t": "sess", "uid": 1, "email": "a@b.com"}, ttl_seconds=-1)
        self.assertIsNone(_auth.verify(tok))

    def test_unexpired_accepted(self):
        tok = _auth.sign({"t": "sess", "uid": 1, "email": "a@b.com"}, ttl_seconds=60)
        self.assertIsNotNone(_auth.verify(tok))

    # ---- fail closed --------------------------------------------------------
    def test_no_secret_signing_raises(self):
        os.environ.pop("APP_SECRET", None)
        with self.assertRaises(RuntimeError):
            _auth.magic_token("a@b.com")

    def test_no_secret_verify_returns_none(self):
        tok = _auth.session_token(1, "a@b.com")    # minted while secret set
        os.environ.pop("APP_SECRET", None)
        self.assertIsNone(_auth.verify(tok))       # fails closed, not open

    def test_secret_rotation_invalidates(self):
        tok = _auth.session_token(1, "a@b.com")
        os.environ["APP_SECRET"] = "a-different-secret"
        self.assertIsNone(_auth.verify(tok))       # old tokens die on rotation

    def test_garbage_rejected(self):
        for junk in ("", "no-dot", "a.b.c.d", "....", "x." + "y" * 10):
            self.assertIsNone(_auth.verify(junk))


if __name__ == "__main__":
    unittest.main(verbosity=2)
