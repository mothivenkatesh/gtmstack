"""
Vercel Python serverless function — GET /api/transcript?url=&lang=&translate=

Vercel maps this file to the /api/transcript route automatically and bundles
sibling files in api/ (so `from _core import ...` resolves on deploy). The same
_core module backs the local Flask server in ../app.py.

Heads-up: YouTube IP-blocks datacenter ranges (Vercel included) much harder than
a home IP. Set WEBSHARE_PROXY_USER/PASS or YT_PROXY in the Vercel project's
Environment Variables to route fetches through a residential proxy.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from _core import fetch_transcript


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        url = (qs.get("url") or [""])[0]
        lang = (qs.get("lang") or [None])[0]
        translate = (qs.get("translate") or [None])[0]
        payload, status = fetch_transcript(url, lang, translate)
        self._send(payload, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
