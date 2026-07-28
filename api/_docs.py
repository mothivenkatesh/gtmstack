"""
Document + event store. Postgres when DATABASE_URL is set, SQLite otherwise.

Exists because two things were living in the browser's localStorage, which is
not storage in any sense a product can rely on: it is per-browser, per-profile,
wiped by a cache clear, invisible to the server, and unshareable with a
teammate. A user who builds a table on their laptop and opens the app on their
phone should not find an empty app.

Two shapes, one module, because they are the same problem:
  docs    durable user documents (Tables). Read-modify-write by key.
  events  append-only product analytics. High volume, disposable, aggregated.

Analytics are FIRST-PARTY on purpose. No third-party script, no cookie banner,
no data leaving the deployment. It answers one question, which of these tools
does anyone actually use, and that is the evidence needed before deciding what
to cut.

No em dashes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))


def use_pg():
    try:
        import _db
        return _db.configured()
    except Exception:                                            # noqa: BLE001
        return False


def _sqlite_path():
    p = os.getenv("GTMSTACK_DOCS_DB")
    if p:
        return p
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return os.path.join(tempfile.gettempdir(), "gtmstack_docs.db")
    store = os.path.join(HERE, "_store")
    try:
        os.makedirs(store, exist_ok=True)
        return os.path.join(store, "docs.db")
    except OSError:
        return os.path.join(tempfile.gettempdir(), "gtmstack_docs.db")


_SQLITE = """
CREATE TABLE IF NOT EXISTS doc (
  key TEXT PRIMARY KEY, owner TEXT, kind TEXT NOT NULL,
  data TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_doc_kind ON doc(kind, owner);
CREATE TABLE IF NOT EXISTS event (
  id TEXT PRIMARY KEY, ts REAL NOT NULL, name TEXT NOT NULL,
  tool TEXT, session TEXT, data TEXT
);
CREATE INDEX IF NOT EXISTS ix_ev_ts ON event(ts);
CREATE INDEX IF NOT EXISTS ix_ev_tool ON event(tool);
"""

_PG = """
CREATE TABLE IF NOT EXISTS doc (
  key TEXT PRIMARY KEY, owner TEXT, kind TEXT NOT NULL,
  data JSONB NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_doc_kind ON doc(kind, owner);
CREATE TABLE IF NOT EXISTS event (
  id TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, name TEXT NOT NULL,
  tool TEXT, session TEXT, data JSONB
);
CREATE INDEX IF NOT EXISTS ix_ev_ts ON event(ts);
CREATE INDEX IF NOT EXISTS ix_ev_tool ON event(tool);
"""

_READY = False


def _sq():
    c = sqlite3.connect(_sqlite_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SQLITE)
    return c


def _pg(run):
    global _READY
    import _db
    if not _READY:
        _db._exec(lambda cur: cur.execute(_PG))
        _READY = True
    return _db._exec(run)


def backend():
    return "postgres" if use_pg() else "sqlite"


# ── documents ───────────────────────────────────────────────────────────────

def put(key, data, kind="table", owner=None):
    now = time.time()
    if use_pg():
        def run(cur):
            cur.execute(
                "INSERT INTO doc (key,owner,kind,data,updated_at) VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (key) DO UPDATE SET data=EXCLUDED.data,"
                " updated_at=EXCLUDED.updated_at, owner=COALESCE(EXCLUDED.owner, doc.owner)",
                (key, owner, kind, json.dumps(data), now))
            return key
        return _pg(run)
    with _sq() as c:
        c.execute("INSERT INTO doc (key,owner,kind,data,updated_at) VALUES (?,?,?,?,?)"
                  " ON CONFLICT(key) DO UPDATE SET data=excluded.data,"
                  " updated_at=excluded.updated_at, owner=COALESCE(excluded.owner, doc.owner)",
                  (key, owner, kind, json.dumps(data), now))
    return key


def _loads(v):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v or "null")
    except (ValueError, TypeError):
        return None


def get(key):
    if use_pg():
        def run(cur):
            cur.execute("SELECT data FROM doc WHERE key=%s", (key,))
            r = cur.fetchone()
            return _loads(r[0]) if r else None
        return _pg(run)
    with _sq() as c:
        r = c.execute("SELECT data FROM doc WHERE key=?", (key,)).fetchone()
    return _loads(r["data"]) if r else None


def delete(key):
    if use_pg():
        _pg(lambda cur: cur.execute("DELETE FROM doc WHERE key=%s", (key,)))
        return True
    with _sq() as c:
        c.execute("DELETE FROM doc WHERE key=?", (key,))
    return True


def listing(kind="table", owner=None, limit=100):
    if use_pg():
        def run(cur):
            sql = "SELECT key, updated_at FROM doc WHERE kind=%s"
            args = [kind]
            if owner:
                sql += " AND owner=%s"; args.append(owner)
            sql += " ORDER BY updated_at DESC LIMIT %s"; args.append(limit)
            cur.execute(sql, args)
            return [{"key": k, "updated_at": u} for k, u in cur.fetchall()]
        return _pg(run) or []
    sql, args = "SELECT key, updated_at FROM doc WHERE kind=?", [kind]
    if owner:
        sql += " AND owner=?"; args.append(owner)
    sql += " ORDER BY updated_at DESC LIMIT ?"; args.append(limit)
    with _sq() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


# ── analytics ───────────────────────────────────────────────────────────────

def track(name, tool=None, session=None, **data):
    """Record a product event. Never raises: analytics must not break the app
    it measures."""
    try:
        eid, now = f"ev_{uuid.uuid4().hex[:12]}", time.time()
        if use_pg():
            _pg(lambda cur: cur.execute(
                "INSERT INTO event (id,ts,name,tool,session,data) VALUES (%s,%s,%s,%s,%s,%s)",
                (eid, now, str(name)[:80], tool, session, json.dumps(data, default=str)[:2000])))
            return True
        with _sq() as c:
            c.execute("INSERT INTO event (id,ts,name,tool,session,data) VALUES (?,?,?,?,?,?)",
                      (eid, now, str(name)[:80], tool, session,
                       json.dumps(data, default=str)[:2000]))
        return True
    except Exception:                                            # noqa: BLE001
        return False


def usage(window_s=30 * 86400):
    """Which tools does anyone actually use. The question that decides what to
    cut, and the one this repo could not answer before."""
    since = time.time() - window_s
    try:
        if use_pg():
            def run(cur):
                cur.execute("SELECT tool, COUNT(*), COUNT(DISTINCT session) FROM event"
                            " WHERE ts>=%s AND tool IS NOT NULL GROUP BY tool"
                            " ORDER BY COUNT(*) DESC", (since,))
                rows = cur.fetchall()
                cur.execute("SELECT COUNT(*), COUNT(DISTINCT session) FROM event WHERE ts>=%s",
                            (since,))
                tot = cur.fetchone()
                return rows, tot
            rows, tot = _pg(run) or ([], (0, 0))
        else:
            with _sq() as c:
                rows = c.execute(
                    "SELECT tool, COUNT(*) n, COUNT(DISTINCT session) s FROM event"
                    " WHERE ts>=? AND tool IS NOT NULL GROUP BY tool ORDER BY n DESC",
                    (since,)).fetchall()
                rows = [(r["tool"], r["n"], r["s"]) for r in rows]
                t = c.execute("SELECT COUNT(*) n, COUNT(DISTINCT session) s FROM event"
                              " WHERE ts>=?", (since,)).fetchone()
                tot = (t["n"], t["s"])
        used = [{"tool": t, "events": n, "sessions": s} for t, n, s in rows]
        return {"window_days": round(window_s / 86400), "backend": backend(),
                "events": tot[0], "sessions": tot[1], "by_tool": used,
                "unused": [] if not used else None}
    except Exception:                                            # noqa: BLE001
        return {"available": False, "backend": backend()}


def reset():
    if use_pg():
        _pg(lambda cur: (cur.execute("DELETE FROM doc"), cur.execute("DELETE FROM event")))
        return
    with _sq() as c:
        c.execute("DELETE FROM doc")
        c.execute("DELETE FROM event")
