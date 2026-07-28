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
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

# Vercel's Python builder finds a function by STATICALLY looking for a `handler`
# class statement. It does not follow `handler = make_handler(...)`, so every
# shim in this repo was invisible to it: the build reported "pattern does not
# match any Serverless Functions", produced a static-only site, and production
# silently kept serving an old deploy. Subclassing keeps the one-line shim while
# giving the builder the class statement it needs.
_Base = make_handler("monitor")


class handler(_Base):
    pass