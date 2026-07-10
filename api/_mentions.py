"""
GTMstack - monitor mentions store (system of record) + run lock.

One interface the monitor uses regardless of deploy: Postgres via _db when
DATABASE_URL is set (so the hosted Reports tab can read it), else a local JSON
file under _store/monitor/ (so local dev and a Mac launchd run still dedup across
runs without a database).

Dedup is KIND-AWARE. The first pass keyed on URL alone, so every comment in a
thread collapsed into the one post row. The key is <kind>:<id-or-hash>, so a
post, its comments, and a review of the same URL stay distinct. The primary key
is (group_id, dedup_key), so the same URL matched by two groups lands in both
group tabs, which the export needs.

No em dashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import _db
except Exception:
    _db = None

_STORE = Path(__file__).resolve().parent / "_store" / "monitor"
_LOCKS = _STORE / "locks"


# ---------------------------------------------------------------------------
# dedup key (kind-aware)
# ---------------------------------------------------------------------------

def dedup_key(m):
    """Stable, kind-aware dedup key for a mention. Prefers an explicit source id;
    else hashes url + a text prefix so two comments in one thread (same url,
    different text) do not collapse."""
    kind = (m.get("kind") or "post").lower()
    sid = m.get("id") or m.get("source_id")
    if sid:
        return f"{kind}:{sid}"
    basis = (m.get("url") or "") + "|" + (m.get("text") or "")[:120]
    h = hashlib.sha1(basis.encode()).hexdigest()[:16]
    return f"{kind}:{h}"


def _stamp(m, run_date):
    m = dict(m)
    m["dedup_key"] = dedup_key(m)
    m["run_date"] = run_date
    return m


# ---------------------------------------------------------------------------
# local JSON fallback (when DB is unconfigured)
# ---------------------------------------------------------------------------

def _local_path(group_id):
    _STORE.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in group_id if ch.isalnum() or ch in "-_")
    return _STORE / f"{safe}.json"


def _local_load(group_id):
    p = _local_path(group_id)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _local_upsert(group_id, rows):
    store = _local_load(group_id)
    inserted = []
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        k = r["dedup_key"]
        if k in store:
            store[k]["last_seen"] = now
            store[k]["sentiment"] = r.get("sentiment")
            store[k]["company"] = r.get("company")
        else:
            rec = dict(r)
            rec["first_seen"] = now
            rec["last_seen"] = now
            store[k] = rec
            inserted.append(k)
    try:
        _local_path(group_id).write_text(json.dumps(store))
    except Exception:
        pass
    return inserted


def _local_recent(group_id, limit):
    store = _local_load(group_id)
    rows = sorted(store.values(), key=lambda r: r.get("ts") or "", reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------
# public store API
# ---------------------------------------------------------------------------

def upsert(group_id, mentions, run_date=None):
    """Upsert a group's mentions. Returns (inserted_mentions, updated_count).
    inserted_mentions is the delta (new this run) to export to Sheets; updates
    just bump last_seen. Uses Postgres when configured, else the local JSON file."""
    run_date = run_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamped = [_stamp(m, run_date) for m in mentions]
    by_key = {m["dedup_key"]: m for m in stamped}      # collapse intra-run dupes

    if _db and _db.configured():
        keys = _db.upsert_mentions(group_id, list(by_key.values()))
    else:
        keys = _local_upsert(group_id, list(by_key.values()))

    inserted = [by_key[k] for k in keys if k in by_key]
    updated = len(by_key) - len(inserted)
    return inserted, updated


def recent(group_id, limit=200):
    if _db and _db.configured():
        return _db.recent_mentions(group_id, limit)
    return _local_recent(group_id, limit)


def prune(older_than_days=180):
    if _db and _db.configured():
        return _db.prune_mentions(older_than_days)
    # local: best-effort, drop rows with last_seen older than cutoff
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    try:
        for p in _STORE.glob("*.json"):
            if p.parent == _LOCKS:
                continue
            store = json.loads(p.read_text())
            keep = {}
            for k, r in store.items():
                try:
                    ls = datetime.fromisoformat((r.get("last_seen") or "").replace("Z", "+00:00"))
                    if ls.timestamp() >= cutoff:
                        keep[k] = r
                    else:
                        removed += 1
                except Exception:
                    keep[k] = r
            p.write_text(json.dumps(keep))
    except Exception:
        pass
    return removed


# ---------------------------------------------------------------------------
# single-flight run lock
# ---------------------------------------------------------------------------

def acquire_lock(name="monitor", ttl=3600):
    """Best-effort single-flight lock so the 9am run, the 13:00 catch-up, and a
    manual run-now cannot overlap and double-write. Returns True if acquired.
    Uses a pg advisory lock when DB is configured, else a lockfile whose mtime
    ages out after ttl seconds (so a crashed run does not wedge the lock forever)."""
    if _db and _db.configured():
        return _db.try_advisory_lock(name)
    _LOCKS.mkdir(parents=True, exist_ok=True)
    lf = _LOCKS / f"{name}.lock"
    try:
        if lf.exists() and (time.time() - lf.stat().st_mtime) < ttl:
            return False
        lf.write_text(str(time.time()))
        return True
    except Exception:
        return True          # never block a run on a lock-io failure


def release_lock(name="monitor"):
    if _db and _db.configured():
        _db.release_advisory_lock(name)
        return
    try:
        (_LOCKS / f"{name}.lock").unlink()
    except Exception:
        pass
