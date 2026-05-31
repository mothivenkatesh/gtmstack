"""
Account-flow controller for GTMforce sign-in, shared by the Vercel function
(api/auth.py) and the Flask dev server (app.py) so both speak the same logic.

Passwordless: request a magic link, click it, get a stateless HMAC session cookie.
Sign-in needs only APP_SECRET; the session token carries the identity, so staying
signed in needs no database. DATABASE_URL is additive: it records the user (so you
know who tried) and their run history. RESEND_API_KEY is additive: it delivers the
link by email. In local dev (GTMFORCE_DEV=1) with no email provider, the link is
returned to the caller so the flow works end to end with zero external services.
Production never leaks the link.
"""
from __future__ import annotations

import os

import _auth
import _db
from _email import send_magic_link

COOKIE = "gtmf_session"
SESSION_MAX_AGE = 30 * 24 * 3600


def _dev() -> bool:
    return os.getenv("GTMFORCE_DEV") == "1"


def _valid_email(email: str) -> bool:
    email = (email or "").strip()
    return "@" in email and "." in email.split("@")[-1] and len(email) <= 254


def request_link(email: str, base_url: str):
    """Mint a magic link and deliver it. Returns (payload, status)."""
    email = (email or "").strip().lower()
    if not _valid_email(email):
        return {"error": "Enter a valid email address."}, 400
    if not os.getenv("APP_SECRET"):
        return {"error": "Sign-in is not configured yet (APP_SECRET missing)."}, 503
    token = _auth.magic_token(email)
    link = f"{base_url.rstrip('/')}/api/auth?action=verify&token={token}"
    res = send_magic_link(email, link)
    if res.get("sent"):
        return {"ok": True, "mode": "email", "email": email}, 200
    if res.get("mode") == "dev" and _dev():
        return {"ok": True, "mode": "dev", "email": email, "link": link}, 200
    return {"ok": False, "mode": "unconfigured", "email": email,
            "error": "Email delivery is not set up. Add RESEND_API_KEY to send links."}, 503


def consume_link(token: str):
    """Verify a magic token and mint a session. Returns (session_token, ok, first_time)."""
    email = _auth.read_magic(token)
    if not email:
        return None, False, False
    uid, first_time = None, False
    if _db.configured():
        _db.init_db()
        user = _db.upsert_user(email)
        if user:
            uid = user["id"]
            first_time = bool(user.get("created"))
    return _auth.session_token(uid, email), True, first_time


def whoami(session_cookie: str):
    s = _auth.read_session(session_cookie or "")
    if not s:
        return {"anon": True}
    return {"anon": False, "email": s["email"], "uid": s.get("uid"),
            "persistent": bool(s.get("uid"))}


def record_run(session_cookie: str, tool: str, summary: str):
    s = _auth.read_session(session_cookie or "")
    if not s or not s.get("uid"):
        return {"saved": False}
    ok = _db.save_run(s["uid"], tool or "tool", summary or "", {})
    return {"saved": bool(ok)}


def list_runs(session_cookie: str):
    s = _auth.read_session(session_cookie or "")
    if not s:
        return {"runs": [], "anon": True}
    if not s.get("uid"):
        return {"runs": [], "anon": False, "no_db": True}
    return {"runs": _db.recent_runs(s["uid"]), "anon": False}
