"""
Vercel Python serverless function — GET /api/transcript?url=&lang=&translate=

Vercel maps this file to the /api/transcript route automatically and bundles
sibling files in api/ (so `from _core import ...` resolves on deploy). The same
_core module backs the local Flask server in ../app.py.

Heads-up: YouTube IP-blocks datacenter ranges (Vercel included) much harder than
a home IP. Set WEBSHARE_PROXY_USER/PASS or YT_PROXY in the Vercel project's
Environment Variables to route fetches through a residential proxy.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("transcript")
