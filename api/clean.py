"""
Vercel function — Clean Data (deliverability layer).
  POST /api/clean                  -> validate + dedupe a contact list
  POST /api/clean?format=csv|json  -> same result, returned as a download
  POST /api/clean?only=clean       -> keep only the deliverable rows

Body: { text } (raw CSV / paste) or { emails: [...] }; optional check_smtp.
The response IS the clean data — agent-ready rows an agent can branch on
(valid boolean + verdict). Core logic lives in api/_clean.py, shared with app.py.

Serverless note: validation runs INLINE (the response already carries the
result). SMTP probes stay off because port 25 is blocked here; the MX +
heuristic layers do the separating without touching the mailbox.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("clean")
