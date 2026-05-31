"""
GTMstack — Content Performance engine (agent 12).

Reads your OWN recent posts and says what works: the formats that earn
engagement, the themes that land, and the best time to post (the longitudinal
view native analytics hide). Reliable by the agent-spec: format winners and
themes cite the posts behind them, best-time windows show the metric, and the
read is honest about how much history it has.

Longitudinal caveat, stated plainly: true month-over-month needs continuous
capture. GTMstack runs inline, not on a scheduler, so this engine keeps a small
local snapshot store that accumulates a little more history each run; a
month-over-month delta appears once two snapshots are far enough apart. Daily
auto-capture is the Phase-2 (scheduled) job, and the store is local-dev only
(a serverless filesystem is ephemeral), so it degrades to no-history silently.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from _signals import lookup as signals_lookup
from _util import eng_str, eng_total

MAX_POSTS = 30
MIN_POSTS = 3
_STORE = os.path.join(os.path.dirname(__file__), "_store")


def collect_own_posts(sources, cap=MAX_POSTS):
    """Flatten the user's own ok sources into posts that keep ts (needed for
    best-time). Mirrors the teardown collector but carries the timestamp."""
    posts = []
    for s in sources or []:
        if s.get("status") != "ok":
            continue
        platform = s.get("platform")
        for a in s.get("activity") or []:
            text = (a.get("text") or "").strip()
            if not text:
                continue
            posts.append({
                "platform": platform,
                "kind": a.get("kind") or "post",
                "text": text,
                "ts": a.get("ts"),
                "ago": a.get("ago") or "",
                "engagement": a.get("engagement") or [],
            })
    return posts[:cap]


def _daypart(h):
    return ("morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17
            else "evening" if 17 <= h < 22 else "night")


def best_times(posts):
    """Average engagement by weekday and by day-part, ranked. Shows the metric
    (avg engagement + post count) so the recommendation is transparent."""
    buckets = {}   # label -> [count, total_engagement]
    for p in posts:
        ts = p.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue
        e = eng_total(p.get("engagement"))
        for label in (dt.strftime("%A"), _daypart(dt.hour)):
            b = buckets.setdefault(label, [0, 0.0])
            b[0] += 1
            b[1] += e
    ranked = sorted(((lbl, c, tot / c) for lbl, (c, tot) in buckets.items() if c),
                    key=lambda x: x[2], reverse=True)
    return [{"window": lbl, "posts": c, "avg_engagement": int(avg)}
            for lbl, c, avg in ranked[:4]]


def _format_winners(posts):
    """Rank platform·kind formats by average engagement; cite the strongest post
    in each. Grounded so a 'winner' always points at the post that won."""
    from _reliability import ground
    groups = {}   # (platform,kind) -> {n, total, best_idx, best_eng}
    for i, p in enumerate(posts, 1):
        e = eng_total(p.get("engagement"))
        g = groups.setdefault((p["platform"], p["kind"]),
                              {"n": 0, "total": 0.0, "best_idx": i, "best_eng": -1.0})
        g["n"] += 1
        g["total"] += e
        if e > g["best_eng"]:
            g["best_eng"], g["best_idx"] = e, i
    items = []
    for (plat, kind), g in sorted(groups.items(),
                                  key=lambda kv: -(kv[1]["total"] / kv[1]["n"])):
        avg = int(g["total"] / g["n"])
        items.append({"text": f'{plat} {kind}: {g["n"]} post(s), avg {avg:,} engagement',
                      "cites": [g["best_idx"]]})
    return ground(items, posts)


def _llm_themes(handle, posts):
    """Model names the themes that land, each citing posts. Raises on failure."""
    import json as _json
    from _llm import chat
    from _reliability import ground
    lines = []
    for i, p in enumerate(posts, 1):
        eng = eng_str(p["engagement"])
        tag = f'{p["platform"]}·{p["kind"]}' + (f'·{p["ago"]}' if p["ago"] else "") \
            + (f'·{eng}' if eng else "")
        lines.append(f'{i}. [{tag}] {p["text"]}')
    corpus = "\n".join(lines)
    sys = (
        "You analyze a creator's OWN recent posts and say what is working for them, "
        "so they do more of it. Be concrete. Cite the post numbers behind each point "
        "and never invent a pattern the posts do not show."
    )
    user = (
        f"Here are {len(posts)} recent posts by @{handle}, each tagged "
        f"[platform·kind·age·engagement]:\n\n{corpus}\n\n"
        "Return ONLY a JSON object in this exact shape:\n"
        '{"summary": "<2 plain sentences on what is working>", '
        '"top_themes": [{"text": "<a theme or angle that earns engagement>", "cites": [<post #s>]}, ...], '
        '"next_actions": [{"text": "<a specific, do-more-of-this action>", "cites": [<post #s>]}, ...]}'
    )
    raw = chat(sys, user, max_tokens=1000)
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    d = _json.loads(raw)
    return {
        "summary": str(d.get("summary") or "").strip(),
        "top_themes": ground(d.get("top_themes"), posts),
        "next_actions": ground(d.get("next_actions"), posts),
    }


def _heuristic_themes(handle, posts):
    """No-model read: point at the single best-performing post as the thing to
    do more of. Grounded, honest, never empty."""
    from _reliability import ground
    best_i, best_e = 1, -1.0
    for i, p in enumerate(posts, 1):
        e = eng_total(p.get("engagement"))
        if e > best_e:
            best_e, best_i = e, i
    nxt = [{"text": "Do more like your best-performing recent post.",
            "cites": [best_i]}]
    return {
        "summary": (f"Read {len(posts)} of your recent posts. "
                    "Connect a model for the theme analysis."),
        "top_themes": ground([], posts),
        "next_actions": ground(nxt, posts),
    }


def _store_path(handle):
    safe = "".join(c for c in handle.lower() if c.isalnum() or c in "-_") or "x"
    return os.path.join(_STORE, f"content_{safe}.json")


def _snapshot(handle, posts):
    """Append this run's averages to a small local store and return a
    month-over-month delta when an old-enough snapshot exists. All file IO is
    best-effort: a read-only or serverless filesystem degrades to no history."""
    avg = (sum(eng_total(p["engagement"]) for p in posts) / len(posts)) if posts else 0.0
    now = datetime.now(timezone.utc)
    rec = {"at": now.isoformat(), "n": len(posts), "avg_engagement": round(avg, 1)}
    history = []
    try:
        os.makedirs(_STORE, exist_ok=True)
        path = _store_path(handle)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                history = json.load(f) or []
        history.append(rec)
        history = history[-60:]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except Exception:
        return {"snapshots": 1, "mom_delta": None,
                "note": "History store unavailable here (serverless or read-only)."}

    mom = None
    for old in history[:-1]:
        try:
            age_days = (now - datetime.fromisoformat(old["at"])).days
        except (ValueError, TypeError, KeyError):
            continue
        if age_days >= 25 and old.get("avg_engagement"):
            mom = round((avg - old["avg_engagement"]) / old["avg_engagement"] * 100, 1)
            break
    note = None if mom is not None else (
        "Building history. Run again over the coming weeks for a month-over-month trend."
        if len(history) < 2 else
        "Not enough spacing yet for a month-over-month read.")
    return {"snapshots": len(history), "mom_delta": mom, "note": note}


def analyze(handle, posts, use_llm=None):
    """Run the performance read over already-collected own-posts. Returns
    (result, engine). Never raises: a model failure degrades to the heuristic."""
    from _reliability import confidence, audit_line
    from _llm import configured
    engine, themed = "model", None
    want = configured() if use_llm is None else use_llm
    if want:
        try:
            themed = _llm_themes(handle, posts)
            engine = "ai"
        except Exception:
            themed = None
    if themed is None:
        themed = _heuristic_themes(handle, posts)

    winners = _format_winners(posts)
    times = best_times(posts)
    conf = confidence(posts)
    result = {
        "summary": themed["summary"],
        "format_winners": winners,
        "top_themes": themed["top_themes"],
        "best_post_times": times,
        "next_actions": themed["next_actions"],
        "trend": _snapshot(handle, posts),
        "confidence": conf,
        "audit": audit_line(conf, [winners, themed["top_themes"], themed["next_actions"]]),
    }
    return result, engine


def performance(handle, sources=None, use_llm=None):
    """Standalone composite (Signals own-posts -> analyze). Returns (payload,
    status). The play uses the pieces so the read shows up as two steps."""
    handle = (handle or "").strip().lstrip("@")
    if not handle:
        return {"error": "Enter your handle to read your content."}, 400
    foot, st = signals_lookup(handle, sources, unit="person")
    if st != 200:
        return foot, st
    posts = collect_own_posts(foot.get("sources") or [])
    if len(posts) < MIN_POSTS:
        return {"handle": handle, "engine": "none", "performance": None,
                "evidence": posts,
                "note": "Not enough of your posts found. Connect the platform you post on."}, 200
    result, engine = analyze(handle, posts, use_llm)
    return {"handle": handle, "engine": engine, "evidence": posts,
            "performance": result}, 200
