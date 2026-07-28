"""
CRM sync into the context graph, across every configured provider.

Providers live in `_crm_providers.py` behind one protocol so HubSpot and
Salesforce are peers rather than a hardcoded default plus an if-branch. This
module owns only the graph-writing half: fetch through the protocol, normalise,
upsert with provenance, and report what changed honestly.

READ ONLY on purpose. Pulling is safe and immediately useful. Writing back is a
SPEND-tier action against someone's system of record, and it belongs behind the
approval ladder rather than in a first connector.

No em dashes.
"""
from __future__ import annotations

import time

import _graph as G
import _crm_providers as P


def configured():
    return P.configured()


def sync(objects=("contacts", "companies", "deals"), run_id=None, providers=None):
    """Pull every configured CRM into the graph.

    Returns what changed split into created and seen, because a re-sync that
    reported everything as new would inflate every downstream metric the same
    way the watch bug did.

    One provider failing does not take the sync down: it is recorded as an error
    against that provider and the others continue."""
    active = [p for p in P.active()
              if not providers or p.id in providers]
    if not active:
        return {"ok": False, "error": "No CRM is connected.",
                "configured": P.configured(), "providers": P.status()["providers"]}
    run_id = run_id or f"crm_{int(time.time())}"
    out, errors = {}, {}

    for prov in active:
        got = {}
        try:
            if "companies" in objects:
                new = seen = 0
                for c in prov.companies():
                    _, created = G.upsert_ex("account", {
                        "name": c["name"], "domain": c["domain"],
                        "industry": c["industry"], "employees": c["employees"],
                        "city": c["city"], "country": c["country"],
                        "lifecycle": c["lifecycle"], "crm": c["crm"],
                        "crm_id": c["crm_id"],
                    }, key=c["key"], agent="crm", run_id=run_id, source=c["url"])
                    new += 1 if created else 0
                    seen += 1
                got["companies"] = {"new": new, "seen": seen}

            if "contacts" in objects:
                new = seen = 0
                for ct in prov.contacts():
                    pid, created = G.upsert_ex("person", {
                        "email": ct["email"], "name": ct["name"], "phone": ct["phone"],
                        "company": ct["company"], "title": ct["title"],
                        "lifecycle": ct["lifecycle"], "crm": ct["crm"],
                        "crm_id": ct["crm_id"], "platform": ct["crm"],
                    }, key=ct["key"], agent="crm", run_id=run_id, source=ct["url"])
                    new += 1 if created else 0
                    seen += 1
                    # Link to the account when the email domain matches one. This
                    # is what lets Steward dedupe a CRM contact against a Reddit
                    # poster: both are Person nodes in one graph.
                    dom = ct["email"].split("@")[-1] if "@" in (ct["email"] or "") else ""
                    if dom:
                        acct = G.query("account", limit=1, where={"domain": dom})
                        if acct:
                            G.link(pid, "works_at", acct[0]["id"])
                got["contacts"] = {"new": new, "seen": seen}

            if "deals" in objects:
                new = seen = 0
                for dl in prov.deals():
                    _, created = G.upsert_ex("deal", {
                        "name": dl["name"], "amount": dl["amount"], "stage": dl["stage"],
                        "pipeline": dl["pipeline"], "close_date": dl["close_date"],
                        "crm": dl["crm"], "crm_id": dl["crm_id"],
                    }, key=dl["key"], agent="crm", run_id=run_id, source=dl["url"])
                    new += 1 if created else 0
                    seen += 1
                got["deals"] = {"new": new, "seen": seen}
            out[prov.id] = got
        except Exception as e:                                   # noqa: BLE001
            # One CRM being down must not fail the others.
            errors[prov.id] = str(e)[:200]
            out[prov.id] = got

    total_new = sum(v.get("new", 0) for prov in out.values() for v in prov.values())
    G.upsert("run", {
        "run_id": run_id, "agent": "crm", "name": "CRM sync", "by": "system",
        "found": out, "errors": errors, "emitted": total_new, "ok": not errors,
        "done": True, "started_at": time.time(),
    }, key=run_id, agent="crm", run_id=run_id)
    return {"ok": not errors, "run_id": run_id, "synced": out,
            "new": total_new, "errors": errors or None,
            "providers": [p.id for p in active]}


def status():
    """What the UI and the agents can honestly say about the CRM."""
    c = P.configured()
    counts = G.counts()["by_type"]
    from_crm = sum(len(G.query("person", limit=2000, where={"crm": pid}))
                   for pid in P.PROVIDERS)
    return {
        "configured": c, "providers": P.status()["providers"],
        "accounts": counts.get("account", 0),
        "people": counts.get("person", 0),
        "deals": counts.get("deal", 0),
        "people_from_crm": from_crm,
        "note": (f"Connected: {', '.join(p.name for p in P.active())}."
                 if c["any"] else
                 "No CRM connected. Connect HubSpot or Salesforce to give Analyst "
                 "and Steward real records to work on."),
    }
