"""
Vercel function - CRM sync (HubSpot). Core logic in api/_crm.py.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

_Base = make_handler("crm")


class handler(_Base):
    pass
