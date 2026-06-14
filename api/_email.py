"""
Magic-link email delivery for GTMstack sign-in.

Provider-agnostic and gated, like the rest of the app. If RESEND_API_KEY is set,
send via Resend's HTTP API (reuses requests, no SDK). Otherwise a dev fallback
hands the link back to the caller and logs it, so local and test runs work with no
email provider configured. send_magic_link() never raises; it returns a result
dict the route branches on.

MAIL_FROM defaults to Resend's shared onboarding sender, which only delivers to
your own verified address until you add a domain. Set MAIL_FROM to a verified
sender for real users.
"""
from __future__ import annotations

import os

try:
    import requests
except Exception:                      # pragma: no cover
    requests = None


def configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and requests)


def _from() -> str:
    return os.getenv("MAIL_FROM", "GTMstack <onboarding@resend.dev>")


def _html(link: str) -> str:
    return (
        '<div style="font-family:\'Zoho Puvi\',sans-serif;font-size:15px;color:#171717">'
        "<p>Click to sign in to GTMstack:</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 16px;'
        'background:#6846E3;color:#fff;border-radius:8px;text-decoration:none">'
        "Sign in</a></p>"
        "<p style=\"color:#6b6b6b;font-size:13px\">This link expires in 15 minutes. "
        "If you did not request it, ignore this email.</p></div>"
    )


def send_magic_link(email: str, link: str) -> dict:
    """Deliver the sign-in link. Returns one of:
      {"sent": True,  "mode": "resend"}
      {"sent": False, "mode": "dev", "link": link}     (no provider; caller may show it)
      {"sent": False, "mode": "resend", "error": ...}  (provider call failed)
      {"sent": False, "mode": "none", "error": ...}    (bad input)
    """
    email = (email or "").strip()
    if not email or "@" not in email:
        return {"sent": False, "mode": "none", "error": "invalid email"}
    if not configured():
        return {"sent": False, "mode": "dev", "link": link}
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
                     "Content-Type": "application/json"},
            json={"from": _from(), "to": [email],
                  "subject": "Your GTMstack sign-in link", "html": _html(link)},
            timeout=15)
        if r.status_code in (200, 201):
            return {"sent": True, "mode": "resend"}
        return {"sent": False, "mode": "resend", "error": f"HTTP {r.status_code}"}
    except Exception as e:                 # pragma: no cover
        return {"sent": False, "mode": "resend", "error": type(e).__name__}
