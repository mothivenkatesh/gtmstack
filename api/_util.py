"""
GTMstack — small shared helpers for the content agents.

Engagement-count parsing lives here because three engines need it: the teardown
(agent 13), trend discovery (agent 14), and content performance (agent 12). One
parser, one place, so a '42K' is read the same way everywhere.
"""
from __future__ import annotations


def eng_num(value):
    """Parse one engagement count ('42K', '1.2M', '400', '12,300') to a float."""
    s = str(value or "").strip().replace(",", "").upper()
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1e3, s[:-1]
    elif s.endswith("M"):
        mult, s = 1e6, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def eng_str(engagement):
    """'12.3K likes, 400 reposts' from an engagement list."""
    return ", ".join(f'{e.get("value")} {e.get("label")}'
                     for e in (engagement or []) if e.get("value"))


def eng_total(engagement):
    """Sum of the parsed engagement values on a post (one comparable number)."""
    return sum(eng_num(e.get("value")) for e in (engagement or []))
