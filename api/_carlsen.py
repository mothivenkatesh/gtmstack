"""
GTMstack - Carlsen scan strategy.

Magnus Carlsen does not win on one killer tactic. He wins on position: develop
the safe pieces first, never overextend, keep the king safe, and convert small
edges in the endgame. This module applies that to a daily keyword-group scan. It
decides the ORDER and PACE of the source reads (the moves) so a time-boxed run
surfaces the sharpest signal while never getting the fragile accounts banned.

It is the strategy layer that sits on top of _fetch.py (the transport: TLS
fingerprint, per-host backoff, circuit breaker). _fetch plays each move safely;
_carlsen decides which move to play, in what order, and when to resign. Pure
Python, deterministic, no network and no model calls, so it is unit-testable.

Chess to code:
  Opening book        cheap, keyless, datacenter-safe sources first (GitHub,
                      YouTube) to develop and confirm the position is live
                      before committing to the fragile ones.
  Move ordering       scan by an evaluation score (source safety x keyword
                      priority), best move first, so a run cut short by the
                      clock still captured the highest-value reads.
  Prophylaxis         read the live circuit-breaker status and skip any host
                      already tripped; widen the politeness gap as fails rise.
                      Stop the ban before it happens.
  King safety         LinkedIn is the king: one fragile personal session a ban
                      takes off the board for good. Always scanned last,
                      sequentially, lowest volume, and resigned on the first
                      soft-challenge. Sacrifice the read to save the account.
  Time management     a hard wall-clock budget for the whole run, split across
                      sources by safety and yield; never burn the clock on one
                      slow host.
  Endgame technique   results persist as they land (see _report), so a timed-out
                      run keeps the position and the next tick converts it
                      instead of losing everything.
  Evaluation function rank surfaced posts by freshness x engagement x
                      competitor-relevance, sharpest signal at the top.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

try:
    from _util import eng_total
except Exception:                       # let the module import standalone in tests
    def eng_total(_engagement):
        return 0.0

# Safety / yield tier per source. Higher means scan earlier and lower ban risk.
# Keyless public sources are both safe and free, so they open; the personal-
# session sources are fragile, so they come last.
SOURCE_SAFETY = {
    "github": 5,     # public REST, datacenter-safe, free
    "youtube": 5,    # public pages, keyless
    "trustpilot": 4, # public __NEXT_DATA__ JSON, permissive posture
    "reddit": 4,     # OAuth app-only, 100 req/min
    "capterra": 3,   # behind Cloudflare, best-effort
    "quora": 3,      # curated question pages, login-walled search
    "x": 2,          # session cookies, rotating query ids
    "g2": 2,         # licensed API only; scraper 403s hard
    "linkedin": 1,   # the king: fragile personal session
}
KING = "linkedin"
OPENING = ("github", "youtube")         # develop these first

# Best-effort source -> host map, so we can read _fetch.status() (keyed by host)
# and skip a source whose circuit breaker is already open (prophylaxis).
SOURCE_HOSTS = {
    "github": ("api.github.com",),
    "youtube": ("www.youtube.com",),
    "trustpilot": ("www.trustpilot.com",),
    "reddit": ("oauth.reddit.com", "www.reddit.com"),
    "capterra": ("www.capterra.com",),
    "quora": ("www.quora.com",),
    "x": ("x.com", "twitter.com", "api.x.com"),
    "g2": ("www.g2.com",),
    "linkedin": ("www.linkedin.com",),
}

# King defaults: small, slow, sequential. A burst from one personal session is
# the bot pattern that gets the account challenged.
KING_MAX_KEYWORDS = 3
KING_BUDGET_S = 8.0


def _breaker_open(source, fetch_status):
    """True when a source's primary host has its circuit breaker tripped."""
    if not fetch_status:
        return False
    for host in SOURCE_HOSTS.get(source, ()):  # tolerate exact or suffix match
        for h, st in fetch_status.items():
            if (h == host or h.endswith(host)) and st.get("open"):
                return True
    return False


def order_sources(sources, fetch_status=None):
    """Opening book + prophylaxis + king safety, in one ordering.

    Drop any source whose breaker is open (prophylaxis), sort the rest by safety
    tier (opening book: cheap/safe first), and force the king (LinkedIn) last so
    the fragile session is only touched once everything else has been read.
    """
    avail = [s for s in (sources or []) if not _breaker_open(s, fetch_status)]
    king = [s for s in avail if s == KING]
    body = [s for s in avail if s != KING]
    body.sort(key=lambda s: (SOURCE_SAFETY.get(s, 3), s in OPENING), reverse=True)
    return body + king          # king always last


def keyword_priority(keyword, group):
    """Initiative: play the sharpest move first. A group's `primary` keywords
    (usually exact brand terms) outrank the broad category terms."""
    kw = (keyword or "").strip().lower()
    primary = {k.lower() for k in (group.get("primary") or [])}
    if kw in primary:
        return 3
    return 1 if len(kw.split()) >= 2 else 2   # multi-word category terms are broadest


def plan(group, sources, fetch_status=None, budget_s=45.0):
    """Build the move list for one group's scan.

    Returns a list of moves, best (safest x highest-yield) first:
        {source, keywords:[...], budget_s, sequential, is_king}
    The clock is split across sources by safety tier so the run spends its time
    on the safe, high-yield reads first; the king gets a small fixed slice and
    runs sequentially.
    """
    ordered = order_sources(sources, fetch_status)
    if not ordered:
        return []
    keywords = list(dict.fromkeys(group.get("keywords") or []))   # de-dupe, keep order
    keywords.sort(key=lambda k: keyword_priority(k, group), reverse=True)

    body = [s for s in ordered if s != KING]
    has_king = KING in ordered
    body_budget = max(budget_s - (KING_BUDGET_S if has_king else 0.0), 1.0)
    weight = {s: SOURCE_SAFETY.get(s, 3) for s in body}
    wsum = sum(weight.values()) or 1

    moves = []
    for s in body:
        moves.append({
            "source": s,
            "keywords": keywords,
            "budget_s": round(body_budget * weight[s] / wsum, 1),
            "sequential": False,
            "is_king": False,
        })
    if has_king:
        moves.append({
            "source": KING,
            "keywords": keywords[:KING_MAX_KEYWORDS],   # lowest volume
            "budget_s": KING_BUDGET_S,
            "sequential": True,                          # never burst the king
            "is_king": True,
        })
    return moves


def resign(source, fails=0, challenged=False):
    """King safety: abandon a source mid-run rather than risk the account.

    For the king (LinkedIn) one soft-challenge or a single hard failure is enough
    to walk away for the day. For the rest we lean on _fetch's own breaker and
    only resign after repeated failures.
    """
    if source == KING:
        return challenged or fails >= 1
    return fails >= 3


def politeness_gap(source, fails=0):
    """Seconds to wait between reads of a source, widened as failures rise
    (prophylaxis). The king is paced slowest."""
    base = 1.5 if source == KING else 0.4
    return round(base * (1 + min(fails, 4)), 2)


def _freshness(ts, half_life_days=7.0):
    """1.0 for a brand-new post, decaying by half every `half_life_days`. An
    undated post is treated as mid-decay so dated, fresh posts outrank it."""
    if not ts:
        return 0.4
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return 0.4
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - dt).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / half_life_days)


def _relevance(text, group):
    """Higher when the post names a group keyword (the signal we asked for),
    with a small bonus for naming more than one (a comparison, the richest read)."""
    t = (text or "").lower()
    hits = sum(1 for k in (group.get("keywords") or []) if k.lower() in t)
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.8
    return 0.4          # surfaced by an adjacent term, still worth keeping


def evaluate(post, group):
    """Positional score for ranking a surfaced post: freshness x reach x
    relevance. The boring-but-strong endgame metric, no model needed."""
    fresh = _freshness(post.get("ts"))
    reach = math.log1p(max(eng_total(post.get("engagement")), 0.0))
    rel = _relevance(post.get("text"), group)
    return round(fresh * (1.0 + reach) * rel, 4)


def rank(posts, group):
    """Order surfaced posts by the evaluation function, sharpest signal first.
    Annotates each post with its `score` so the report can show why it ranked."""
    scored = []
    for p in posts or []:
        p = dict(p)
        p["score"] = evaluate(p, group)
        scored.append(p)
    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored
