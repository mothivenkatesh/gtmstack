"""
Vercel function - GTMstack harness: cohorts.
Core logic lives in api/_cohorts.py (and the harness engines it imports), shared
with app.py through the module registry, so the two deployments cannot drift.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("cohorts")
