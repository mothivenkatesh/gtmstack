"""
Vercel function - the single dispatcher for every /api/* route.

One function, not nineteen. Vercel's Hobby plan caps a deployment at 12
Serverless Functions, and this app has 19 endpoints, so per-endpoint shims
cannot deploy at all. Routing every /api/* path into one function through the
same REGISTRY is both the fix and the better shape: app.py has always dispatched
this way, so the local and deployed servers now share one code path instead of
drifting apart.

The `class handler` statement is deliberate. Vercel's Python builder finds a
function by statically looking for it; it does not follow `handler = f()`.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

_Base = make_handler()          # no module id: resolved from the request path


class handler(_Base):
    pass
