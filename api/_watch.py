"""
Standing watches - the thing that makes this a product rather than a toolkit.

A watch is a keyword the team cares about, checked on a schedule, with new
signals delivered once. Before this, every agent run needed a human to click,
which means the app only worked while someone was looking at it. Nobody pays a
monthly fee for software they have to operate; they pay for one that works while
they sleep and tells them what it found.

A watch is deliberately NOT an agent. It is a schedule plus a keyword. The agent
is what runs when it fires. Keeping them separate means you can add a watch
without touching the AOP, and the agent stays testable on its own.

    run_due()   fire every watch whose interval has elapsed
    run_all()   fire everything now (what the cron and the CLI call)

Both are safe to call repeatedly: delivery is idempotent downstream, and a watch
records its own last_run so a double-fire is a no-op.

No em dashes.
"""
from __future__ import annotations

import time

import _graph as G
import _observe as O

DEFAULT_INTERVAL_S = 6 * 3600      # four times a day is plenty for public posts


def list_watches():
    return [{"id": w["id"], **w["data"]} for w in G.query("watch", limit=100)]


def add(query, sources=None, interval_s=DEFAULT_INTERVAL_S, label=None):
    if not (query or "").strip():
        return {"ok": False, "error": "a watch needs a keyword"}
    key = (query or "").strip().lower()
    wid = G.upsert("watch", {
        "query": query.strip(), "label": label or query.strip(),
        "sources": sources or ["reddit"], "interval_s": int(interval_s),
        "created_at": time.time(), "last_run": None, "runs": 0, "found": 0,
        "enabled": True,
    }, key=key, agent="user")
    return {"ok": True, "id": wid, "query": query.strip()}


def remove(watch_id):
    from _graph import _conn
    with _conn() as c:
        c.execute("DELETE FROM node WHERE id=? AND type='watch'", (watch_id,))
    return {"ok": True}


def due(now=None):
    now = now or time.time()
    out = []
    for w in list_watches():
        if not w.get("enabled", True):
            continue
        last = w.get("last_run")
        if last is None or (now - last) >= (w.get("interval_s") or DEFAULT_INTERVAL_S):
            out.append(w)
    return out


def _fire(w):
    """Run one watch: the agent does the work, delivery is inside its AOP."""
    from _agents import run
    t0 = time.time()
    rec, status = run("listener",
                      {"query": w["query"], "sources": w.get("sources") or ["reddit"]},
                      approved=True)      # a standing watch is a standing grant
    found = rec.get("emitted", 0) if isinstance(rec, dict) else 0
    d = dict(w)
    for k in ("id",):
        d.pop(k, None)
    d["last_run"] = time.time()
    d["runs"] = (w.get("runs") or 0) + 1
    d["found"] = (w.get("found") or 0) + found
    G.upsert("watch", d, key=(w.get("query") or "").strip().lower(), agent="system")
    return {"watch": w.get("label") or w.get("query"), "found": found,
            "ok": bool(isinstance(rec, dict) and rec.get("ok")),
            "seconds": round(time.time() - t0, 1)}


def run_due():
    items = due()
    if not items:
        return {"ran": 0, "results": [], "note": "nothing due"}
    return run_these(items)


def run_all():
    return run_these([w for w in list_watches() if w.get("enabled", True)])


def run_these(items):
    results = []
    for w in items:
        try:
            results.append(_fire(w))
        except Exception as e:                                   # noqa: BLE001
            results.append({"watch": w.get("query"), "ok": False,
                            "error": str(e)[:160]})
            O.log(O.ERROR, agent="listener", ok=False,
                  summary=f"watch failed: {str(e)[:120]}")
    total = sum(r.get("found", 0) for r in results)
    O.log(O.RUN_END, agent="watch", ok=all(r.get("ok") for r in results),
          summary=f"{len(results)} watches, {total} new signals", found=total)
    return {"ran": len(results), "found": total, "results": results}


def status():
    """Is the unattended side alive. A watch that has never run, or has not run
    in three intervals, is the failure a user needs told about."""
    ws, now = list_watches(), time.time()
    stale = []
    for w in ws:
        last = w.get("last_run")
        gap = (w.get("interval_s") or DEFAULT_INTERVAL_S) * 3
        if last is None or (now - last) > gap:
            stale.append(w.get("label") or w.get("query"))
    last_any = max([w.get("last_run") or 0 for w in ws], default=0)
    return {
        "watches": len(ws),
        "enabled": sum(1 for w in ws if w.get("enabled", True)),
        "stale": stale,
        "healthy": bool(ws) and not stale,
        "last_run": last_any or None,
        "hours_since": round((now - last_any) / 3600, 1) if last_any else None,
    }
