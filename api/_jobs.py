"""
GTMforce — Signals async jobs (the delivery layer).

Wraps the synchronous Signals engine in an async job surface so an agent can:
  - submit a lookup (single or bulk) and get a job id back right away,
  - poll job status (queued -> running -> done | error),
  - receive a webhook POST the moment the job finishes,
  - export the result as JSON or CSV (bulk export).

Two execution modes, one code path:
  - Local / long-lived (Flask): a ThreadPoolExecutor drains the queue in the
    background, so submit() returns instantly and the status transitions are
    real. The webhook fires from the worker thread on completion.
  - Serverless (Vercel): set SIGNALS_SYNC_JOBS=1. A background thread cannot
    outlive the request once the response is flushed, so submit() runs the job
    INLINE and returns it already "done" (result attached, no polling needed).

PHASE-2 GATES (not satisfied here): the job store is SQLite in a temp dir, which
is per-instance and ephemeral on serverless. A sold product needs a durable
queue + result store (QStash / Cloud Tasks / a real DB), webhook retries, and
per-tenant auth + rate budgets. This is the working single-tenant slice.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock

try:
    import requests  # noqa
except Exception:  # pragma: no cover
    requests = None

from _signals import lookup, to_csv, to_csv_bulk

_JOBS_DB = os.getenv("SIGNALS_JOBS_DB") or os.path.join(
    tempfile.gettempdir(), "gtmforce_jobs.db")
# Inline mode: process synchronously inside submit(). Default-on for serverless,
# where a background worker thread cannot outlive the request.
SYNC = os.getenv("SIGNALS_SYNC_JOBS", "").strip().lower() in ("1", "true", "yes")
MAX_BULK = int(os.getenv("SIGNALS_MAX_BULK", "50"))

_pool = None
_pool_lock = Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _db():
    conn = sqlite3.connect(_JOBS_DB, timeout=15, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS jobs ("
        "id TEXT PRIMARY KEY, kind TEXT, unit TEXT, status TEXT, "
        "request TEXT, result TEXT, error TEXT, webhook TEXT, "
        "created TEXT, updated TEXT)")
    return conn


_COLS = ("id,kind,unit,status,request,result,error,webhook,created,updated")


def _row_to_job(row, include_result=True):
    if not row:
        return None
    job = {
        "id": row[0], "kind": row[1], "unit": row[2], "status": row[3],
        "request": json.loads(row[4]) if row[4] else None,
        "error": row[6], "webhook": row[7],
        "created": row[8], "updated": row[9],
    }
    if include_result:
        job["result"] = json.loads(row[5]) if row[5] else None
    return job


def _get_row(conn, job_id):
    return conn.execute(f"SELECT {_COLS} FROM jobs WHERE id=?", (job_id,)).fetchone()


def _update(job_id, status, result=None, error=None):
    conn = _db()
    conn.execute(
        "UPDATE jobs SET status=?, result=?, error=?, updated=? WHERE id=?",
        (status, json.dumps(result) if result is not None else None,
         error, _now(), job_id))
    conn.commit()
    conn.close()


# ── worker pool (Flask / long-lived only) ───────────────────────────────────
def _pool_get():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=int(os.getenv("SIGNALS_WORKERS", "4")))
    return _pool


def _safe_process(job_id):
    try:
        _process(job_id)
    except Exception as e:  # never let a worker thread die silently
        _update(job_id, "error", error=f"{type(e).__name__}: {e}")


# ── public API ──────────────────────────────────────────────────────────────
def submit(request):
    """request: {kind, unit, query|queries, sources?, handles?, force?, webhook?}.
    kind defaults to 'lookup' ('bulk' fans out over queries). Returns the job
    dict; in SYNC mode it is already 'done' with the result attached."""
    kind = (request.get("kind") or "lookup").strip().lower()
    if kind not in ("lookup", "bulk"):
        kind = "lookup"
    unit = (request.get("unit") or "person").strip().lower()
    webhook = (request.get("webhook") or "").strip() or None
    job_id = uuid.uuid4().hex
    now = _now()

    conn = _db()
    conn.execute(
        f"INSERT INTO jobs ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (job_id, kind, unit, "queued", json.dumps(request),
         None, None, webhook, now, now))
    conn.commit()
    conn.close()

    if SYNC:
        _safe_process(job_id)
    else:
        _pool_get().submit(_safe_process, job_id)
    return get(job_id)


def get(job_id):
    conn = _db()
    row = _get_row(conn, job_id)
    conn.close()
    return _row_to_job(row)


def recent(limit=25):
    conn = _db()
    rows = conn.execute(
        f"SELECT {_COLS} FROM jobs ORDER BY created DESC LIMIT ?",
        (int(limit),)).fetchall()
    conn.close()
    return [_row_to_job(r, include_result=False) for r in rows]


def export(job_id, fmt="json"):
    """Return (body_text, content_type, filename) for a finished job, or
    (None, None, None) if the job is missing or not done yet."""
    job = get(job_id)
    if not job or job.get("status") != "done" or not job.get("result"):
        return None, None, None
    fmt = (fmt or "json").strip().lower()
    result = job["result"]
    short = job_id[:8]
    if fmt == "csv":
        if job["kind"] == "bulk":
            body = to_csv_bulk(result.get("items", []))
        else:
            body = to_csv(result)
        return body, "text/csv; charset=utf-8", f"signals_{short}.csv"
    return json.dumps(result, indent=2), "application/json", f"signals_{short}.json"


# ── execution ───────────────────────────────────────────────────────────────
def _process(job_id):
    conn = _db()
    row = _get_row(conn, job_id)
    conn.close()
    if not row:
        return
    job = _row_to_job(row)
    req = job["request"] or {}
    _update(job_id, "running")
    try:
        result = _run_bulk(req) if job["kind"] == "bulk" else _run_single(req)
    except Exception as e:
        _update(job_id, "error", error=f"{type(e).__name__}: {e}")
        _fire_webhook(job["webhook"], get(job_id))
        return
    _update(job_id, "done", result=result)
    _fire_webhook(job["webhook"], get(job_id))


def _run_single(req):
    payload, status = lookup(
        req.get("query", ""),
        req.get("sources") or None,
        req.get("handles") or None,
        bool(req.get("force")),
        req.get("unit") or "person",
    )
    if status >= 400:
        raise RuntimeError(payload.get("error") or f"lookup failed ({status})")
    return payload


def _run_bulk(req):
    queries = req.get("queries") or []
    if isinstance(queries, str):
        queries = re.split(r"[\n,]", queries)
    queries = [q for q in (str(x).strip() for x in queries) if q][:MAX_BULK]
    unit = req.get("unit") or "person"
    sources = req.get("sources") or None
    force = bool(req.get("force"))
    items = []
    for q in queries:
        try:
            payload, status = lookup(q, sources, None, force, unit)
            if status >= 400:
                items.append({"query": q,
                              "error": payload.get("error") or f"HTTP {status}"})
            else:
                items.append({"query": q, "payload": payload})
        except Exception as e:
            items.append({"query": q, "error": f"{type(e).__name__}: {e}"})
    return {"unit": unit, "count": len(items), "items": items}


def _fire_webhook(url, job):
    """Best-effort POST of the finished job to the caller's URL. Delivery
    guarantees + retries are a Phase-2 concern."""
    if not url or requests is None or not job:
        return
    body = {
        "id": job["id"], "kind": job["kind"], "unit": job["unit"],
        "status": job["status"], "error": job.get("error"),
        "result": job.get("result"),
    }
    try:
        requests.post(url, json=body, timeout=10,
                      headers={"User-Agent": "GTMforce-Signals/1.0",
                               "Content-Type": "application/json"})
    except Exception:
        pass
