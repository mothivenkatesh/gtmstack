"""
Vercel function - standing watches and the value surface.
POST is cron-gated; this is the endpoint the scheduler hits.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("watch")
