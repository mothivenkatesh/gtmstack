"""
The Cohort Engine - smart segments as the unit of GTM action.

Static segments (industry, size, geo) are commodity. On a live outcome graph you
get cohorts that are multi-parameter, self-updating, and outcome-learned, which
is a prediction rather than a list.

The design rule that matters most, and the reason membership lives here rather
than in a prompt: MEMBERSHIP COMPUTATION IS DETERMINISTIC. The model never
hand-picks accounts, because a model asked to enumerate a set will quietly
invent members and silently drop others. What is agentic is DEFINING a cohort
(translating "accounts like our best customers that just showed intent" into
parameters) and PROPOSING new ones from patterns in the graph.

Every membership carries the reason it matched, so a cohort is auditable rather
than a black box.

No em dashes.
"""
from __future__ import annotations

import time

import _graph as G

KINDS = ("static", "dynamic", "outcome_learned", "predictive")

# Seed cohorts spanning all four kinds, so the difference is visible rather than
# asserted. Predicates are declarative dicts the engine compiles, never code
# strings, so a cohort definition is safe to store and show to a user.
SEEDS = [
    {"key": "buying_intent", "name": "Showing buying intent", "kind": "dynamic",
     "plain": "Anyone publicly asking which vendor to use, or comparing us with a competitor",
     "node": "signal",
     "predicate": {"intent_type_in": ["category_intent", "competitor_comparison"]},
     "play": {"agents": ["writer"], "note": "route to outbound with the signal quoted"}},
    {"key": "unhappy_public", "name": "Publicly unhappy", "kind": "dynamic",
     "plain": "Negative public posts, any platform, so support and comms see them same-day",
     "node": "signal", "predicate": {"sentiment_in": ["negative"]},
     "play": {"agents": ["greeter"], "note": "acknowledge fast, route to support"}},
    {"key": "warm_lookalike", "name": "Looks like a past win", "kind": "outcome_learned",
     "plain": "Accounts whose signal sequence matches the accounts that closed won",
     "node": "account", "predicate": {"has_signal": True, "min_signals": 2},
     "play": {"agents": ["scout", "writer"], "note": "enrich, then a grounded first touch"}},
    {"key": "reddit_voices", "name": "Active Reddit voices", "kind": "static",
     "plain": "People who posted on Reddit, the highest-signal channel for India payments",
     "node": "person", "predicate": {"platform_in": ["reddit"]},
     "play": {"agents": ["watcher"], "note": "watch for repeat posters becoming champions"}},
]


def seed():
    for c in SEEDS:
        if _by_key(c["key"]):
            continue
        G.upsert("cohort", {**c, "created_at": time.time()}, key=c["key"], agent="system")
    return len(SEEDS)


def _by_key(key):
    for c in G.query("cohort", limit=200):
        if c["data"].get("key") == key:
            return c
    return None


def _test(node, pred):
    """Compile a declarative predicate against a node. Returns (matched, reason)
    so every membership can explain itself."""
    d = node["data"]
    reasons = []
    for k, v in (pred or {}).items():
        if k.endswith("_in"):
            field = k[:-3]
            if d.get(field) not in v:
                return False, ""
            reasons.append(f"{field} is {d.get(field)}")
        elif k == "has_signal":
            n = len(G.neighbours(node["id"], "has_signal"))
            if bool(n) != bool(v):
                return False, ""
            reasons.append(f"{n} linked signals")
        elif k == "min_signals":
            n = len(G.neighbours(node["id"], "has_signal"))
            if n < int(v):
                return False, ""
            reasons.append(f"{n} signals, at or above the {v} threshold")
        else:
            if d.get(k) != v:
                return False, ""
            reasons.append(f"{k} is {v}")
    return True, "; ".join(reasons) or "matched"


def members(cohort_key, limit=100):
    c = _by_key(cohort_key)
    if not c:
        return {"error": f"unknown cohort: {cohort_key}"}
    spec = c["data"]
    nodes = G.query(spec.get("node") or "signal", limit=1000)
    out = []
    for n in nodes:
        ok, why = _test(n, spec.get("predicate"))
        if ok:
            out.append({"id": n["id"], "data": n["data"], "reason": why,
                        "source": n.get("source")})
        if len(out) >= limit:
            break
    return {"cohort": cohort_key, "name": spec.get("name"), "kind": spec.get("kind"),
            "plain": spec.get("plain"), "play": spec.get("play"),
            "count": len(out), "members": out}


def all():
    seed()
    out = []
    for c in G.query("cohort", limit=200):
        d = c["data"]
        m = members(d.get("key"), limit=1000)
        total = G.counts()["by_type"].get(d.get("node") or "signal", 0) or 1
        share = round(100.0 * m.get("count", 0) / total, 1)
        out.append({"id": c["id"], **d, "count": m.get("count", 0), "share_pct": share,
                    "lift": _lift(m.get("count", 0), total)})
    return out


def _lift(count, total):
    """Placeholder lift until outcomes accumulate. Stated honestly rather than
    faked: with no closed-won data yet there is nothing to measure against, and
    inventing a number here would undermine the exact claim the cohort makes."""
    if not count:
        return None
    return {"baseline_share_pct": round(100.0 * count / (total or 1), 1),
            "outcome_lift": None,
            "note": "outcome lift needs closed-won data, not yet in the graph"}


def create(name, plain, node="signal", predicate=None, kind="dynamic", play=None):
    key = (name or "").strip().lower().replace(" ", "_")
    if not key:
        return {"ok": False, "error": "name required"}
    nid = G.upsert("cohort", {
        "key": key, "name": name, "plain": plain, "kind": kind if kind in KINDS else "dynamic",
        "node": node, "predicate": predicate or {}, "play": play or {},
        "created_at": time.time(),
    }, key=key, agent="user")
    return {"ok": True, "id": nid, "key": key}


def suggest():
    """Propose cohorts from patterns actually present in the graph. Agentic in
    spirit, deterministic in execution: it reports observed concentrations, it
    does not guess at sets."""
    sigs = G.query("signal", limit=1000)
    by_platform, by_intent = {}, {}
    for s in sigs:
        by_platform[s["data"].get("platform")] = by_platform.get(s["data"].get("platform"), 0) + 1
        by_intent[s["data"].get("intent_type")] = by_intent.get(s["data"].get("intent_type"), 0) + 1
    out = []
    for plat, n in sorted(by_platform.items(), key=lambda x: -x[1])[:2]:
        if plat and n >= 3:
            out.append({"name": f"{str(plat).title()} conversation", "kind": "static",
                        "plain": f"Signals from {plat}, {n} in the graph today",
                        "node": "signal", "predicate": {"platform_in": [plat]},
                        "why": f"{n} signals concentrate here"})
    for intent, n in sorted(by_intent.items(), key=lambda x: -x[1])[:2]:
        if intent and intent != "brand_mention" and n >= 2:
            out.append({"name": f"{str(intent).replace('_', ' ').title()}", "kind": "dynamic",
                        "plain": f"Signals classified {intent}",
                        "node": "signal", "predicate": {"intent_type_in": [intent]},
                        "why": f"{n} signals, worth its own play"})
    return out
