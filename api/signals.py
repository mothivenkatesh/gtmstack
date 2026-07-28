"""
Vercel function — Signals (data intelligence layer).
  GET  /api/signals   -> per-source readiness (github / reddit / linkedin / x)
  POST /api/signals   -> { query, sources[], handles{}, force, unit } => footprint or feed

unit is person (default), company (footprint + the people who work there), or
keyword (a merged mentions feed). GitHub works with no config. LinkedIn needs
LI_AT + LI_JSESSIONID (or a LINKEDIN_COOKIES path). X reads the real timeline
with a connected session, else best-effort via the public syndication endpoint.
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
_Base = make_handler("signals")


class handler(_Base):
    pass