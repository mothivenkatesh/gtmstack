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

# Vercel's Python builder finds a function by STATICALLY looking for a `handler`
# class statement. It does not follow `handler = make_handler(...)`, so every
# shim in this repo was invisible to it: the build reported "pattern does not
# match any Serverless Functions", produced a static-only site, and production
# silently kept serving an old deploy. Subclassing keeps the one-line shim while
# giving the builder the class statement it needs.
_Base = make_handler("auth")


class handler(_Base):
    pass