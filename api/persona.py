"""
Vercel function — Synthetic Dev Persona preview.
  GET  /api/persona            -> the persona roster (for the UI chips)
  POST /api/persona            -> { text, type, personas[] }  =>  reactions + scores

Set ANTHROPIC_API_KEY in the Vercel project env to upgrade reactions from the
built-in model to live Claude. Without it, the deterministic engine still runs.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from _personas import preview, persona_roster


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"personas": persona_roster()})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._send({"error": "Send a JSON body."}, 400)
        payload, status = preview(
            body.get("text", ""),
            body.get("type", "landing"),
            body.get("personas") or None,
        )
        self._send(payload, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
