"""
The revenue context graph - GTMstack's ontology, not a database.

One canonical model every agent reads and writes: Account, Person, Signal,
Cohort, Deal, Action, Outcome, KeyDefinition, ApprovalPolicy, AgentRun. Agents
are rows against this graph, never scripts with private state, which is what
makes multi-agent coordination and the learning loop possible.

Storage is Postgres when DATABASE_URL is set, SQLite otherwise. That split was
always the plan and it matters more than it looks: on serverless the SQLite file
lives in the temp dir and is destroyed on every cold start, so the graph the
whole moat argument rests on would silently reset. Postgres makes it durable.
Callers only use upsert/query/link/neighbours, so the swap stays inside this
module and nothing above it changes.

Everything an agent writes carries provenance: which agent, which run, and the
source it came from. No unsourced rows, ever, because the whole moat argument
rests on the outcome graph being auditable.

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


def _db_path():
    p = os.getenv("GTMSTACK_GRAPH_DB")
    if p:
        return p
    # Serverless has a READ-ONLY application directory; only the temp dir is
    # writable. The old check (makedirs with exist_ok) silently succeeded when
    # a bundled _store/ existed, so reads worked and the first write crashed the
    # function. Decide by platform, not by whether a directory happens to exist.
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return os.path.join(tempfile.gettempdir(), "gtmstack_graph.db")
    store = os.path.join(HERE, "_store")
    try:
        os.makedirs(store, exist_ok=True)
        return os.path.join(store, "graph.db")
    except OSError:
        return os.path.join(tempfile.gettempdir(), "gtmstack_graph.db")


# Every node type the ontology defines. One table, typed rows, because the shape
# varies per type and the value is in the edges plus the provenance, not in rigid
# columns. Queries stay fast with the type + key indexes below.
NODE_TYPES = (
    "account", "person", "signal", "cohort", "deal",
    "action", "outcome", "definition", "policy", "run", "watch",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS node (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  key        TEXT,
  data       TEXT NOT NULL,
  agent      TEXT,
  run_id     TEXT,
  source     TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_node_type     ON node(type);
CREATE INDEX IF NOT EXISTS ix_node_type_key ON node(type, key);
CREATE INDEX IF NOT EXISTS ix_node_created  ON node(created_at);

CREATE TABLE IF NOT EXISTS edge (
  id         TEXT PRIMARY KEY,
  src        TEXT NOT NULL,
  rel        TEXT NOT NULL,
  dst        TEXT NOT NULL,
  data       TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_edge_src ON edge(src, rel);
CREATE INDEX IF NOT EXISTS ix_edge_dst ON edge(dst, rel);
"""


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS node (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  key        TEXT,
  data       JSONB NOT NULL,
  agent      TEXT,
  run_id     TEXT,
  source     TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_node_type     ON node(type);
CREATE UNIQUE INDEX IF NOT EXISTS ux_node_type_key ON node(type, key) WHERE key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_node_created  ON node(created_at);
CREATE TABLE IF NOT EXISTS edge (
  id         TEXT PRIMARY KEY,
  src        TEXT NOT NULL,
  rel        TEXT NOT NULL,
  dst        TEXT NOT NULL,
  data       JSONB,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_edge ON edge(src, rel, dst);
CREATE INDEX IF NOT EXISTS ix_edge_src ON edge(src, rel);
"""

_PG_READY = False


def use_pg():
    """Postgres when DATABASE_URL is set and psycopg imports, else SQLite."""
    try:
        import _db
        return _db.configured()
    except Exception:                                            # noqa: BLE001
        return False


def _pg(run):
    """Run run(cursor) against Postgres, creating the schema once per process."""
    global _PG_READY
    import _db
    if not _PG_READY:
        _db._exec(lambda cur: cur.execute(_PG_SCHEMA))
        _PG_READY = True
    return _db._exec(run)


def _conn():
    c = sqlite3.connect(_db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _row(r):
    d = dict(r)
    try:
        d["data"] = json.loads(d.get("data") or "{}")
    except (ValueError, TypeError):
        d["data"] = {}
    return d


def _norm(r):
    """Normalise a row from either backend into the same dict shape."""
    d = dict(r)
    v = d.get("data")
    if isinstance(v, str):
        try:
            d["data"] = json.loads(v or "{}")
        except (ValueError, TypeError):
            d["data"] = {}
    elif v is None:
        d["data"] = {}
    return d


def upsert_ex(type_, data, key=None, agent=None, run_id=None, source=None, id=None):
    """upsert, but reports whether the node was CREATED or merely updated.

    Load-bearing, not cosmetic. A watch firing every six hours re-reads the same
    posts, and without this the run reports "19 new signals" forever: the user is
    told the same thing repeatedly and every value metric downstream inflates."""
    existed = False
    if key:
        if use_pg():
            existed = bool(_pg(lambda cur: (
                cur.execute("SELECT 1 FROM node WHERE type=%s AND key=%s", (type_, key)),
                cur.fetchone())[1]))
        else:
            with _conn() as c:
                existed = c.execute("SELECT 1 FROM node WHERE type=? AND key=?",
                                    (type_, key)).fetchone() is not None
    nid = upsert(type_, data, key=key, agent=agent, run_id=run_id,
                 source=source, id=id)
    return nid, (not existed)


def upsert(type_, data, key=None, agent=None, run_id=None, source=None, id=None):
    """Insert or update a node. `key` is the natural identity for the type, so a
    re-run updates rather than duplicates. That idempotency is what lets the job
    engine retry safely.

    Merges rather than replaces: a partial write must not silently drop fields a
    previous run set. Note the consequence, which has bitten before: a field is
    unset by writing None, not by omitting it."""
    if type_ not in NODE_TYPES:
        raise ValueError(f"unknown node type: {type_}")
    now = time.time()
    nid = id or f"{type_}_{uuid.uuid4().hex[:12]}"

    if use_pg():
        def run(cur):
            if key:
                cur.execute("SELECT id, data FROM node WHERE type=%s AND key=%s",
                            (type_, key))
                hit = cur.fetchone()
                if hit:
                    merged = hit[1] if isinstance(hit[1], dict) else json.loads(hit[1] or "{}")
                    merged.update(data or {})
                    cur.execute(
                        "UPDATE node SET data=%s, agent=COALESCE(%s,agent),"
                        " run_id=COALESCE(%s,run_id), source=COALESCE(%s,source),"
                        " updated_at=%s WHERE id=%s",
                        (json.dumps(merged), agent, run_id, source, now, hit[0]))
                    return hit[0]
            cur.execute(
                "INSERT INTO node (id,type,key,data,agent,run_id,source,created_at,updated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (id) DO NOTHING",
                (nid, type_, key, json.dumps(data or {}), agent, run_id, source, now, now))
            return nid
        return _pg(run)

    with _conn() as c:
        if key:
            hit = c.execute("SELECT id, data FROM node WHERE type=? AND key=?",
                            (type_, key)).fetchone()
            if hit:
                try:
                    merged = json.loads(hit["data"] or "{}")
                except (ValueError, TypeError):
                    merged = {}
                merged.update(data or {})
                c.execute(
                    "UPDATE node SET data=?, agent=COALESCE(?,agent), run_id=COALESCE(?,run_id),"
                    " source=COALESCE(?,source), updated_at=? WHERE id=?",
                    (json.dumps(merged), agent, run_id, source, now, hit["id"]))
                return hit["id"]
        c.execute(
            "INSERT INTO node (id,type,key,data,agent,run_id,source,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (nid, type_, key, json.dumps(data or {}), agent, run_id, source, now, now))
        return nid


_COLS = ("id", "type", "key", "data", "agent", "run_id", "source",
         "created_at", "updated_at")


def get(node_id):
    if use_pg():
        def run(cur):
            cur.execute(f"SELECT {','.join(_COLS)} FROM node WHERE id=%s", (node_id,))
            r = cur.fetchone()
            return _norm(dict(zip(_COLS, r))) if r else None
        return _pg(run)
    with _conn() as c:
        r = c.execute("SELECT * FROM node WHERE id=?", (node_id,)).fetchone()
    return _norm(r) if r else None


def query(type_=None, limit=200, since=None, where=None):
    """Read nodes. `where` is exact-match tests against the JSON data, applied in
    Python so callers stay free of SQL and the storage swap stays safe."""
    n = int(limit) * (4 if where else 1)
    if use_pg():
        def run(cur):
            sql = f"SELECT {','.join(_COLS)} FROM node"
            args, clauses = [], []
            if type_:
                clauses.append("type=%s"); args.append(type_)
            if since:
                clauses.append("created_at>=%s"); args.append(float(since))
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC LIMIT %s"
            args.append(n)
            cur.execute(sql, args)
            return [_norm(dict(zip(_COLS, r))) for r in cur.fetchall()]
        rows = _pg(run) or []
    else:
        sql, args, clauses = "SELECT * FROM node", [], []
        if type_:
            clauses.append("type=?"); args.append(type_)
        if since:
            clauses.append("created_at>=?"); args.append(float(since))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(n)
        with _conn() as c:
            rows = [_norm(r) for r in c.execute(sql, args).fetchall()]
    if where:
        rows = [r for r in rows
                if all(r["data"].get(k) == v for k, v in where.items())][:int(limit)]
    return rows


def link(src, rel, dst, data=None):
    eid = f"e_{uuid.uuid4().hex[:12]}"
    if use_pg():
        def run(cur):
            cur.execute("SELECT id FROM edge WHERE src=%s AND rel=%s AND dst=%s",
                        (src, rel, dst))
            hit = cur.fetchone()
            if hit:
                return hit[0]
            cur.execute("INSERT INTO edge (id,src,rel,dst,data,created_at)"
                        " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (eid, src, rel, dst, json.dumps(data or {}), time.time()))
            return eid
        return _pg(run)
    with _conn() as c:
        hit = c.execute("SELECT id FROM edge WHERE src=? AND rel=? AND dst=?",
                        (src, rel, dst)).fetchone()
        if hit:
            return hit["id"]
        c.execute("INSERT INTO edge (id,src,rel,dst,data,created_at) VALUES (?,?,?,?,?,?)",
                  (eid, src, rel, dst, json.dumps(data or {}), time.time()))
        return eid


def neighbours(node_id, rel=None):
    if use_pg():
        def run(cur):
            sql = "SELECT rel, dst FROM edge WHERE src=%s"
            args = [node_id]
            if rel:
                sql += " AND rel=%s"; args.append(rel)
            cur.execute(sql, args)
            edges = cur.fetchall()
            out = []
            for r, dst in edges:
                cur.execute(f"SELECT {','.join(_COLS)} FROM node WHERE id=%s", (dst,))
                nr = cur.fetchone()
                if nr:
                    out.append({"rel": r, "node": _norm(dict(zip(_COLS, nr)))})
            return out
        return _pg(run) or []
    sql, args = "SELECT * FROM edge WHERE src=?", [node_id]
    if rel:
        sql += " AND rel=?"; args.append(rel)
    with _conn() as c:
        edges = [dict(r) for r in c.execute(sql, args).fetchall()]
        out = []
        for e in edges:
            r = c.execute("SELECT * FROM node WHERE id=?", (e["dst"],)).fetchone()
            if r:
                out.append({"rel": e["rel"], "node": _norm(r)})
    return out


def counts():
    if use_pg():
        def run(cur):
            cur.execute("SELECT type, COUNT(*) FROM node GROUP BY type")
            by = {t: n for t, n in cur.fetchall()}
            cur.execute("SELECT COUNT(*) FROM edge")
            return {"by_type": by, "nodes": sum(by.values()),
                    "edges": cur.fetchone()[0], "backend": "postgres"}
        return _pg(run) or {"by_type": {}, "nodes": 0, "edges": 0, "backend": "postgres"}
    with _conn() as c:
        rows = c.execute("SELECT type, COUNT(*) n FROM node GROUP BY type").fetchall()
        edges = c.execute("SELECT COUNT(*) n FROM edge").fetchone()["n"]
    by = {r["type"]: r["n"] for r in rows}
    return {"by_type": by, "nodes": sum(by.values()), "edges": edges, "backend": "sqlite"}


def reset():
    """Wipe the graph. Used by tests and the demo seeder."""
    if use_pg():
        def run(cur):
            cur.execute("DELETE FROM edge")
            cur.execute("DELETE FROM node")
        _pg(run)
        return
    with _conn() as c:
        c.execute("DELETE FROM edge")
        c.execute("DELETE FROM node")
