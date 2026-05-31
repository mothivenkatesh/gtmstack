"""
Vercel function — Clean Data (deliverability layer).
  POST /api/clean                  -> validate + dedupe a contact list
  POST /api/clean?format=csv|json  -> same result, returned as a download
  POST /api/clean?only=clean       -> keep only the deliverable rows

Body: { text } (raw CSV / paste) or { emails: [...] }; optional check_smtp.
The response IS the clean data — agent-ready rows an agent can branch on
(valid boolean + verdict). Core logic lives in api/_clean.py, shared with app.py.

Serverless note: validation runs INLINE (the response already carries the
result). SMTP probes stay off because port 25 is blocked here; the MX +
heuristic layers do the separating without touching the mailbox.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _clean import clean, to_csv, to_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, text, ctype, filename):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        q = parse_qs(urlparse(self.path).query)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._json({"error": "Send a JSON body."}, 400)
        payload, status = clean(
            body.get("text", ""), body.get("emails") or None,
            bool(body.get("check_smtp")))
        fmt = ((q.get("format") or [body.get("format")])[0] or "").lower()
        if status == 200 and fmt in ("csv", "json"):
            only = ((q.get("only") or [body.get("only")])[0]) == "clean"
            if fmt == "csv":
                return self._file(to_csv(payload, only), "text/csv", "clean-emails.csv")
            return self._file(to_json(payload, only), "application/json", "clean-emails.json")
        self._json(payload, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
