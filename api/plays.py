"""
Vercel function — Plays (composite, agent-callable multi-step tools).
  GET  /api/plays   -> list available plays (metadata only)
  POST /api/plays   -> run a play: body { "play": id, "input": { ... } }

A play chains existing single-tool engines server-side and returns a steps[]
array an agent can branch on. Core logic lives in api/_plays.py, shared with
app.py. Runs INLINE: the response already carries every step's result, so
there is nothing to poll.

Phase 1 ships one play, 'video_messaging' (transcript -> dev-persona reactions);
see api/_plays.py for why the contact-axis plays wait for Phase-2 connectors.
"""
import json
from http.server import BaseHTTPRequestHandler

from _plays import list_plays, run_play


class handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json({"plays": list_plays()})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._json({"error": "Send a JSON body."}, 400)
        payload, status = run_play(body.get("play", ""), body.get("input") or {})
        self._json(payload, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
