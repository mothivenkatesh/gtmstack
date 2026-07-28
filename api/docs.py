"""
Vercel function - durable documents and first-party analytics.
Core logic in api/_docs.py, shared with app.py through the registry.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

_Base = make_handler("docs")


class handler(_Base):
    pass
