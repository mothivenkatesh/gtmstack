"""
Vercel cron - competitive monitor staleness watchdog.

Read-only and datacenter-safe: it does NOT scrape (that only works from the Mac's
residential IP + session). It reads the last monitor run time from Postgres and,
when the last successful run is older than MONITOR_STALE_HOURS (default 26), emails
MONITOR_ALERT_EMAIL. This is the one alarm that still fires when the Mac is asleep
or off, so a silently missed day is caught.

Scheduled in vercel.json crons. Also callable as GET for a manual check.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("watchdog")
