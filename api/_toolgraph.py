"""
Tool output into the context graph.

Every tool run writes what it learned, whether a human clicked it or an agent
called it. Before this, the toolkit and the harness were two disconnected
systems: a manual Signals lookup rendered and vanished, while the same lookup
through Listener became durable nodes with provenance. That made the product's
central claim, one graph many doors, false.

Deliberately narrow. It records the ENTITIES a tool discovered, not the raw
payload: people, signals, and the run itself. A graph stuffed with response
blobs is a log, not an ontology.

Never raises. Recording must not break the tool it observes.

No em dashes.
"""
from __future__ import annotations

import time
import uuid

import _graph as G


def _people_from_signals(payload, run_id, tool):
    """A Signals lookup: persist the authors and their posts."""
    n_p = n_s = 0
    items = list(payload.get("feed") or [])
    for src in payload.get("sources") or []:
        for a in src.get("activity") or []:
            items.append({**a, "platform": a.get("platform") or src.get("platform")})
    for m in items:
        plat = m.get("platform") or "unknown"
        author = (m.get("author") or "").strip()
        pid = None
        if author:
            pid, created = G.upsert_ex("person", {"handle": author, "platform": plat},
                                       key=f"{plat}:{author}", agent=tool,
                                       run_id=run_id, source=m.get("url"))
            n_p += 1 if created else 0
        key = f"{plat}:{m.get('id') or m.get('url') or (m.get('text') or '')[:80]}"
        sid, created = G.upsert_ex("signal", {
            "platform": plat, "url": m.get("url"), "author": author,
            "text": (m.get("text") or "")[:600], "where": m.get("where"),
            "posted_at": m.get("ts"), "ago": m.get("ago"),
            "found_by": tool,
        }, key=key, agent=tool, run_id=run_id, source=m.get("url"))
        n_s += 1 if created else 0
        if pid:
            G.link(sid, "authored_by", pid)
    return {"people": n_p, "signals": n_s}


def _accounts_from_clean(payload, run_id, tool):
    """A NoBounce run: the deliverable domains are accounts worth knowing."""
    n = 0
    seen = set()
    for row in (payload.get("rows") or [])[:500]:
        dom = (row.get("domain") or "").strip().lower()
        if not dom or dom in seen or not row.get("valid"):
            continue
        seen.add(dom)
        _, created = G.upsert_ex("account", {"domain": dom, "found_by": tool},
                                 key=dom, agent=tool, run_id=run_id)
        n += 1 if created else 0
    return {"accounts": n}


def record(tool_id, body, payload):
    """Write what a tool discovered. Returns a summary, or None when nothing
    was worth recording."""
    if not isinstance(payload, dict):
        return None
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    found = {}

    if tool_id == "signals":
        found = _people_from_signals(payload, run_id, tool_id)
    elif tool_id == "clean":
        found = _accounts_from_clean(payload, run_id, tool_id)

    if not any(found.values()):
        return None

    G.upsert("run", {
        "run_id": run_id, "agent": tool_id, "name": tool_id.title(),
        "input": {k: v for k, v in (body or {}).items() if k != "text"},
        "emitted": sum(found.values()), "found": found,
        "by": "human", "started_at": time.time(), "ok": True,
    }, key=run_id, agent=tool_id, run_id=run_id)
    return found
