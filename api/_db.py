"""
Postgres data layer for GTMforce accounts and run history.

Env-gated on DATABASE_URL (Neon / Supabase / any Postgres). When it is unset, or
the driver is missing, configured() is False and every call degrades to a no-op:
the app runs exactly as it does today, anonymous and stateless. This mirrors the
rest of GTMforce, where each capability lights up only when its key is present.

Boring on purpose: one lazy connection per process (serverless reuses warm
instances), autocommit, parameterised SQL only. At ~100 concurrent the single
connection becomes the bottleneck; the fix is Neon's pooled endpoint plus a small
pool here (Phase 3), not a rewrite.
"""
from __future__ import annotations

import json
import os
import threading

try:
    import psycopg
except Exception:                      # driver absent -> feature simply off
    psycopg = None

_LOCK = threading.Lock()
_CONN = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id           BIGSERIAL PRIMARY KEY,
  email        TEXT UNIQUE NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runs (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
  tool       TEXT NOT NULL,
  summary    TEXT,
  input      JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_user_idx ON runs(user_id, created_at DESC);
"""


def configured() -> bool:
    return bool(os.getenv("DATABASE_URL") and psycopg)


def _conn():
    global _CONN
    if not configured():
        return None
    with _LOCK:
        if _CONN is None or getattr(_CONN, "closed", True):
            _CONN = psycopg.connect(os.getenv("DATABASE_URL"), autocommit=True)
    return _CONN


def _exec(run):
    """Run run(cursor) on a live connection. Reconnect once if the cached
    connection went stale: Neon (and any pooler) closes idle connections, but
    psycopg's `.closed` stays False, so a reused-but-dead connection raises on
    first use. Returns run()'s value, or None when the DB is not configured."""
    global _CONN
    err = None
    for _ in range(2):
        c = _conn()
        if not c:
            return None
        try:
            with c.cursor() as cur:
                return run(cur)
        except (psycopg.OperationalError, psycopg.InterfaceError) as e:
            err = e
            with _LOCK:
                try:
                    if _CONN is not None:
                        _CONN.close()
                except Exception:
                    pass
                _CONN = None
    if err:
        raise err


def init_db() -> bool:
    """Idempotent migration. Safe to call on every cold start."""
    if not configured():
        return False
    _exec(lambda cur: cur.execute(SCHEMA))
    return True


def upsert_user(email: str):
    """Create the user if new, else bump last_seen. Returns {id, email, created} or None."""
    email = (email or "").strip().lower()
    if not configured() or not email:
        return None

    def run(cur):
        cur.execute(
            "INSERT INTO users(email) VALUES(%s) "
            "ON CONFLICT(email) DO UPDATE SET last_seen_at=now() "
            "RETURNING id, email, (xmax = 0) AS created", (email,))
        return cur.fetchone()

    row = _exec(run)
    return {"id": row[0], "email": row[1], "created": bool(row[2])} if row else None


def save_run(user_id, tool: str, summary: str, input_obj) -> bool:
    """Append a run to a user's history. No-op for anonymous users."""
    if not configured() or not user_id:
        return False
    _exec(lambda cur: cur.execute(
        "INSERT INTO runs(user_id, tool, summary, input) VALUES(%s,%s,%s,%s)",
        (user_id, tool, (summary or "")[:280], json.dumps(input_obj or {})[:4000])))
    return True


def recent_runs(user_id, limit: int = 50):
    if not configured() or not user_id:
        return []

    def run(cur):
        cur.execute(
            "SELECT tool, summary, created_at FROM runs WHERE user_id=%s "
            "ORDER BY created_at DESC LIMIT %s", (user_id, int(limit)))
        return cur.fetchall()

    rows = _exec(run) or []
    return [{"tool": r[0], "summary": r[1], "at": r[2].isoformat()} for r in rows]


def stats() -> dict:
    """The 'we know who tried' read: how many signed up and ran something."""
    if not configured():
        return {"configured": False}

    def run(cur):
        cur.execute("SELECT count(*) FROM users")
        u = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM runs")
        r = cur.fetchone()[0]
        return (u, r)

    res = _exec(run) or (0, 0)
    return {"configured": True, "users": res[0], "runs": res[1]}
