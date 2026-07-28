"""
The approval engine - governed autonomy for agent actions.

Ported from OpenWorker (Andrew Ng, MIT), coworker/permissions.py + engine.py.
Two invariants carry over verbatim because they are the whole point:

  1. Every auto-allowed call CITES THE RULE that allowed it. An approval with no
     stated reason is indistinguishable from an agent doing whatever it wants.
  2. Approve-once, then standing. The user grants a scope, not an action, so the
     approval surface SHRINKS as trust compounds. That shrink is the headline
     eval in the PRD, so it has to be a measurable property of this engine.

The outcomes mirror OpenWorker's ApprovalOutcome (once / always_tool /
always_command / deny), re-cut as ONCE / ALWAYS / DENY where ALWAYS carries a
scope string (the GTM equivalent of "always for this command").

Guardrails are checked BEFORE any grant is considered. A standing policy can
never unlock a guardrail, which is what makes them hard limits rather than
defaults.

No em dashes.
"""
from __future__ import annotations

import json
import time
import uuid

import _observe as O
from _graph import _conn, upsert, query
from _risk import RiskClass, classify, is_consequential

# ── outcomes ────────────────────────────────────────────────────────────────

ONCE = "once"
ALWAYS = "always"
DENY = "deny"


class Decision:
    """The engine's answer. `rule` is non-empty whenever allowed is True and the
    call was not explicitly approved by a human in this request, so the UI can
    always show why something was permitted."""

    def __init__(self, allowed, reason, needs_user=False, rule=None, risk=None):
        self.allowed = allowed
        self.reason = reason
        self.needs_user = needs_user
        self.rule = rule
        self.risk = risk

    def as_dict(self):
        return {"allowed": self.allowed, "reason": self.reason,
                "needs_user": self.needs_user, "rule": self.rule,
                "risk": self.risk.value if self.risk else None}


# ── guardrails: hard limits no policy can unlock ────────────────────────────

GUARDRAILS = [
    {"id": "excluded_account", "desc": "Never message an account on the exclusion list"},
    {"id": "budget_cap", "desc": "Never exceed the configured single-change budget cap"},
    {"id": "bulk_delete", "desc": "Never bulk-delete records without explicit approval"},
    {"id": "unsourced_claim", "desc": "Never send a claim that cites no graph node or source"},
]

BUDGET_CAP = 50000.0     # single-change ceiling, currency-agnostic
BULK_CAP = 100           # records touched before it counts as bulk


def check_guardrails(action, payload):
    """Return the id of the first guardrail violated, or None. Checked before
    grants, so a standing policy can never unlock one."""
    payload = payload or {}
    if payload.get("excluded"):
        return "excluded_account"
    amount = payload.get("amount")
    if amount is not None:
        try:
            if float(amount) > BUDGET_CAP:
                return "budget_cap"
        except (TypeError, ValueError):
            pass
    if action in ("bulk_delete",) or (action == "bulk_update"
                                      and int(payload.get("count") or 0) > BULK_CAP):
        return "bulk_delete"
    if payload.get("claims") and not payload.get("sources"):
        return "unsourced_claim"
    return None


# ── standing policies ───────────────────────────────────────────────────────

def grant(action, scope="*", agent=None, note=None):
    """Record a standing policy. Scope is a plain string the caller defines, for
    example an agent id, a cohort, or 'diagnostics under 1000'."""
    return upsert("policy",
                  {"action": action, "scope": scope, "agent": agent,
                   "note": note, "granted_at": time.time()},
                  key=f"{action}:{scope}:{agent or '*'}", agent=agent)


def policies():
    return query("policy", limit=200)


def revoke(policy_id):
    with _conn() as c:
        c.execute("DELETE FROM node WHERE id=? AND type='policy'", (policy_id,))


def _match(action, scope, agent):
    """Find a standing policy covering this call. Most specific first: an
    agent-scoped policy beats a wildcard, so a broad grant never silently
    shadows a narrow one."""
    best = None
    for p in policies():
        d = p["data"]
        if d.get("action") != action:
            continue
        p_scope, p_agent = d.get("scope") or "*", d.get("agent")
        if p_scope not in ("*", scope):
            continue
        if p_agent and agent and p_agent != agent:
            continue
        specificity = (1 if p_scope != "*" else 0) + (1 if p_agent else 0)
        if best is None or specificity > best[0]:
            best = (specificity, p)
    return best[1] if best else None


# ── the engine ──────────────────────────────────────────────────────────────

def decide(action, agent=None, scope="*", payload=None, overrides=None) -> Decision:
    """The single gate every agent action passes through."""
    risk = classify(action, overrides=overrides)

    hit = check_guardrails(action, payload)
    if hit:
        g = next((x for x in GUARDRAILS if x["id"] == hit), {"desc": hit})
        return Decision(False, f"blocked by guardrail: {g['desc']}", risk=risk)

    if not is_consequential(risk):
        return Decision(True, "read only, no side effects",
                        rule="tier:read is automatic", risk=risk)

    p = _match(action, scope, agent)
    if p:
        d = p["data"]
        who = d.get("agent") or "any agent"
        rule = f"standing policy: {d.get('action')} for {d.get('scope')} ({who})"
        return Decision(True, "allowed by a standing policy", rule=rule, risk=risk)

    tier = "spend" if risk is RiskClass.SPEND else "write"
    return Decision(False, f"{tier} action needs approval", needs_user=True, risk=risk)


# ── the pending queue: the labelling stream ─────────────────────────────────

def request(action, agent, scope="*", payload=None, summary=""):
    """Queue an action for human approval. This queue is also the eval and
    labelling stream, so every item keeps its full payload and reasoning."""
    return upsert("action",
                  {"action": action, "agent": agent, "scope": scope,
                   "payload": payload or {}, "summary": summary,
                   "state": "pending", "risk": classify(action).value,
                   "requested_at": time.time()},
                  agent=agent)


def pending():
    return [a for a in query("action", limit=200)
            if a["data"].get("state") == "pending"]


def resolve(action_id, outcome, scope=None):
    """Human answer to a pending action. ALWAYS also writes a standing policy,
    which is the mechanism that shrinks the queue over time."""
    node = None
    for a in query("action", limit=400):
        if a["id"] == action_id:
            node = a
            break
    if not node:
        return {"ok": False, "error": "unknown action"}

    d = node["data"]
    d["state"] = {ONCE: "approved", ALWAYS: "approved", DENY: "denied"}.get(outcome, "denied")
    d["outcome"] = outcome
    d["resolved_at"] = time.time()

    granted = None
    if outcome == ALWAYS:
        granted = grant(d.get("action"), scope or d.get("scope") or "*", d.get("agent"),
                        note="granted from the approval queue")
        d["policy_id"] = granted

    # Update in place. Do NOT route this through upsert(): with an explicit id
    # and no natural key it takes the INSERT path and trips the primary key.
    with _conn() as c:
        c.execute("UPDATE node SET data=?, updated_at=? WHERE id=?",
                  (json.dumps(d), time.time(), action_id))
    # Every human answer is a label. Logging it is what makes the approvals
    # shrink measurable rather than asserted.
    O.log(O.APPROVAL, agent=d.get("agent"), ok=(outcome != DENY),
          summary=f"{d.get('action')}: {outcome}", action=d.get("action"),
          outcome=outcome, made_standing=bool(granted))
    return {"ok": True, "action": action_id, "outcome": outcome, "policy": granted}


def stats():
    """The compounding metric: approvals asked per week should trend down as
    standing policies accumulate. This is the number the PRD calls the headline
    eval, so it is computed here rather than in the UI."""
    acts = query("action", limit=1000)
    now = time.time()
    week = 7 * 86400
    asked_this_week = sum(1 for a in acts
                          if (a["data"].get("requested_at") or 0) >= now - week)
    asked_prev_week = sum(1 for a in acts
                          if now - 2 * week <= (a["data"].get("requested_at") or 0) < now - week)
    return {
        "standing_policies": len(policies()),
        "pending": len(pending()),
        "asked_this_week": asked_this_week,
        "asked_prev_week": asked_prev_week,
        "auto_allowed": sum(1 for a in acts if a["data"].get("state") == "auto"),
        "guardrails": GUARDRAILS,
    }
