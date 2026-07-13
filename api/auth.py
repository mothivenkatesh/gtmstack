"""
Vercel serverless function for GTMstack sign-in. One file, action-routed:

  POST /api/auth            {action:"request", email}    -> send magic link
  GET  /api/auth?action=verify&token=...                 -> set cookie, 302 to app
  GET  /api/auth?action=me                               -> current user
  GET  /api/auth?action=runs                             -> run history
  POST /api/auth            {action:"logout"}            -> clear cookie
  POST /api/auth            {action:"run", tool, summary} -> append to history

The session cookie is HttpOnly + SameSite=Lax, and Secure on https. The logic
lives in _accounts so the Flask dev server runs the exact same flow.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("auth")
