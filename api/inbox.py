"""
Vercel function - GTMstack harness: the Inbox.
The human-attention queue (approvals, questions, notifications). Logic lives in
the module registry, shared with app.py, so the two deployments cannot drift.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("inbox")
