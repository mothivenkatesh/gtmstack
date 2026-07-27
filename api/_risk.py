"""
Risk classes for agent actions - the intrinsic side-effect category that drives
approval gating.

Ported from OpenWorker (Andrew Ng, MIT), coworker/risk.py, and re-cut for GTM.
OpenWorker classifies a local coding agent's tools (read / write_local / exec /
external). A GTM harness moves messages, records, and money instead of files, so
the ladder is READ -> WRITE -> SPEND, and "external" collapses into WRITE or
SPEND depending on whether the action costs money or is irreversible.

The rule that carries over unchanged, and the reason this file exists: risk is a
DECLARED PROPERTY of an action that one `classify` reads, never a hardcoded name
set scattered through the engine. Effective risk = a user-local override, then
the by-name base table, then the action's own metadata, else READ.

No em dashes.
"""
from __future__ import annotations

from enum import Enum


class RiskClass(str, Enum):
    READ = "read"      # no side effects, always allowed
    WRITE = "write"    # mutates a record or sends a message, approve-once then standing
    SPEND = "spend"    # costs money or is irreversible, explicit until a standing policy exists


# Actions whose risk is fixed by name. This is the whole gate, as data.
WRITE_ACTIONS = {
    "update_record", "create_record", "enrich_account", "write_signal",
    "send_message", "send_email", "send_whatsapp", "publish_post",
    "book_meeting", "assign_owner", "add_to_cohort", "write_definition",
}

SPEND_ACTIONS = {
    "set_budget", "launch_campaign", "pause_campaign", "reallocate_spend",
    "bulk_update", "bulk_delete", "merge_records", "issue_refund", "charge",
}

_BASE: dict[str, RiskClass] = {
    **{name: RiskClass.WRITE for name in WRITE_ACTIONS},
    **{name: RiskClass.SPEND for name in SPEND_ACTIONS},
}


def classify(action_name, metadata=None, overrides=None) -> RiskClass:
    """Effective risk of an action. A user-local override wins, then the by-name
    base table, then metadata (`irreversible` -> SPEND, `mutates` -> WRITE),
    else READ."""
    if overrides is not None:
        ov = overrides(action_name)
        if ov is not None:
            return ov
    base = _BASE.get(action_name)
    if base is not None:
        return base
    if metadata is not None:
        if bool(getattr(metadata, "irreversible", False)):
            return RiskClass.SPEND
        if bool(getattr(metadata, "mutates", False)):
            return RiskClass.WRITE
    return RiskClass.READ


def is_consequential(risk: RiskClass) -> bool:
    """Anything but a pure read needs the approval engine's attention."""
    return risk is not RiskClass.READ


def tier_meta(risk: RiskClass) -> dict:
    """UI-facing description of a tier, so the frontend never hardcodes copy."""
    return {
        RiskClass.READ: {
            "label": "Read", "tone": "green", "gate": "automatic",
            "desc": "Query the graph, research, analyse. No side effects.",
        },
        RiskClass.WRITE: {
            "label": "Write", "tone": "amber", "gate": "approve once, then standing",
            "desc": "Update a record, send a message, publish. Reversible.",
        },
        RiskClass.SPEND: {
            "label": "Spend", "tone": "red", "gate": "explicit every time until a standing policy exists",
            "desc": "Move budget, bulk-modify, or anything irreversible.",
        },
    }[risk]
