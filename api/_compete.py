"""
GTMstack — Competitor Intelligence engine.

Give it your brand and your competitor brands. It reads who is posting and
tagging about each across the channels Signals reaches (X, GitHub, YouTube,
Reddit), then returns the competitor-analysis panels: share of voice, a
market-positioning quadrant (post volume x engagement), the channel breakdown,
the top voices per brand, and the voices shared across competitors (overlap =
who to engage).

Honest scope: built from posts, mentions, and engagement, not scraped engager
lists. Instagram is excluded (product-note exclusion: not API-available,
scraping-only, ToS-hostile, consumer not B2B). Reuses the trends engine's voice
ranking. Brand scans run in parallel (stdlib threads) so five brands cost about
one brand's latency, not five; a per-brand failure degrades to empty, never a
crash.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from _signals import lookup as signals_lookup, linkedin_firmographics
from _util import eng_total
from _trends import collect_feed, top_voices

MAX_BRANDS = 6


def _brand_posts(brand, sources=None, force=True):
    """Posts mentioning a brand, via the Signals keyword feed. force=True scrapes
    live (past the 30-min cache) for a realtime read. Never raises: a failed scan
    returns empty so one bad brand can't take the comparison down."""
    try:
        foot, st = signals_lookup(brand, sources, force=force, unit="keyword")
        if st != 200:
            return [], []
        posts = collect_feed(foot.get("feed") or [])
        status = [{"platform": s.get("platform"), "status": s.get("status"),
                   "note": s.get("note")} for s in (foot.get("sources") or [])]
        return posts, status
    except Exception:
        return [], []


def _quadrant(vol_hi, eng_hi):
    """Market-positioning quadrant from a median split of volume x engagement."""
    if vol_hi and eng_hi:
        return "Leader"            # high volume + strong engagement
    if vol_hi and not eng_hi:
        return "Aggressive"        # lots of posts, lower engagement each
    if not vol_hi and eng_hi:
        return "Punching above"    # fewer posts, high engagement each
    return "Starter"               # low volume + low engagement


def _insights(rows, channels, overlap, your_brand):
    """Opinionated takes derived deterministically from the metrics (boring-stack:
    no model needed). Each is a named read a GTM lead can act on this week."""
    out = []
    yb = your_brand.lower()
    you = next((r for r in rows if r["you"]), None)
    leader = rows[0] if rows else None

    if you and leader:
        if you["rank"] == 1:
            out.append({"kind": "win", "headline": "You lead on reach",
                        "detail": f'{your_brand} owns {you["reach_pct"]}% of the engagement, '
                                  f'ahead of {len(rows) - 1} competitor(s). Press it.'})
        else:
            out.append({"kind": "gap",
                        "headline": f'You sit #{you["rank"]} of {len(rows)} on reach',
                        "detail": f'{leader["brand"]} leads at {leader["reach_pct"]}% vs your '
                                  f'{you["reach_pct"]}%. They win on '
                                  f'{leader["top_channel"] or "volume"}.'})

    for r in rows:
        if r["quadrant"] == "Aggressive":
            out.append({"kind": "read", "headline": f'{r["brand"]} buys reach, not earns it',
                        "detail": f'High volume, only {r["impact"]}x the field-average engagement '
                                  f'per post. Loud, not resonant.'})
        elif r["quadrant"] == "Punching above":
            out.append({"kind": "read", "headline": f'{r["brand"]} punches above its weight',
                        "detail": f'Fewer posts, {r["impact"]}x engagement each. Study what they post.'})

    for c in channels:
        tot = sum(c["by_brand"].values()) or 1
        top = max(c["by_brand"], key=c["by_brand"].get)
        share = c["by_brand"][top] / tot
        if share >= 0.45 and len(c["by_brand"]) > 1:
            mine = top.lower() == yb
            out.append({"kind": "win" if mine else "channel",
                        "headline": f'{top} owns {c["channel"]}',
                        "detail": f'{int(share * 100)}% of {c["channel"]} chatter is about {top}. '
                                  f'{"Your stronghold, defend it." if mine else "A gap to attack or cede."}'})

    if overlap:
        v = overlap[0]
        out.append({"kind": "voice", "headline": f'@{v["author"]} is a bridge voice',
                    "detail": f'Already posts about {", ".join(v["brands"])}. '
                              f'Engage once, reach all {v["shared_across"]}.'})

    return out[:7]


def analyze(your_brand, competitors, sources=None):
    your_brand = (your_brand or "").strip()
    brands = [your_brand] + list(competitors or [])
    brands = [b.strip() for b in brands if b.strip()][:MAX_BRANDS]
    # de-dupe, preserve order
    seen, ordered = set(), []
    for b in brands:
        if b.lower() not in seen:
            seen.add(b.lower())
            ordered.append(b)
    brands = ordered

    # Parallel brand scans (independent I/O; _fetch's per-host breaker keeps it safe).
    per, status = {}, {}
    with ThreadPoolExecutor(max_workers=min(len(brands), MAX_BRANDS) or 1) as ex:
        for b, (posts, st) in zip(brands, ex.map(lambda x: (_brand_posts(x, sources)), brands)):
            per[b] = posts
            status[b] = st

    # LinkedIn audience size per brand: compliant company-page read via the user's
    # own session. Fetched SEQUENTIALLY (not parallel) on purpose: a burst of
    # simultaneous Voyager calls from one personal session is the bot pattern
    # LinkedIn rate-limits and can challenge the real account. Each call is cached
    # 6h, so a repeated comparison is free; an absent/checkpointed cookie or an
    # unresolvable brand degrades to None rather than blocking the comparison.
    li = {b: linkedin_firmographics(b) for b in brands}

    # ---- per-brand aggregates -> share of voice ----
    rows = []
    for b in brands:
        posts = per[b]
        n = len(posts)
        eng = sum(eng_total(p["engagement"]) for p in posts)
        voices = len({(p["platform"], p["author"]) for p in posts if p.get("author")})
        by_chan = {}
        for p in posts:
            by_chan[p["platform"]] = by_chan.get(p["platform"], 0) + 1
        rows.append({"brand": b, "you": b.lower() == your_brand.lower(),
                     "posts": n, "engagement": int(eng), "voices": voices,
                     "eng_per_post": round(eng / n, 1) if n else 0.0,
                     "eng_per_voice": round(eng / voices, 1) if voices else 0.0,
                     "top_channel": max(by_chan, key=by_chan.get) if by_chan else None,
                     "linkedin": li.get(b) or {}})
    tot_posts = sum(r["posts"] for r in rows) or 1
    tot_eng = sum(r["engagement"] for r in rows) or 1
    vols = sorted(r["posts"] for r in rows)
    epps = sorted(r["eng_per_post"] for r in rows)
    med_vol = vols[len(vols) // 2] if vols else 0
    med_epp = epps[len(epps) // 2] if epps else 0.0
    avg_epp = tot_eng / tot_posts
    for r in rows:
        r["voice_pct"] = round(r["posts"] / tot_posts * 100, 1)
        r["reach_pct"] = round(r["engagement"] / tot_eng * 100, 1)
        r["impact"] = round(r["eng_per_post"] / avg_epp, 1) if avg_epp else 0.0  # 1.0x = field average
        r["quadrant"] = _quadrant(r["posts"] >= med_vol, r["eng_per_post"] >= med_epp)
    rows.sort(key=lambda r: r["reach_pct"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # ---- channel breakdown: posts per platform per brand ----
    channels = {}
    for b in brands:
        for p in per[b]:
            channels.setdefault(p["platform"], {}).setdefault(b, 0)
            channels[p["platform"]][b] += 1
    channel_breakdown = [{"channel": plat, "by_brand": d} for plat, d in
                         sorted(channels.items(), key=lambda kv: -sum(kv[1].values()))]

    # ---- top voices per brand ----
    voices_by_brand = {b: top_voices(per[b]) for b in brands}

    # ---- influencer overlap: authors appearing for two or more brands ----
    author_brands = {}
    for b in brands:
        for key in {(p["platform"], p["author"]) for p in per[b] if p.get("author")}:
            author_brands.setdefault(key, set()).add(b)
    overlap = [{"author": a, "platform": plat, "brands": sorted(bs),
                "shared_across": len(bs)}
               for (plat, a), bs in author_brands.items() if len(bs) >= 2]
    overlap.sort(key=lambda d: (-d["shared_across"], d["author"].lower()))

    # ---- provenance: what we scraped + the date range it covers ----
    all_posts = [{**p, "brand": b} for b in brands for p in per[b]]
    dated = sorted((p for p in all_posts if p.get("ts")), key=lambda p: p["ts"])
    date_range = ({"earliest": dated[0]["ts"], "latest": dated[-1]["ts"],
                   "dated": len(dated), "total": len(all_posts)} if dated
                  else {"earliest": None, "latest": None, "dated": 0,
                        "total": len(all_posts)})
    evidence = [{"brand": p["brand"], "platform": p["platform"],
                 "author": p.get("author"), "text": (p.get("text") or "")[:140],
                 "ago": p.get("ago"), "ts": p.get("ts"),
                 "engagement": p.get("engagement")}
                for p in sorted(all_posts, key=lambda p: eng_total(p.get("engagement")),
                                reverse=True)[:10]]

    return {
        "your_brand": your_brand,
        "brands": brands,
        "date_range": date_range,
        "evidence": evidence,
        "insights": _insights(rows, channel_breakdown, overlap, your_brand),
        "share_of_voice": rows,
        "positioning": [{"brand": r["brand"], "you": r["you"],
                         "x_volume": r["posts"], "y_engagement": r["eng_per_post"],
                         "quadrant": r["quadrant"]} for r in rows],
        "channel_breakdown": channel_breakdown,
        "top_voices": voices_by_brand,
        "overlap": overlap[:12],
        "platform_status": status,
    }


def competitor_intel(your_brand, competitors, sources=None):
    """Standalone composite for direct/agent calls. Returns (payload, status)."""
    your_brand = (your_brand or "").strip()
    if not your_brand:
        return {"error": "Enter your brand to run the comparison."}, 400
    comps = [c.strip() for c in (competitors or []) if c and c.strip()]
    if not comps:
        return {"error": "Enter at least one competitor brand."}, 400
    return analyze(your_brand, comps, sources), 200
