"""
The revenue context graph - GTMstack's ontology, not a database.

One canonical model every agent reads and writes: Account, Person, Signal,
Cohort, Deal, Action, Outcome, KeyDefinition, ApprovalPolicy, AgentRun. Agents
are rows against this graph, never scripts with private state, which is what
makes multi-agent coordination and the learning loop possible.

SQLite, same posture as _jobs.py: a local file under the store dir, overridable
by env. Serverless gets an ephemeral copy per cold start, which is fine because
the graph is a local-first prototype surface today; Postgres via DATABASE_URL is
the Phase 1 swap (the callers below only use upsert/query/link, so the storage
change stays inside this module).

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


def upsert_ex(type_, data, key=None, agent=None, run_id=None, source=None, id=None):
    """upsert, but reports whether the node was CREATED or merely updated.

    This distinction is load-bearing, not cosmetic. A watch firing every six
    hours re-reads the same posts, and without it the run reports "19 new
    signals" forever: the user gets told the same thing repeatedly and every
    value metric downstream is inflated. `new` has to mean new."""
    existed = False
    if key:
        with _conn() as c:
            existed = c.execute("SELECT 1 FROM node WHERE type=? AND key=?",
                                (type_, key)).fetchone() is not None
    nid = upsert(type_, data, key=key, agent=agent, run_id=run_id,
                 source=source, id=id)
    return nid, (not existed)


def upsert(type_, data, key=None, agent=None, run_id=None, source=None, id=None):
    """Insert or update a node. `key` is the natural identity for the type
    (domain for an account, platform:handle for a person, platform:post_id for a
    signal), so re-running an agent updates rather than duplicates. That
    idempotency is what lets the durable job engine retry safely."""
    if type_ not in NODE_TYPES:
        raise ValueError(f"unknown node type: {type_}")
    now = time.time()
    with _conn() as c:
        if key:
            hit = c.execute("SELECT id, data FROM node WHERE type=? AND key=?",
                            (type_, key)).fetchone()
            if hit:
                merged = {}
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
        nid = id or f"{type_}_{uuid.uuid4().hex[:12]}"
        c.execute(
            "INSERT INTO node (id,type,key,data,agent,run_id,source,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (nid, type_, key, json.dumps(data or {}), agent, run_id, source, now, now))
        return nid


def get(node_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM node WHERE id=?", (node_id,)).fetchone()
    return _row(r) if r else None


def query(type_=None, limit=200, since=None, where=None):
    """Read nodes. `where` is a dict of exact-match tests against the JSON data,
    applied in Python so callers stay free of SQL and the storage swap is safe."""
    sql, args = "SELECT * FROM node", []
    clauses = []
    if type_:
        clauses.append("type=?"); args.append(type_)
    if since:
        clauses.append("created_at>=?"); args.append(float(since))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit) * (4 if where else 1))
    with _conn() as c:
        rows = [_row(r) for r in c.execute(sql, args).fetchall()]
    if where:
        rows = [r for r in rows
                if all(r["data"].get(k) == v for k, v in where.items())][:int(limit)]
    return rows


def link(src, rel, dst, data=None):
    with _conn() as c:
        hit = c.execute("SELECT id FROM edge WHERE src=? AND rel=? AND dst=?",
                        (src, rel, dst)).fetchone()
        if hit:
            return hit["id"]
        eid = f"e_{uuid.uuid4().hex[:12]}"
        c.execute("INSERT INTO edge (id,src,rel,dst,data,created_at) VALUES (?,?,?,?,?,?)",
                  (eid, src, rel, dst, json.dumps(data or {}), time.time()))
        return eid


def neighbours(node_id, rel=None):
    sql = "SELECT * FROM edge WHERE src=?"
    args = [node_id]
    if rel:
        sql += " AND rel=?"; args.append(rel)
    with _conn() as c:
        edges = [dict(r) for r in c.execute(sql, args).fetchall()]
        out = []
        for e in edges:
            r = c.execute("SELECT * FROM node WHERE id=?", (e["dst"],)).fetchone()
            if r:
                out.append({"rel": e["rel"], "node": _row(r)})
    return out


def counts():
    with _conn() as c:
        rows = c.execute("SELECT type, COUNT(*) n FROM node GROUP BY type").fetchall()
        edges = c.execute("SELECT COUNT(*) n FROM edge").fetchone()["n"]
    by = {r["type"]: r["n"] for r in rows}
    return {"by_type": by, "nodes": sum(by.values()), "edges": edges}


def reset():
    """Wipe the graph. Used by the demo seeder so a fresh run is reproducible."""
    with _conn() as c:
        c.execute("DELETE FROM node")
        c.execute("DELETE FROM edge")
