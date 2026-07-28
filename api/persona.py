"""
Vercel function — Synthetic Dev Persona preview.
  GET  /api/persona            -> the persona roster (for the UI chips)
  POST /api/persona            -> { text, type, personas[] }  =>  reactions + scores

Set ANTHROPIC_API_KEY in the Vercel project env to upgrade reactions from the
built-in model to live Claude. Without it, the deterministic engine still runs.
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
_Base = make_handler("persona")


class handler(_Base):
    pass