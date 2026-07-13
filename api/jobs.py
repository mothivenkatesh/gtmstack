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

handler = make_handler("jobs")
