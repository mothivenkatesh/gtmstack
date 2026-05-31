"""
Vercel serverless function for GTMstack sign-in. One file, action-routed:

  POST /api/auth            {action:"request", email}    -> send magic link
  GET  /api/auth?action=verify&token=...                 -> set cookie, 302 to app
  GET  /api/auth?action=me                               -> current user
  GET  /api/auth?action=runs                             -> run history
  POST /api/auth            {action:"logout"}            -> clear cookie
  POST /api/auth            {action:"run", tool, summary} -> append to history

The session cookie is HttpOnly + SameSite=Lax, and Secure on https. The logic
lives in _accounts so the Flask dev server runs the exact same flow.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

import _accounts  # noqa: E402


def _cookie_header(value: str, max_age: int) -> str:
    return (f"{_accounts.COOKIE}={value}; Path=/; HttpOnly; Secure; "
            f"SameSite=Lax; Max-Age={max_age}")


class handler(BaseHTTPRequestHandler):
    def _base(self):
        host = self.headers.get("host", "")
        proto = self.headers.get("x-forwarded-proto", "https")
        return f"{proto}://{host}"

    def _session_cookie(self):
        for part in (self.headers.get("cookie", "") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == _accounts.COOKIE:
                    return v
        return None

    def _json(self, payload, status=200, set_cookie=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location, set_cookie=None):
        self.send_response(302)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        action = (q.get("action") or [""])[0]
        if action == "verify":
            sess, ok, first = _accounts.consume_link((q.get("token") or [""])[0])
            if ok:
                return self._redirect("/?welcome=1" if first else "/",
                                      _cookie_header(sess, _accounts.SESSION_MAX_AGE))
            return self._redirect("/?auth=expired")
        if action == "me":
            return self._json(_accounts.whoami(self._session_cookie()))
        if action == "runs":
            return self._json(_accounts.list_runs(self._session_cookie()))
        return self._json({"error": "unknown action"}, 400)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._json({"error": "Send a JSON body."}, 400)
        action = body.get("action")
        if action == "request":
            payload, status = _accounts.request_link(body.get("email", ""), self._base())
            return self._json(payload, status)
        if action == "logout":
            return self._json({"ok": True}, 200, set_cookie=_cookie_header("", 0))
        if action == "run":
            return self._json(_accounts.record_run(
                self._session_cookie(), body.get("tool", ""), body.get("summary", "")))
        return self._json({"error": "unknown action"}, 400)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
