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
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("report")
