"""
Stateless auth tokens for GTMstack accounts.

Two token kinds, same mechanism: an HMAC-signed, time-limited payload of the form
"body.sig" where body is url-safe-base64(JSON). No secret material lives in the
token, only a signed claim, so verification needs no database round trip.

  - magic token  : emailed sign-in link, short TTL (15 min), single claim {email}.
  - session token : the cookie after sign-in, long TTL (30 days), {uid, email}.

Gated on APP_SECRET. Pure stdlib (hmac / hashlib / base64 / json / time), no deps,
so the whole thing is unit-testable with no network and no DB. Signing raises if
APP_SECRET is unset; verification simply returns None, so a missing secret fails
closed (nobody is authenticated) rather than open.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

MAGIC_TTL = 15 * 60            # sign-in link lives 15 minutes
SESSION_TTL = 30 * 24 * 3600   # session cookie lives 30 days


def _secret() -> bytes:
    return (os.getenv("APP_SECRET") or "").encode("utf-8")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, ttl_seconds: int) -> str:
    """payload -> 'body.sig'. Adds an absolute expiry. Raises if APP_SECRET unset."""
    secret = _secret()
    if not secret:
        raise RuntimeError("APP_SECRET is not set; cannot mint tokens.")
    body = dict(payload)
    body["exp"] = int(time.time()) + int(ttl_seconds)
    raw = _b64e(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(secret, raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def verify(token: str, kind: str | None = None) -> dict | None:
    """Return the payload if the signature is valid and unexpired, else None.
    Fails closed: no secret, bad signature, malformed body, or wrong kind -> None.
    Signature comparison is constant-time."""
    secret = _secret()
    if not secret or not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expect = _b64e(hmac.new(secret, raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        body = json.loads(_b64d(raw))
    except Exception:
        return None
    if int(body.get("exp", 0)) < int(time.time()):
        return None
    if kind is not None and body.get("t") != kind:
        return None
    return body


def magic_token(email: str) -> str:
    return sign({"t": "magic", "email": (email or "").strip().lower()}, MAGIC_TTL)


def session_token(user_id, email: str) -> str:
    return sign({"t": "sess", "uid": user_id, "email": (email or "").strip().lower()},
                SESSION_TTL)


def read_magic(token: str) -> str | None:
    """A valid magic token -> the email it authorizes, else None."""
    body = verify(token, kind="magic")
    return body.get("email") if body else None


def read_session(token: str) -> dict | None:
    """A valid session token -> {uid, email}, else None."""
    body = verify(token, kind="sess")
    return {"uid": body["uid"], "email": body["email"]} if body else None
