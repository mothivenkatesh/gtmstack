"""
Vercel function - GTMstack harness: observability.
Core logic lives in api/_observe.py, shared with app.py through the registry.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("observe")
