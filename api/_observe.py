"""
Observability - what the agents actually did, and whether it worked.

The premise: an autonomous system you cannot inspect is one you cannot trust,
and "trust me, it ran" is not an answer when the thing runs unattended and
writes to your CRM. RISK.md already flagged no-observability as a critical gap.

Three questions this has to answer, and nothing more, because a metrics system
nobody reads is its own kind of dead code:

  1. What happened just now?          -> `recent()`, the event stream
  2. Is it healthy?                   -> `metrics()`, rollups + error rate
  3. Why did it do that?              -> every event carries the rule or reason

Design notes:
  - Its own SQLite table, NOT graph nodes. Events are high-volume, append-only,
    and disposable; graph nodes are the durable business record. Mixing them
    would let telemetry drown the thing it observes.
  - `log()` NEVER raises. Telemetry that can break the request it measures is
    worse than no telemetry.
  - Bounded by construction: `PRUNE_KEEP` caps the table, so an unattended box
    cannot fill its disk with events.

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

PRUNE_KEEP = int(os.getenv("OBSERVE_KEEP", "5000"))

# Event kinds. Kept small and closed so the rollups stay meaningful.
RUN_START = "run_start"
RUN_END = "run_end"
STEP = "step"
DECISION = "decision"      # the approval engine allowed or blocked something
APPROVAL = "approval"      # a human answered
ERROR = "error"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event (
  id      TEXT PRIMARY KEY,
  ts      REAL NOT NULL,
  kind    TEXT NOT NULL,
  agent   TEXT,
  run_id  TEXT,
  ok      INTEGER,
  ms      REAL,
  summary TEXT,
  data    TEXT
);
CREATE INDEX IF NOT EXISTS ix_event_ts   ON event(ts);
CREATE INDEX IF NOT EXISTS ix_event_kind ON event(kind);
CREATE INDEX IF NOT EXISTS ix_event_run  ON event(run_id);
"""


def _db_path():
    p = os.getenv("OBSERVE_DB")
    if p:
        return p
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return os.path.join(tempfile.gettempdir(), "gtmstack_events.db")
    store = os.path.join(HERE, "_store")
    try:
        os.makedirs(store, exist_ok=True)
        return os.path.join(store, "events.db")
    except OSError:
        return os.path.join(tempfile.gettempdir(), "gtmstack_events.db")


def _conn():
    c = sqlite3.connect(_db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def log(kind, agent=None, run_id=None, ok=None, ms=None, summary="", **data):
    """Append one event. Swallows every error on purpose: observability must
    never be the reason a run fails."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO event (id,ts,kind,agent,run_id,ok,ms,summary,data)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (f"ev_{uuid.uuid4().hex[:12]}", time.time(), kind, agent, run_id,
                 None if ok is None else int(bool(ok)),
                 None if ms is None else float(ms),
                 str(summary)[:500], json.dumps(data, default=str)[:4000]))
    except Exception:                                            # noqa: BLE001
        pass


def _row(r):
    d = dict(r)
    try:
        d["data"] = json.loads(d.get("data") or "{}")
    except (ValueError, TypeError):
        d["data"] = {}
    return d


def recent(limit=60, kind=None, run_id=None):
    try:
        sql, args, where = "SELECT * FROM event", [], []
        if kind:
            where.append("kind=?"); args.append(kind)
        if run_id:
            where.append("run_id=?"); args.append(run_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        with _conn() as c:
            return [_row(r) for r in c.execute(sql, args).fetchall()]
    except Exception:                                            # noqa: BLE001
        return []


def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


def metrics(window_s=7 * 86400):
    """Rollups over a window. Everything here answers "is it healthy", so it is
    deliberately short: runs, success rate, latency, what is failing, and the
    approvals-shrink number the PRD calls the headline eval."""
    try:
        since = time.time() - window_s
        with _conn() as c:
            rows = [_row(r) for r in
                    c.execute("SELECT * FROM event WHERE ts>=? ORDER BY ts DESC",
                              (since,)).fetchall()]
    except Exception:                                            # noqa: BLE001
        return {"available": False}

    runs = [r for r in rows if r["kind"] == RUN_END]
    steps = [r for r in rows if r["kind"] == STEP]
    decisions = [r for r in rows if r["kind"] == DECISION]
    # A BLOCKED DECISION IS NOT AN ERROR. The gate refusing an ungranted write is
    # the system working exactly as designed, and counting it as a failure makes a
    # healthy install look broken, which trains people to ignore the error count.
    # Errors are explicit errors, or a non-decision event that failed.
    errors = [r for r in rows
              if r["kind"] == ERROR or (r["ok"] == 0 and r["kind"] != DECISION)]
    durations = [r["ms"] for r in runs if r["ms"] is not None]

    by_agent = {}
    for r in runs:
        a = r["agent"] or "unknown"
        b = by_agent.setdefault(a, {"runs": 0, "ok": 0, "failed": 0})
        b["runs"] += 1
        b["ok" if r["ok"] else "failed"] += 1

    top_errors = {}
    for e in errors:
        key = (e["summary"] or "unknown")[:120]
        top_errors[key] = top_errors.get(key, 0) + 1

    blocked = [d for d in decisions if not d["ok"]]
    return {
        "available": True,
        "window_days": round(window_s / 86400.0, 1),
        "runs": len(runs),
        "runs_ok": sum(1 for r in runs if r["ok"]),
        "runs_failed": sum(1 for r in runs if not r["ok"]),
        "success_rate": (round(100.0 * sum(1 for r in runs if r["ok"]) / len(runs), 1)
                         if runs else None),
        "steps": len(steps),
        "errors": len(errors),
        "p50_ms": _pct(durations, 50),
        "p95_ms": _pct(durations, 95),
        "by_agent": by_agent,
        "top_errors": sorted(({"error": k, "n": v} for k, v in top_errors.items()),
                             key=lambda x: -x["n"])[:5],
        "decisions": len(decisions),
        "blocked": len(blocked),
        "events": len(rows),
    }


def prune(keep=None):
    """Keep the table bounded. Called after each run so an unattended box cannot
    fill its disk."""
    keep = int(keep or PRUNE_KEEP)
    try:
        with _conn() as c:
            c.execute(
                "DELETE FROM event WHERE id NOT IN "
                "(SELECT id FROM event ORDER BY ts DESC LIMIT ?)", (keep,))
    except Exception:                                            # noqa: BLE001
        pass


def reset():
    try:
        with _conn() as c:
            c.execute("DELETE FROM event")
    except Exception:                                            # noqa: BLE001
        pass
