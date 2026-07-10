"""
Vercel function - daily keyword-group Signals report.
  GET  /api/report                 -> { groups, reports }  (index for the tab)
  GET  /api/report?groups=1        -> { groups }
  GET  /api/report?group=ID        -> the latest stored report for a group
  GET  /api/report?group=ID&list=1 -> { reports } index for that group
  GET  /api/report?id=REPORT_ID    -> one stored report
  POST /api/report  {group, sources?, budget_s?}  -> run a report now, return it

POST is the expensive path (it scans). When CRON_SECRET is set it must be sent as
the X-Cron-Secret header (so the public deploy is not a free scrape button); with
no secret set the endpoint stays open for local dev, like the other tools.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _groups import list_groups  # noqa: E402
from _report import run_report, reports_index, latest_report, get_report  # noqa: E402


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
        if q.get("groups"):
            return self._send({"groups": list_groups()})
        if q.get("id"):
            return self._send(get_report(q["id"][0]) or {"error": "not found"})
        gid = (q.get("group") or [None])[0]
        if gid and q.get("list"):
            return self._send({"reports": reports_index(gid)})
        if gid:
            return self._send(latest_report(gid) or {"error": "no report yet", "group_id": gid})
        self._send({"groups": list_groups(), "reports": reports_index()})

    def do_POST(self):
        secret = os.getenv("CRON_SECRET")
        if secret and self.headers.get("X-Cron-Secret") != secret:
            return self._send({"error": "unauthorized"}, 401)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._send({"error": "Send a JSON body."}, 400)
        report, status = run_report(
            body.get("group", ""),
            body.get("sources") or None,
            float(body.get("budget_s") or 45),
            body.get("use_llm"),
        )
        self._send(report, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cron-Secret")
        self.end_headers()
