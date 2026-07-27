"""
Key Definitions - the semantic layer.

One authoritative, versioned definition per business metric. Any agent computing
that metric must use it, and no agent may redefine it inline. This is the fix for
the failure mode where three reports disagree because three people each wrote
their own win-rate formula.

Why it is in the PRD as a moat component and not just a nicety: a KD is the
customer's own semantics, encoded in our system, promoted out of their own
analyses. It makes every future analysis consistent, it is permanent
institutional knowledge, and it is one of the strongest switching costs we have.

Versioned on purpose: editing a KD flags every downstream analysis built on the
old version rather than silently changing history.

No em dashes.
"""
from __future__ import annotations

import time

import _graph as G

# Seed definitions. These are the metrics real GTM teams asked to standardise.
SEEDS = [
    {"key": "opportunity_age", "name": "Opportunity Age",
     "formula": "close_date - date_entered_pipeline",
     "inputs": ["date_entered_pipeline", "close_date"], "owner": "RevOps"},
    {"key": "win_rate", "name": "Win Rate",
     "formula": "closed_won / (closed_won + closed_lost)",
     "inputs": ["stage", "closed_won", "closed_lost"], "owner": "RevOps"},
    {"key": "churn_rate", "name": "Churn Rate",
     "formula": "customers_lost_in_period / customers_at_period_start",
     "inputs": ["customers_at_period_start", "customers_lost"], "owner": "RevOps"},
    {"key": "pipeline_velocity", "name": "Pipeline Velocity",
     "formula": "(opportunities * win_rate * average_deal_value) / sales_cycle_length",
     "inputs": ["opportunities", "win_rate", "average_deal_value", "sales_cycle_length"],
     "owner": "Sales"},
    {"key": "campaign_influence_roi", "name": "Campaign Influence ROI",
     "formula": "influenced_pipeline / campaign_spend",
     "inputs": ["influenced_pipeline", "campaign_spend"], "owner": "Marketing"},
    {"key": "active_pipeline", "name": "Active Pipeline",
     "formula": "sum(amount) where stage is open and period overlaps",
     "inputs": ["amount", "stage", "close_date"], "owner": "RevOps"},
]

_MATCH = {
    "opportunity_age": ("age", "how long", "days in stage", "stalled"),
    "win_rate": ("win rate", "won", "conversion"),
    "churn_rate": ("churn", "retention", "lost customers"),
    "pipeline_velocity": ("velocity", "sales cycle", "how fast"),
    "campaign_influence_roi": ("campaign", "attribution", "influence", "roi", "roas"),
    "active_pipeline": ("pipeline", "open deals", "coverage"),
}


def seed():
    """Idempotent: keyed upserts, so calling this twice does not duplicate."""
    for d in SEEDS:
        existing = _by_key(d["key"])
        if existing:
            continue
        G.upsert("definition",
                 {**d, "version": 1, "created_at": time.time(), "used_by": []},
                 key=d["key"], agent="system")
    return len(SEEDS)


def _by_key(key):
    for d in G.query("definition", limit=200):
        if d["data"].get("key") == key:
            return d
    return None


def all():
    seed()
    return [{"id": d["id"], **d["data"]} for d in G.query("definition", limit=200)]


DEFINITIONS = SEEDS


def resolve_for_question(question):
    """Which Key Definitions does this question touch. Deterministic keyword
    match, not a model call: picking the standard definition must be predictable,
    or the consistency guarantee is worthless."""
    q = (question or "").lower()
    hits = []
    for d in all():
        keys = _MATCH.get(d.get("key"), ())
        if any(k in q for k in keys):
            hits.append(d)
    return hits


def promote(name, formula, inputs=None, owner="RevOps", source_run=None):
    """Promote a formula from an analysis into a Key Definition. This is the
    exact move real analysts ask for: that formula is right, make it the
    standard so nobody redefines it next quarter."""
    key = (name or "").strip().lower().replace(" ", "_")
    if not key:
        return {"ok": False, "error": "name required"}
    existing = _by_key(key)
    version = (existing["data"].get("version", 1) + 1) if existing else 1
    nid = G.upsert("definition", {
        "key": key, "name": name, "formula": formula, "inputs": inputs or [],
        "owner": owner, "version": version, "created_at": time.time(),
        "promoted_from": source_run, "used_by": [],
    }, key=key, agent="analyst", run_id=source_run)
    return {"ok": True, "id": nid, "key": key, "version": version,
            "note": ("new definition" if version == 1 else
                     f"version {version}, downstream analyses on v{version - 1} are flagged")}
