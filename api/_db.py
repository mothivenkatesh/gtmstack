"""
Postgres data layer for GTMstack accounts and run history.

Env-gated on DATABASE_URL (Neon / Supabase / any Postgres). When it is unset, or
the driver is missing, configured() is False and every call degrades to a no-op:
the app runs exactly as it does today, anonymous and stateless. This mirrors the
rest of GTMstack, where each capability lights up only when its key is present.

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
CREATE TABLE IF NOT EXISTS reports (
  id           BIGSERIAL PRIMARY KEY,
  group_id     TEXT NOT NULL,
  group_name   TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_group_idx ON reports(group_id, generated_at DESC);
CREATE TABLE IF NOT EXISTS monitor_mentions (
  group_id     TEXT NOT NULL,
  dedup_key    TEXT NOT NULL,
  kind         TEXT,
  platform     TEXT,
  brand        TEXT,
  keyword      TEXT,
  body         TEXT,
  url          TEXT,
  author       TEXT,
  post_ts      TIMESTAMPTZ,
  rating       TEXT,
  sentiment    TEXT,
  company      TEXT,
  enrich_mode  TEXT,
  from_archive BOOLEAN DEFAULT false,
  snapshot_ts  TEXT,
  first_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_date     TEXT,
  PRIMARY KEY (group_id, dedup_key)
);
CREATE INDEX IF NOT EXISTS mentions_group_idx
  ON monitor_mentions(group_id, post_ts DESC);
CREATE INDEX IF NOT EXISTS mentions_lastseen_idx
  ON monitor_mentions(last_seen);
"""

# Columns the mention upsert writes, in order. Kept as one list so the INSERT and
# the VALUES tuple never drift apart.
_MENTION_COLS = ("group_id", "dedup_key", "kind", "platform", "brand", "keyword",
                 "body", "url", "author", "post_ts", "rating", "sentiment",
                 "company", "enrich_mode", "from_archive", "snapshot_ts", "run_date")


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


def init_db() -> bool:
    """Idempotent migration. Safe to call on every cold start."""
    c = _conn()
    if not c:
        return False
    with c.cursor() as cur:
        cur.execute(SCHEMA)
    return True


def upsert_user(email: str):
    """Create the user if new, else bump last_seen. Returns {id, email} or None."""
    email = (email or "").strip().lower()
    c = _conn()
    if not c or not email:
        return None
    with c.cursor() as cur:
        cur.execute(
            "INSERT INTO users(email) VALUES(%s) "
            "ON CONFLICT(email) DO UPDATE SET last_seen_at=now() "
            "RETURNING id, email, (xmax = 0) AS created", (email,))
        row = cur.fetchone()
    return {"id": row[0], "email": row[1], "created": bool(row[2])} if row else None


def save_run(user_id, tool: str, summary: str, input_obj) -> bool:
    """Append a run to a user's history. No-op for anonymous users."""
    c = _conn()
    if not c or not user_id:
        return False
    with c.cursor() as cur:
        cur.execute(
            "INSERT INTO runs(user_id, tool, summary, input) VALUES(%s,%s,%s,%s)",
            (user_id, tool, (summary or "")[:280],
             json.dumps(input_obj or {})[:4000]))
    return True


def recent_runs(user_id, limit: int = 50):
    c = _conn()
    if not c or not user_id:
        return []
    with c.cursor() as cur:
        cur.execute(
            "SELECT tool, summary, created_at FROM runs WHERE user_id=%s "
            "ORDER BY created_at DESC LIMIT %s", (user_id, int(limit)))
        rows = cur.fetchall()
    return [{"tool": r[0], "summary": r[1], "at": r[2].isoformat()} for r in rows]


def save_report(group_id: str, group_name: str, payload) -> bool:
    """Persist one daily report. No-op (returns False) when DB is not configured;
    the caller then falls back to a local JSON snapshot."""
    c = _conn()
    if not c or not group_id:
        return False
    with c.cursor() as cur:
        cur.execute(
            "INSERT INTO reports(group_id, group_name, payload) VALUES(%s,%s,%s)",
            (group_id, (group_name or "")[:120], json.dumps(payload or {})))
    return True


def list_reports(group_id=None, limit: int = 30):
    """Recent reports (newest first), optionally scoped to one group. Returns a
    light index: id + group + when + the synthesis summary, not the full payload."""
    c = _conn()
    if not c:
        return []
    with c.cursor() as cur:
        if group_id:
            cur.execute(
                "SELECT id, group_id, group_name, generated_at, "
                "payload->'synthesis'->>'summary' "
                "FROM reports WHERE group_id=%s ORDER BY generated_at DESC LIMIT %s",
                (group_id, int(limit)))
        else:
            cur.execute(
                "SELECT id, group_id, group_name, generated_at, "
                "payload->'synthesis'->>'summary' "
                "FROM reports ORDER BY generated_at DESC LIMIT %s", (int(limit),))
        rows = cur.fetchall()
    return [{"id": r[0], "group_id": r[1], "group_name": r[2],
             "generated_at": r[3].isoformat(), "summary": r[4]} for r in rows]


def get_report(report_id):
    c = _conn()
    if not c:
        return None
    with c.cursor() as cur:
        cur.execute("SELECT payload FROM reports WHERE id=%s", (int(report_id),))
        row = cur.fetchone()
    return row[0] if row else None


def latest_report(group_id):
    c = _conn()
    if not c or not group_id:
        return None
    with c.cursor() as cur:
        cur.execute(
            "SELECT payload FROM reports WHERE group_id=%s "
            "ORDER BY generated_at DESC LIMIT 1", (group_id,))
        row = cur.fetchone()
    return row[0] if row else None


def upsert_mentions(group_id, rows):
    """Upsert monitor mentions keyed (group_id, dedup_key). Returns the list of
    dedup_keys that were NEWLY inserted this call (the delta to export to Sheets).
    Existing rows just bump last_seen (so 'thread updated' is captured) and are
    NOT in the delta. No-op returning [] when the DB is not configured."""
    c = _conn()
    if not c or not group_id or not rows:
        return []
    inserted = []
    ph = "(" + ",".join(["%s"] * len(_MENTION_COLS)) + ")"
    sql = (f"INSERT INTO monitor_mentions ({','.join(_MENTION_COLS)}) VALUES {ph} "
           "ON CONFLICT (group_id, dedup_key) DO UPDATE SET "
           "last_seen=now(), sentiment=EXCLUDED.sentiment, company=EXCLUDED.company "
           "RETURNING dedup_key, (xmax = 0) AS was_insert")
    with c.cursor() as cur:
        for r in rows:
            vals = (
                group_id, r.get("dedup_key"), r.get("kind"),
                r.get("where") or r.get("platform"), r.get("brand"), r.get("keyword"),
                (r.get("text") or "")[:4000], r.get("url"), r.get("author"),
                r.get("ts") or None, str(r.get("rating")) if r.get("rating") is not None else None,
                r.get("sentiment"), r.get("company"), r.get("enrich_mode"),
                bool(r.get("from_archive")), r.get("snapshot_ts"), r.get("run_date"),
            )
            try:
                cur.execute(sql, vals)
                row = cur.fetchone()
                if row and row[1]:
                    inserted.append(row[0])
            except Exception:
                pass
    return inserted


def recent_mentions(group_id, limit: int = 200):
    c = _conn()
    if not c or not group_id:
        return []
    with c.cursor() as cur:
        cur.execute(
            "SELECT kind, platform, brand, keyword, body, url, author, post_ts, "
            "rating, sentiment, company, enrich_mode, from_archive, snapshot_ts, "
            "first_seen, last_seen FROM monitor_mentions WHERE group_id=%s "
            "ORDER BY post_ts DESC NULLS LAST, last_seen DESC LIMIT %s",
            (group_id, int(limit)))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("post_ts", "first_seen", "last_seen"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        out.append(d)
    return out


def prune_mentions(older_than_days: int = 180) -> int:
    """Retention: drop mentions whose last_seen is older than N days. Returns the
    row count removed. No-op returning 0 when DB unconfigured."""
    c = _conn()
    if not c:
        return 0
    with c.cursor() as cur:
        cur.execute(
            "DELETE FROM monitor_mentions "
            "WHERE last_seen < now() - (%s || ' days')::interval", (str(int(older_than_days)),))
        return cur.rowcount or 0


def _lock_key(name):
    """Stable 63-bit int from a lock name for pg advisory locks."""
    import hashlib
    return int(hashlib.sha1(name.encode()).hexdigest()[:15], 16)


def try_advisory_lock(name) -> bool:
    """Session-scoped single-flight lock. True if acquired, False if held by
    another session. Released by release_advisory_lock or when the connection
    closes (process exit). No-op returning True when DB unconfigured (the local
    file lock in _mentions covers that path)."""
    c = _conn()
    if not c:
        return True
    with c.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_lock_key(name),))
        return bool(cur.fetchone()[0])


def release_advisory_lock(name) -> None:
    c = _conn()
    if not c:
        return
    try:
        with c.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_lock_key(name),))
    except Exception:
        pass


def stats() -> dict:
    """The 'we know who tried' read: how many signed up and ran something."""
    c = _conn()
    if not c:
        return {"configured": False}
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        users = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM runs")
        runs = cur.fetchone()[0]
    return {"configured": True, "users": users, "runs": runs}
