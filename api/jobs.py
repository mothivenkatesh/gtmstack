"""
Vercel function — Signals async jobs (delivery layer).
  POST /api/jobs                  -> submit a lookup (single or bulk) job
  GET  /api/jobs                  -> recent jobs
  GET  /api/jobs?id=X             -> one job (status + result)
  GET  /api/jobs?id=X&format=csv  -> export the finished job (csv | json)

Serverless note: a background worker thread cannot outlive the request, so jobs
run INLINE here (the response already carries the result). Durable async +
webhook retries are a Phase-2 concern; see api/_jobs.py.
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
_Base = make_handler("jobs")


class handler(_Base):
    pass