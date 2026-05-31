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
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Force inline processing before the engine reads the flag at import time.
os.environ.setdefault("SIGNALS_SYNC_JOBS", "1")

import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _jobs import submit, get, recent, export  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, text, ctype, filename):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._json({"error": "Send a JSON body."}, 400)
        job = submit(body)
        done = bool(job and job.get("status") in ("done", "error"))
        self._json(job, 200 if done else 202)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        job_id = (q.get("id") or [None])[0]
        if not job_id:
            return self._json({"jobs": recent()})
        fmt = (q.get("format") or [None])[0]
        if fmt:
            text, ctype, fname = export(job_id, fmt)
            if text is None:
                return self._json({"error": "Job not finished or not found."}, 404)
            return self._file(text, ctype, fname)
        job = get(job_id)
        if not job:
            return self._json({"error": "Job not found."}, 404)
        self._json(job)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
