"""
The signal lifecycle. One state machine, stated once, so every surface agrees.

Why this file exists. Delivery, outcomes, cohorts, and the value surface each
had their own implicit idea of what stage a signal was at, expressed as ad-hoc
field checks (`delivered_at` here, `actioned` there). That works until two
surfaces disagree, and then the product tells a user two different things about
the same row. A state machine written down once is cheaper than reconciling four
opinions later.

    discovered -> classified -> saved -> queued -> delivered -> actioned
                                                             -> ignored
                                                             -> converted

STATE OWNERSHIP, which is the decision everything else hangs off:

  The GRAPH owns every field except the outcome.
  The SHEET owns the outcome column, and nothing else.

That split is deliberate and it is what makes a two-way sync safe. Each field
has exactly ONE writer, so there is no conflict to resolve and no last-writer-
wins guesswork. A user editing the text of a row in their sheet changes nothing
upstream, which is correct: the post is a fact about the world, not their copy
of it. A user setting the outcome dropdown changes everything, which is also
correct: the outcome is THEIR judgment and only they have it.

A row deleted from the sheet is NOT re-pushed. Delivery is a thing that
happened, not a desired end state, so re-adding it would be arguing with the
user about their own workspace.

No em dashes.
"""
from __future__ import annotations

import time

import _graph as G

# ── the states ──────────────────────────────────────────────────────────────

DISCOVERED = "discovered"    # the agent found a public post
CLASSIFIED = "classified"    # intent and sentiment assigned
SAVED = "saved"              # written to the graph with provenance
QUEUED = "queued"            # judged worth a human's attention, not yet sent
DELIVERED = "delivered"      # pushed to at least one channel
ACTIONED = "actioned"        # the human acted on it
IGNORED = "ignored"          # the human saw it and chose not to act
CONVERTED = "converted"      # it became a real conversation

TERMINAL = (ACTIONED, IGNORED, CONVERTED)
ORDER = [DISCOVERED, CLASSIFIED, SAVED, QUEUED, DELIVERED, ACTIONED]

# Which transitions are legal. Anything not listed is a bug, and `advance`
# refuses it rather than writing a state nobody can reason about.
TRANSITIONS = {
    DISCOVERED: {CLASSIFIED},
    CLASSIFIED: {SAVED},
    SAVED: {QUEUED, IGNORED},          # a non-buying signal is stored, never queued
    QUEUED: {DELIVERED, IGNORED},
    DELIVERED: {ACTIONED, IGNORED, CONVERTED},
    ACTIONED: {CONVERTED},             # an actioned signal can still convert later
    IGNORED: set(),
    CONVERTED: set(),
}

BUYING = ("category_intent", "competitor_comparison")

# What the user sees, per state. Product copy lives with the state it describes
# so the two cannot drift.
LABELS = {
    DISCOVERED: ("Found", "We spotted this post"),
    CLASSIFIED: ("Read", "We worked out what it is"),
    SAVED: ("Saved", "Kept, with a link back to the original"),
    QUEUED: ("Ready for you", "Worth your attention, waiting to be sent"),
    DELIVERED: ("Sent to you", "In your sheet or Slack, awaiting your call"),
    ACTIONED: ("You acted", "You reached out or replied"),
    IGNORED: ("Not worth it", "You saw it and passed"),
    CONVERTED: ("Became a conversation", "This one turned into something real"),
}


def state_of(node):
    """Derive the current state from a signal node.

    Derived rather than stored, on purpose. A stored status field is a second
    source of truth that goes stale the moment any writer forgets to update it.
    The fields it reads (`outcome`, `delivered_at`, `intent_type`) are each
    written by exactly one owner, so the derivation cannot disagree with itself.
    """
    d = node.get("data", node) or {}
    outcome = d.get("outcome")
    if outcome in TERMINAL:
        return outcome
    if d.get("delivered_at"):
        return DELIVERED
    if d.get("intent_type") in BUYING:
        return QUEUED
    if d.get("intent_type"):
        return SAVED
    return DISCOVERED


def can(frm, to):
    return to in TRANSITIONS.get(frm, set())


def advance(signal_id, to, note=None, by="system"):
    """Move a signal forward, refusing an illegal jump.

    Returns {ok, from, to} or {ok: False, error}. Never raises: a lifecycle
    disagreement should surface as a refused transition the caller can log, not
    an exception that takes a run down."""
    node = G.get(signal_id)
    if not node:
        return {"ok": False, "error": "unknown signal"}
    frm = state_of(node)
    if frm == to:
        return {"ok": True, "from": frm, "to": to, "noop": True}
    if not can(frm, to):
        return {"ok": False, "error": f"cannot go from {frm} to {to}",
                "from": frm, "to": to}

    patch = {"state_changed_at": time.time(), "state_changed_by": by}
    if to in TERMINAL:
        patch["outcome"] = to
        patch["actioned"] = to != IGNORED
        if note:
            patch["outcome_note"] = note
    elif to == DELIVERED:
        patch["delivered_at"] = time.time()
    G.upsert("signal", patch, key=node.get("key"), agent=by)
    return {"ok": True, "from": frm, "to": to}


def funnel(window_s=30 * 86400):
    """The lifecycle as a funnel. This is the honest health check: if signals
    pile up at DELIVERED and nothing reaches a terminal state, the alerts are
    not useful enough to act on, and that is the number that predicts churn."""
    since = time.time() - window_s
    counts = {s: 0 for s in (DISCOVERED, CLASSIFIED, SAVED, QUEUED, DELIVERED,
                             ACTIONED, IGNORED, CONVERTED)}
    for n in G.query("signal", limit=3000):
        if (n.get("created_at") or 0) < since:
            continue
        counts[state_of(n)] = counts.get(state_of(n), 0) + 1

    delivered_total = sum(counts[s] for s in (DELIVERED,) + TERMINAL)
    decided = sum(counts[s] for s in TERMINAL)
    acted = counts[ACTIONED] + counts[CONVERTED]
    return {
        "counts": counts,
        "delivered": delivered_total,
        "awaiting_your_call": counts[DELIVERED],
        "decided": decided,
        "response_rate": round(100.0 * decided / delivered_total, 1) if delivered_total else None,
        "useful_alert_rate": round(100.0 * acted / delivered_total, 1) if delivered_total else None,
        "stalled": counts[DELIVERED] > 0 and decided == 0,
        "labels": {k: {"label": v[0], "help": v[1]} for k, v in LABELS.items()},
    }
