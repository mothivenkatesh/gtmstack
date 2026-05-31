"""
Vercel function — Signals (data intelligence layer).
  GET  /api/signals   -> per-source readiness (github / reddit / linkedin / x)
  POST /api/signals   -> { query, sources[], handles{}, force, unit } => footprint or feed

unit is person (default), company (footprint + the people who work there), or
keyword (a merged mentions feed). GitHub works with no config. LinkedIn needs
LI_AT + LI_JSESSIONID (or a LINKEDIN_COOKIES path). X reads the real timeline
with a connected session, else best-effort via the public syndication endpoint.
"""
import json
from http.server import BaseHTTPRequestHandler

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _signals import lookup, sources_status  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"sources": sources_status()})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._send({"error": "Send a JSON body."}, 400)
        payload, status = lookup(
            body.get("query", ""),
            body.get("sources") or None,
            body.get("handles") or None,
            bool(body.get("force")),
            body.get("unit") or "person",
        )
        self._send(payload, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
