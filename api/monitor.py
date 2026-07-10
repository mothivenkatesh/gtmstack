"""
Vercel function - competitive monitor.
  GET  /api/monitor                 -> { groups, last_run, mentions, sheet_url }
  GET  /api/monitor?group=ID        -> recent mentions for one group
  GET  /api/monitor?staleness=1     -> { hours } since the last run (watchdog)
  POST /api/monitor  {only?}        -> run the monitor now, return the summary

POST scans (expensive, and it needs the Mac's cookies + residential IP), so on
the hosted deploy it is CRON_SECRET-gated: without the header it 401s. The read
side is open like the Reports tab. On serverless the scan mostly degrades (no
local session), which is why the real run is the launchd job; POST here is for a
local run-now button and for cron-triggered catch-up.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _monitor import overview, run_monitor, staleness_hours  # noqa: E402
try:
    from _mentions import recent as recent_mentions
except Exception:
    def recent_mentions(*a, **k): return []


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("staleness"):
            return self._send({"hours": staleness_hours()})
        gid = (q.get("group") or [None])[0]
        if gid:
            return self._send({"group_id": gid, "mentions": recent_mentions(gid, 200)})
        self._send(overview())

    def do_POST(self):
        secret = os.getenv("CRON_SECRET")
        if secret and self.headers.get("X-Cron-Secret") != secret:
            return self._send({"error": "unauthorized"}, 401)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            body = {}
        summary = run_monitor(only=body.get("only"), catchup=bool(body.get("catchup")))
        self._send(summary)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cron-Secret")
        self.end_headers()
