"""
Vercel function - keyword group config.
  GET  /api/groups                       -> { groups }
  POST /api/groups  {id, ...fields}      -> create/edit a group (CRON_SECRET-gated)
  POST /api/groups  {id, delete:true}    -> remove a file-store override

Writes are CRON_SECRET-gated so the hosted deploy is read-only unless the header
is sent. Hand-editing api/_store/groups.json is the documented interim path.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _groups import list_groups, save_group, delete_group  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"groups": list_groups()})

    def do_POST(self):
        secret = os.getenv("CRON_SECRET")
        if secret and self.headers.get("X-Cron-Secret") != secret:
            return self._send({"error": "unauthorized"}, 401)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._send({"error": "Send a JSON body."}, 400)
        if body.get("delete"):
            return self._send({"ok": delete_group(body.get("id", ""))})
        saved = save_group(body)
        self._send({"group": saved} if saved else {"error": "bad group"},
                   200 if saved else 400)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cron-Secret")
        self.end_headers()
