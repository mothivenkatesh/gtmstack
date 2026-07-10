"""
GTMstack - keyword groups for the daily Signals report.

A group is a saved watch: a name, the keywords to scan, which of those are the
brand-exact `primary` terms (they get scan priority and anchor share-of-voice),
the `competitors` to compare against, and which sources to read. The daily report
runs one scan per group.

Groups come from three places, most specific first:
  1. Postgres `groups` table (when DATABASE_URL is set) - user-edited groups.
  2. a gitignored api/_store/groups.json override - local edits without a DB.
  3. the built-in DEFAULT_GROUPS below - so the feature works out of the box.

Edit the defaults here, drop a groups.json, or add DB rows; all three merge by id.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ALL_SOURCES = ["github", "youtube", "reddit", "x", "linkedin"]

# India subs where payment / PG chatter lives. The monitor restricts Reddit
# search to these per-sub (restrict_sr=1); global Reddit search returns garbage
# for niche India PG topics, a rule proven the hard way.
DEFAULT_SUBREDDITS = [
    "developersIndia", "IndiaStartups", "indianstartups", "IndiaBusiness",
    "india", "StartUpIndia", "smallbusiness", "ecommerce", "shopify", "SaaS",
    "fintech", "IndianFinance",
]

# Built-in groups, tuned for Cashfree competitive watch. "primary" = brand-exact
# terms (Carlsen plays these first and they anchor share-of-voice); the broad
# category terms widen the net.
DEFAULT_GROUPS = [
    {
        "id": "payment_gateway",
        "name": "Payment Gateway",
        "keywords": ["cashfree", "razorpay", "payu", "ccavenue", "billdesk",
                     "easebuzz", "instamojo", "juspay", "payment gateway"],
        "primary": ["cashfree"],
        "competitors": ["razorpay", "payu", "billdesk", "easebuzz", "instamojo", "juspay"],
        "sources": ALL_SOURCES,
    },
    {
        "id": "cashfree_brand",
        "name": "Cashfree Brand Watch",
        "keywords": ["cashfree", "cashfree payments", "cashfree payouts"],
        "primary": ["cashfree"],
        "competitors": [],
        "sources": ALL_SOURCES,
    },
    {
        "id": "razorpay_watch",
        "name": "Razorpay Watch",
        "keywords": ["razorpay", "razorpayx", "razorpay magic"],
        "primary": ["razorpay"],
        "competitors": ["cashfree"],
        "sources": ALL_SOURCES,
    },
    {
        "id": "payments_infra",
        "name": "Payments Infra India",
        "keywords": ["payment aggregator", "payment gateway india", "upi autopay",
                     "payout api", "rbi payment aggregator"],
        "primary": [],
        "competitors": [],
        "sources": ["github", "youtube", "reddit", "x"],   # broad terms, skip the king
    },
    # --- Monitor groups (scanned by the 9am competitive monitor) ---------------
    {
        "id": "competitor_watch",
        "name": "Competitor Watch",
        "monitor": True,
        "window_days": 10,
        "keywords": ["payment gateway india", "payment aggregator india",
                     "razorpay", "payu", "ccavenue", "easebuzz", "instamojo",
                     "billdesk", "juspay", "best payment gateway", "pg integration"],
        "primary": ["cashfree"],
        "competitors": ["razorpay", "payu", "ccavenue", "easebuzz", "instamojo",
                        "billdesk", "juspay"],
        "sources": ["reddit", "quora", "trustpilot", "capterra", "g2", "x", "linkedin"],
        "review_brands": ["cashfree", "razorpay", "payu", "ccavenue", "easebuzz",
                          "instamojo", "billdesk"],
        "include_comments": False,
        "quora_questions": [],
        "sinks": ["store", "sheets"],
    },
    {
        "id": "cashfree_mentions",
        "name": "Cashfree Mentions",
        "monitor": True,
        "window_days": 2,
        "keywords": ["cashfree", "cashfree payments", "cashfree payouts"],
        "primary": ["cashfree"],
        "competitors": [],
        "sources": ["reddit", "quora", "x", "linkedin"],
        "review_brands": [],
        "include_comments": True,      # posts AND thread comments, last 2 days
        "quora_questions": [],
        "sinks": ["store", "sheets"],
    },
]

_STORE = Path(__file__).resolve().parent / "_store" / "groups.json"


def _normalize(g):
    """Fill defaults so every consumer can rely on the same shape.

    Monitor fields (used by _monitor.py; the daily report ignores them):
      monitor         : bool, is this group scanned by the 9am competitive monitor
      window_days     : how far back to scan (competitor watch 10, brand watch 2)
      subreddits      : Reddit subs to restrict search to (restrict_sr=1 per sub)
      review_brands   : brand slugs to pull G2/Capterra/TrustPilot reviews for
      include_comments: also pull Reddit thread COMMENTS, not just post titles
      quora_questions : curated Quora question URLs (the reliable Quora path)
      sinks           : where results go, e.g. ['store','sheets']
    """
    g = dict(g or {})
    g.setdefault("keywords", [])
    g.setdefault("primary", [])
    g.setdefault("competitors", [])
    g.setdefault("sources", ALL_SOURCES)
    g.setdefault("monitor", False)
    g.setdefault("window_days", 10)
    g.setdefault("subreddits", list(DEFAULT_SUBREDDITS))
    g.setdefault("review_brands", [])
    g.setdefault("include_comments", False)
    g.setdefault("quora_questions", [])
    g.setdefault("sinks", ["store", "sheets"])
    g["name"] = g.get("name") or g.get("id") or "Untitled"
    return g


def monitor_groups():
    """Only the groups the competitive monitor scans (monitor=True)."""
    return [g for g in list_groups() if g.get("monitor")]


def _file_groups():
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text())
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _db_groups():
    try:
        import _db
        if not _db.configured():
            return []
        c = _db._conn()
        with c.cursor() as cur:
            cur.execute("SELECT to_jsonb(g) FROM groups g")  # optional table
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []          # table may not exist; defaults still serve


def list_groups():
    """All groups, merged by id (DB and file override the built-ins)."""
    merged = {}
    for g in DEFAULT_GROUPS + _file_groups() + _db_groups():
        if g and g.get("id"):
            merged[g["id"]] = _normalize(g)
    return list(merged.values())


def get_group(group_id):
    for g in list_groups():
        if g["id"] == group_id:
            return g
    return None


# Fields a caller is allowed to edit via the write API (never let them inject
# arbitrary keys). id is required and immutable per record.
_EDITABLE = ("name", "keywords", "primary", "competitors", "sources", "monitor",
             "window_days", "subreddits", "review_brands", "include_comments",
             "quora_questions", "sinks")


def save_group(group):
    """Upsert one group into the file store (api/_store/groups.json), which
    overrides the built-in defaults by id. Returns the normalised group or None on
    bad input. Local-first: the launchd Mac and the hosted app both read this file
    (the hosted deploy reads a committed groups.json or the DB). Never raises."""
    gid = (group or {}).get("id", "").strip()
    if not gid:
        return None
    clean = {"id": gid}
    for k in _EDITABLE:
        if k in group:
            clean[k] = group[k]
    try:
        existing = {g["id"]: g for g in _file_groups()}
        # start from any built-in default so a partial edit keeps the rest
        base = next((dict(g) for g in DEFAULT_GROUPS if g["id"] == gid), {})
        base.update(existing.get(gid, {}))
        base.update(clean)
        existing[gid] = base
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(list(existing.values()), indent=2))
        return _normalize(base)
    except Exception:
        return None


def delete_group(group_id):
    """Remove a group from the file store. Built-in defaults reappear (they are
    not deletable, only overridable). Returns True on a write."""
    try:
        rows = [g for g in _file_groups() if g.get("id") != group_id]
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(rows, indent=2))
        return True
    except Exception:
        return False
