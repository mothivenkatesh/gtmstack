"""
CRM connector. HubSpot first, Salesforce-shaped so the second one is cheap.

This is the single biggest unlock in the product. Analyst and Steward are fully
built and were reasoning over a graph containing only public Reddit posts, which
is a fraction of their value: "find duplicate contacts" over 19 signals is a
demo, and over a real CRM it is the job. Everything in Phase 1 and Phase 2 of the
roadmap was gated on this file existing.

Design, consistent with the rest of the app:
  - READ ONLY for now. Pulling is safe and immediately useful. Writing back is a
    SPEND-tier action against someone's system of record and needs the approval
    ladder plus a lot more care than a first connector should carry.
  - Gated. No token means `configured()` is False and the agents say so honestly
    rather than pretending an empty CRM.
  - Everything lands in the graph with provenance, so a CRM contact and a Reddit
    poster are the same kind of node and Steward can dedupe across both.
  - Paginated and capped. A first sync must not pull 200k records and time out.

No em dashes.
"""
from __future__ import annotations

import os
import time

import _graph as G

try:
    import requests
except ImportError:                                              # pragma: no cover
    requests = None

HUBSPOT_BASE = "https://api.hubapi.com"
MAX_PAGES = int(os.getenv("CRM_MAX_PAGES", "10"))
PAGE_SIZE = int(os.getenv("CRM_PAGE_SIZE", "100"))


def configured():
    return {
        "hubspot": bool(os.getenv("HUBSPOT_TOKEN") and requests),
        "salesforce": False,      # shaped for it, not wired
        "any": bool(os.getenv("HUBSPOT_TOKEN") and requests),
    }


def _hs(path, params=None):
    tok = os.getenv("HUBSPOT_TOKEN")
    if not (tok and requests):
        raise RuntimeError("HubSpot is not connected")
    r = requests.get(f"{HUBSPOT_BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"},
                     params=params or {}, timeout=30)
    if r.status_code == 401:
        raise RuntimeError("HubSpot rejected the token")
    if r.status_code == 429:
        raise RuntimeError("HubSpot rate limit, try again shortly")
    r.raise_for_status()
    return r.json()


def _pages(path, props):
    """Walk HubSpot's cursor pagination, bounded. An unbounded first sync on a
    large portal is how a connector times out and looks broken."""
    after, seen = None, 0
    for _ in range(MAX_PAGES):
        params = {"limit": PAGE_SIZE, "properties": ",".join(props)}
        if after:
            params["after"] = after
        data = _hs(path, params)
        rows = data.get("results") or []
        for row in rows:
            yield row
            seen += 1
        after = (((data.get("paging") or {}).get("next") or {}).get("after"))
        if not after or not rows:
            return


CONTACT_PROPS = ("email", "firstname", "lastname", "phone", "company",
                 "jobtitle", "lifecyclestage", "hs_lead_status", "createdate")
COMPANY_PROPS = ("name", "domain", "industry", "numberofemployees", "city",
                 "country", "lifecyclestage", "createdate")
DEAL_PROPS = ("dealname", "amount", "dealstage", "pipeline", "closedate",
              "createdate", "hs_lastmodifieddate")


def sync(objects=("contacts", "companies", "deals"), run_id=None):
    """Pull the CRM into the graph. Returns what changed, honestly split into
    created and seen, because a re-sync that reports everything as new would
    inflate every downstream metric the same way the watch bug did."""
    if not configured()["any"]:
        return {"ok": False, "error": "HubSpot is not connected. Set HUBSPOT_TOKEN.",
                "configured": configured()}
    run_id = run_id or f"crm_{int(time.time())}"
    out = {}

    if "companies" in objects:
        new = seen = 0
        for row in _pages("/crm/v3/objects/companies", COMPANY_PROPS):
            p = row.get("properties") or {}
            dom = (p.get("domain") or "").strip().lower()
            key = dom or f"hubspot:company:{row.get('id')}"
            _, created = G.upsert_ex("account", {
                "name": p.get("name"), "domain": dom, "industry": p.get("industry"),
                "employees": p.get("numberofemployees"), "city": p.get("city"),
                "country": p.get("country"), "lifecycle": p.get("lifecyclestage"),
                "crm_id": row.get("id"), "crm": "hubspot",
            }, key=key, agent="crm", run_id=run_id,
                source=f"https://app.hubspot.com/contacts/0/company/{row.get('id')}")
            new += 1 if created else 0
            seen += 1
        out["companies"] = {"new": new, "seen": seen}

    if "contacts" in objects:
        new = seen = 0
        for row in _pages("/crm/v3/objects/contacts", CONTACT_PROPS):
            p = row.get("properties") or {}
            email = (p.get("email") or "").strip().lower()
            key = email or f"hubspot:contact:{row.get('id')}"
            name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x)
            pid, created = G.upsert_ex("person", {
                "email": email, "name": name or None, "phone": p.get("phone"),
                "company": p.get("company"), "title": p.get("jobtitle"),
                "lifecycle": p.get("lifecyclestage"), "lead_status": p.get("hs_lead_status"),
                "crm_id": row.get("id"), "crm": "hubspot", "platform": "hubspot",
            }, key=key, agent="crm", run_id=run_id,
                source=f"https://app.hubspot.com/contacts/0/contact/{row.get('id')}")
            new += 1 if created else 0
            seen += 1
            # Link the person to their account when the email domain matches one.
            dom = email.split("@")[-1] if "@" in email else ""
            if dom:
                acct = G.query("account", limit=1, where={"domain": dom})
                if acct:
                    G.link(pid, "works_at", acct[0]["id"])
        out["contacts"] = {"new": new, "seen": seen}

    if "deals" in objects:
        new = seen = 0
        for row in _pages("/crm/v3/objects/deals", DEAL_PROPS):
            p = row.get("properties") or {}
            _, created = G.upsert_ex("deal", {
                "name": p.get("dealname"), "amount": p.get("amount"),
                "stage": p.get("dealstage"), "pipeline": p.get("pipeline"),
                "close_date": p.get("closedate"), "created_at": p.get("createdate"),
                "crm_id": row.get("id"), "crm": "hubspot",
            }, key=f"hubspot:deal:{row.get('id')}", agent="crm", run_id=run_id,
                source=f"https://app.hubspot.com/contacts/0/deal/{row.get('id')}")
            new += 1 if created else 0
            seen += 1
        out["deals"] = {"new": new, "seen": seen}

    total_new = sum(v["new"] for v in out.values())
    G.upsert("run", {
        "run_id": run_id, "agent": "crm", "name": "CRM sync", "by": "system",
        "found": out, "emitted": total_new, "ok": True, "started_at": time.time(),
    }, key=run_id, agent="crm", run_id=run_id)
    return {"ok": True, "run_id": run_id, "synced": out, "new": total_new}


def status():
    """What the UI and the agents can honestly say about the CRM."""
    c = configured()
    counts = G.counts()["by_type"]
    from_crm = len(G.query("person", limit=2000, where={"crm": "hubspot"}))
    return {
        "configured": c,
        "accounts": counts.get("account", 0),
        "people": counts.get("person", 0),
        "deals": counts.get("deal", 0),
        "people_from_crm": from_crm,
        "note": ("Connected." if c["any"] else
                 "Not connected. Set HUBSPOT_TOKEN to give Analyst and Steward "
                 "real records to work on."),
    }
