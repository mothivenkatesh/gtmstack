"""
GTMstack - daily keyword-group Signals report.

For one keyword group it runs a Carlsen-ordered scan (api/_carlsen.py): the safe,
high-yield sources first, LinkedIn (the king) last, sequential, and resigned on
the first challenge, all inside a wall-clock budget. It dedupes the mentions,
ranks them by the positional evaluation, enriches the top ones with sentiment and
the author's company (via _llm, heuristic fallback), computes share-of-voice
across the group's brands, and reuses the trends engine for a grounded synthesis.
The report is stored (Postgres when DATABASE_URL is set, else a local JSON
snapshot) so the in-app Reports tab can read it.

No new scraping primitives: every read goes through _signals.lookup, which goes
through the resilient _fetch transport. This module only decides order, pace, and
what to keep.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import _carlsen as carlsen
from _groups import ALL_SOURCES, get_group
from _signals import lookup as signals_lookup
from _trends import collect_feed, top_voices, analyze as trends_analyze
from _util import eng_total
# Sentiment + profile-url primitives live in the shared _enrich module, so the
# report and the competitive monitor tag posts identically (no drifting copies).
from _enrich import heuristic_sentiment as _heuristic_sentiment, profile_url as _profile_url

TOP_POSTS = 12          # how many mentions we enrich + surface
SYNTH_FEED = 40         # how many ranked posts the synthesis reads
DEFAULT_BUDGET_S = 45.0

_STORE = Path(__file__).resolve().parent / "_store" / "reports"


def _brand_of(text, group):
    """Which of the group's brands a post is about (primary first, then
    competitors), for share-of-voice. None when it matched only a broad term."""
    t = (text or "").lower()
    for b in (group.get("primary") or []):
        if b.lower() in t:
            return b
    for b in (group.get("competitors") or []):
        if b.lower() in t:
            return b
    return None


def _brand_of(text, group):
    """Which of the group's brands a post is about (primary first, then
    competitors), for share-of-voice. None when it matched only a broad term."""
    t = (text or "").lower()
    for b in (group.get("primary") or []):
        if b.lower() in t:
            return b
    for b in (group.get("competitors") or []):
        if b.lower() in t:
            return b
    return None


def _share_of_voice(posts, group):
    brands = list(dict.fromkeys((group.get("primary") or []) + (group.get("competitors") or [])))
    agg = {b: {"brand": b, "mentions": 0, "engagement": 0.0,
               "you": b in (group.get("primary") or [])} for b in brands}
    for p in posts:
        b = _brand_of(p.get("text"), group)
        if b in agg:
            agg[b]["mentions"] += 1
            agg[b]["engagement"] += eng_total(p.get("engagement"))
    rows = [r for r in agg.values() if r["mentions"]]
    tot = sum(r["engagement"] for r in rows) or 1.0
    for r in rows:
        r["engagement"] = int(r["engagement"])
        r["reach_pct"] = round(r["engagement"] / tot * 100, 1)
    rows.sort(key=lambda r: r["engagement"], reverse=True)
    return rows


def _enrich(posts, use_llm=None):
    """Add sentiment + the author's company to each surfaced post. One batched
    model call (cheap, JSON out); falls back to lexicon sentiment + Unknown
    company when no model is configured. Never raises."""
    out = []
    for p in posts:
        out.append({
            "platform": p.get("platform"),
            "author": p.get("author") or "",
            "profile_url": _profile_url(p.get("platform"), p.get("author")),
            "text": (p.get("text") or "").strip(),
            "url": p.get("url") or "",
            "ts": p.get("ts"),
            "ago": p.get("ago") or "",
            "engagement": p.get("engagement") or [],
            "score": p.get("score"),
            "keyword": p.get("keyword") or "",
            "sentiment": _heuristic_sentiment(p.get("text")),
            "company": "Unknown",
        })
    from _llm import configured, chat
    want = configured() if use_llm is None else use_llm
    if not want or not out:
        return out
    try:
        lines = [f'{i}. [{p["platform"]}{("/@" + p["author"]) if p["author"] else ""}] '
                 f'{p["text"][:300]}' for i, p in enumerate(out, 1)]
        sys = (
            "You tag social posts about payment companies. For each numbered post "
            "return its sentiment toward the company discussed (positive, negative, "
            "or neutral) and the company the AUTHOR works for, inferred from the "
            "post and handle. Use \"Unknown\" if the author's employer is not "
            "evident. Do not invent a company."
        )
        user = ("Posts:\n" + "\n".join(lines) + "\n\nReturn ONLY a JSON array: "
                '[{"i": <post number>, "sentiment": "positive|negative|neutral", '
                '"company": "<employer or Unknown>"}, ...]')
        raw = chat(sys, user, max_tokens=1200)
        raw = raw[raw.find("["): raw.rfind("]") + 1]
        for row in json.loads(raw):
            i = int(row.get("i", 0)) - 1
            if 0 <= i < len(out):
                s = str(row.get("sentiment", "")).lower().strip()
                if s in ("positive", "negative", "neutral"):
                    out[i]["sentiment"] = s
                comp = str(row.get("company", "")).strip()
                if comp:
                    out[i]["company"] = comp
    except Exception:
        pass            # keep the heuristic enrichment
    return out


def run_report(group_id, sources=None, budget_s=DEFAULT_BUDGET_S, use_llm=None):
    """Scan one group the Carlsen way, enrich, synthesize, store. Returns
    (report, status). Never raises on a single source failing."""
    group = get_group(group_id)
    if not group:
        return {"error": f"Unknown group: {group_id}"}, 404
    sources = sources or group.get("sources") or ALL_SOURCES

    try:
        from _fetch import status as fetch_status
        fstat = fetch_status()
    except Exception:
        fstat = {}

    moves = carlsen.plan(group, sources, fstat, budget_s)
    deadline = time.monotonic() + budget_s
    posts, log, seen, src_status = [], [], set(), {}

    for mv in moves:
        src = mv["source"]
        if time.monotonic() > deadline:
            log.append({"move": "clock", "note": "budget spent, holding position"})
            break
        fails, found = 0, 0
        mv_deadline = min(deadline, time.monotonic() + mv["budget_s"])
        for kw in mv["keywords"]:
            if time.monotonic() > mv_deadline:
                break
            if carlsen.resign(src, fails):
                log.append({"move": src, "note": f"resigned to protect the account ({fails} fail)",
                            "is_king": mv["is_king"]})
                break
            try:
                foot, st = signals_lookup(kw, [src], unit="keyword")
                for s in (foot.get("sources") or []):
                    src_status[s.get("platform")] = {"status": s.get("status"), "note": s.get("note")}
                if st == 200:
                    for p in collect_feed(foot.get("feed") or []):
                        key = (p.get("platform"), p.get("url") or (p.get("text") or "")[:120])
                        if key in seen:
                            continue
                        seen.add(key)
                        p["keyword"] = kw
                        posts.append(p)
                        found += 1
                else:
                    fails += 1
            except Exception:
                fails += 1
            if mv["sequential"]:
                time.sleep(carlsen.politeness_gap(src, fails))
        log.append({"move": src, "is_king": mv["is_king"], "keywords": len(mv["keywords"]),
                    "found": found, "fails": fails, "budget_s": mv["budget_s"]})

    ranked = carlsen.rank(posts, group)
    top = _enrich(ranked[:TOP_POSTS], use_llm)
    sentiment = {"positive": 0, "negative": 0, "neutral": 0}
    for p in posts:
        sentiment[_heuristic_sentiment(p.get("text"))] += 1

    synth, engine = ({}, "none")
    if len(ranked) >= 3:
        try:
            synth, engine = trends_analyze(group["name"], ranked[:SYNTH_FEED], use_llm=use_llm)
        except Exception:
            synth, engine = {}, "none"

    report = {
        "group": {k: group.get(k) for k in ("id", "name", "keywords", "primary", "competitors")},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_s": budget_s,
        "totals": {"mentions": len(posts), "enriched": len(top),
                   "sources_hit": sorted({p.get("platform") for p in posts if p.get("platform")})},
        "sentiment": sentiment,
        "share_of_voice": _share_of_voice(posts, group),
        "top_posts": top,
        "top_voices": top_voices(ranked),
        "synthesis": synth,
        "engine": engine,
        "strategy_log": log,
        "platform_status": [{"platform": k, **v} for k, v in src_status.items()],
    }
    _store_report(report)
    return report, 200


# ---- storage: Postgres when configured, else a local JSON snapshot -----------
def _store_report(report):
    gid = report["group"]["id"]
    gname = report["group"]["name"]
    try:
        import _db
        if _db.configured() and _db.save_report(gid, gname, report):
            return "db"
    except Exception:
        pass
    try:
        d = _STORE / gid
        d.mkdir(parents=True, exist_ok=True)
        stamp = report["generated_at"].replace(":", "-")
        (d / f"{stamp}.json").write_text(json.dumps(report, ensure_ascii=False))
        return "file"
    except Exception:
        return "none"


def reports_index(group_id=None, limit=30):
    """Light index of recent reports (id, group, when, summary), newest first."""
    try:
        import _db
        if _db.configured():
            return _db.list_reports(group_id, limit)
    except Exception:
        pass
    out = []
    roots = [(_STORE / group_id)] if group_id else (list(_STORE.iterdir()) if _STORE.exists() else [])
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.json"), reverse=True):
            try:
                p = json.loads(f.read_text())
            except Exception:
                continue
            out.append({"id": f"{root.name}/{f.stem}", "group_id": root.name,
                        "group_name": p.get("group", {}).get("name"),
                        "generated_at": p.get("generated_at"),
                        "summary": (p.get("synthesis") or {}).get("summary")})
    out.sort(key=lambda r: r.get("generated_at") or "", reverse=True)
    return out[:limit]


def latest_report(group_id):
    try:
        import _db
        if _db.configured():
            r = _db.latest_report(group_id)
            if r:
                return r
    except Exception:
        pass
    root = _STORE / group_id
    files = sorted(root.glob("*.json"), reverse=True) if root.exists() else []
    if files:
        try:
            return json.loads(files[0].read_text())
        except Exception:
            return None
    return None


def get_report(report_id):
    if report_id and "/" in str(report_id):          # local "group/stamp"
        gid, stamp = str(report_id).split("/", 1)
        f = _STORE / gid / f"{stamp}.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                return None
    try:
        import _db
        if _db.configured():
            return _db.get_report(report_id)
    except Exception:
        pass
    return None
