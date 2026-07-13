"""
Vercel function - keyword group config.
  GET  /api/groups                       -> { groups }
  POST /api/groups  {id, ...fields}      -> create/edit a group (CRON_SECRET-gated)
  POST /api/groups  {id, delete:true}    -> remove a file-store override

Writes are CRON_SECRET-gated so the hosted deploy is read-only unless the header
is sent. Hand-editing api/_store/groups.json is the documented interim path.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("groups")
