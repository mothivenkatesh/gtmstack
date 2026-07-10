"""
Vercel cron - competitive monitor staleness watchdog.

Read-only and datacenter-safe: it does NOT scrape (that only works from the Mac's
residential IP + session). It reads the last monitor run time from Postgres and,
when the last successful run is older than MONITOR_STALE_HOURS (default 26), emails
MONITOR_ALERT_EMAIL. This is the one alarm that still fires when the Mac is asleep
or off, so a silently missed day is caught.

Scheduled in vercel.json crons. Also callable as GET for a manual check.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _monitor import staleness_hours, latest_run  # noqa: E402
try:
    import _email
except Exception:
    _email = None

STALE_HOURS = float(os.getenv("MONITOR_STALE_HOURS", "26"))


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        hours = staleness_hours()
        stale = hours is None or hours > STALE_HOURS
        alerted = False
        recipient = os.getenv("MONITOR_ALERT_EMAIL")
        if stale and recipient and _email:
            lr = latest_run() or {}
            when = "never" if hours is None else f"{hours}h ago"
            body = (f"The GTMstack competitive monitor has not run recently.\n"
                    f"Last successful run: {when}\n"
                    f"Last finished_at: {lr.get('finished_at', 'unknown')}\n"
                    f"Threshold: {STALE_HOURS}h\n\n"
                    f"Check that the Mac running the launchd job is awake and "
                    f"logged in.")
            try:
                _email.send(recipient, "[GTMstack] monitor is stale", body)
                alerted = True
            except Exception:
                pass
        self._send({"stale": stale, "hours": hours,
                    "threshold_hours": STALE_HOURS, "alerted": alerted})
