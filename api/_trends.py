"""
GTMstack — Trend & Top-Voice discovery engine (agent 14).

Give it a topic. It scans the dev-native channels (the Signals keyword feed),
ranks what is moving by VELOCITY (engagement per hour, the metric shown, never
hidden), names the voices worth engaging, and a model synthesizes what is heating
up and where to jump in.

Reliable by the agent-spec: the velocity metric is transparent, every synthesised
insight cites the posts it was drawn from (_reliability.ground), and a thin feed
yields a low-confidence read instead of a confident guess. Reuses the same _llm +
_reliability scaffold as the teardown, so 'live AI' and 'built-in model' behave
identically across the content agents.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _signals import lookup as signals_lookup
from _util import eng_str, eng_total

MAX_FEED = 40        # how many mentions we rank
TOP_POSTS = 8        # trending posts surfaced
TOP_VOICES = 6       # voices surfaced
MIN_FEED = 3         # below this there is no trend to read


def _age_hours(ts):
    """Hours since an ISO timestamp; None when unparseable. Floored at 30 min so
    a brand-new post does not divide velocity by ~zero."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 0.5)


def _velocity(post):
    """Engagement per hour, the transparent ranking metric. An undated post is
    treated as ~3 days old so it ranks below dated, genuinely-moving posts."""
    eng = eng_total(post.get("engagement"))
    h = _age_hours(post.get("ts"))
    return eng / (h if h is not None else 72.0)


def collect_feed(feed, cap=MAX_FEED):
    """Flatten the Signals keyword feed into velocity-ranked posts."""
    posts = []
    for a in feed or []:
        text = (a.get("text") or "").strip()
        if not text:
            continue
        posts.append({
            "platform": a.get("platform"),
            "kind": a.get("kind") or "mention",
            "author": a.get("author") or "",
            "text": text,
            "url": a.get("url") or "",
            "ts": a.get("ts"),
            "ago": a.get("ago") or "",
            "engagement": a.get("engagement") or [],
            "velocity": round(_velocity(a), 1),
        })
    posts.sort(key=lambda p: p["velocity"], reverse=True)
    return posts[:cap]


def top_voices(posts, cap=TOP_VOICES):
    """Aggregate by author: post count + total engagement, ranked by engagement.
    why shows the numbers, so the ranking is never a black box."""
    agg = {}
    for p in posts:
        a = p["author"]
        if not a:
            continue
        d = agg.setdefault((p["platform"], a), {
            "author": a, "platform": p["platform"], "posts": 0, "engagement": 0.0})
        d["posts"] += 1
        d["engagement"] += eng_total(p["engagement"])
    voices = sorted(agg.values(), key=lambda d: d["engagement"], reverse=True)
    return [{
        "author": v["author"], "platform": v["platform"],
        "posts": v["posts"], "engagement": int(v["engagement"]),
        "why": f'{v["posts"]} post{"s" if v["posts"] != 1 else ""}, '
               f'{int(v["engagement"]):,} total engagement',
    } for v in voices[:cap]]


def _llm_synthesis(topic, posts):
    """Model names what is heating + where to engage, each insight citing posts."""
    import json
    from _llm import chat
    from _reliability import ground
    lines = []
    for i, p in enumerate(posts, 1):
        eng = eng_str(p["engagement"])
        tag = f'{p["platform"]}' + (f'·@{p["author"]}' if p["author"] else "") \
            + (f'·{p["ago"]}' if p["ago"] else "") + (f'·{eng}' if eng else "") \
            + f'·vel {p["velocity"]}'
        lines.append(f'{i}. [{tag}] {p["text"]}')
    corpus = "\n".join(lines)
    sys = (
        "You read a live feed of posts about a topic, ranked by velocity "
        "(engagement per hour), and tell a GTM team what is heating up and where "
        "to jump in. Be concrete. Cite the post numbers behind each point and "
        "never invent a trend the feed does not show."
    )
    user = (
        f'Topic: "{topic}". {len(posts)} recent posts, highest-velocity first, '
        f'each tagged [platform·author·age·engagement·velocity]:\n\n{corpus}\n\n'
        "Return ONLY a JSON object in this exact shape:\n"
        '{"summary": "<2 plain sentences on what is moving>", '
        '"topics_heating": [{"text": "<a sub-theme gaining traction>", "cites": [<post #s>]}, ...], '
        '"suggested_engagements": [{"text": "<a specific post or voice to engage, and why>", "cites": [<post #s>]}, ...]}'
    )
    raw = chat(sys, user, max_tokens=1100)
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    d = json.loads(raw)
    return {
        "summary": str(d.get("summary") or "").strip(),
        "topics_heating": ground(d.get("topics_heating"), posts),
        "suggested_engagements": ground(d.get("suggested_engagements"), posts),
    }


def _heuristic_synthesis(topic, posts, voices):
    """No-model read: name the heating sub-themes by the highest-velocity posts
    and point at the top voice. Grounded and honest, never empty."""
    from _reliability import ground
    heating = [{"text": f'{p["platform"]} post moving at {p["velocity"]}/hr',
                "cites": [i]} for i, p in enumerate(posts[:3], 1)]
    sugg = []
    if voices:
        v = voices[0]
        idx = next((i for i, p in enumerate(posts, 1)
                    if p["author"] == v["author"] and p["platform"] == v["platform"]), None)
        sugg.append({"text": f'Engage @{v["author"]} on {v["platform"]} ({v["why"]})',
                     "cites": [idx] if idx else []})
    return {
        "summary": (f'Scanned {len(posts)} recent posts on "{topic}". '
                    "Connect a model for the full trend read."),
        "topics_heating": ground(heating, posts),
        "suggested_engagements": ground(sugg, posts),
    }


def analyze(topic, posts, voices=None, use_llm=None):
    """Synthesize over already-ranked posts. Returns (result, engine) where
    engine is 'ai' | 'model'. Never raises: a model failure degrades to the
    grounded heuristic so the play step still completes."""
    from _reliability import confidence, audit_line
    from _llm import configured
    voices = top_voices(posts) if voices is None else voices
    engine, synth = "model", None
    want = configured() if use_llm is None else use_llm
    if want:
        try:
            synth = _llm_synthesis(topic, posts)
            engine = "ai"
        except Exception:
            synth = None
    if synth is None:
        synth = _heuristic_synthesis(topic, posts, voices)
    conf = confidence(posts)
    synth["confidence"] = conf
    synth["audit"] = audit_line(conf, [synth.get("topics_heating"),
                                       synth.get("suggested_engagements")])
    return synth, engine


def discover(topic, sources=None, use_llm=None):
    """Scan -> rank -> synthesize, standalone composite for direct/agent calls.
    Returns (payload, status). The play uses the pieces above so the scan and the
    synthesis show up as two inspectable steps."""
    topic = (topic or "").strip()
    if not topic:
        return {"error": "Enter a topic or keyword to scan."}, 400
    foot, st = signals_lookup(topic, sources, unit="keyword")
    if st != 200:
        return foot, st
    posts = collect_feed(foot.get("feed") or [])
    voices = top_voices(posts)
    payload = {
        "topic": topic,
        "mentions": len(posts),
        "platform_status": [{"platform": s.get("platform"), "status": s.get("status"),
                             "note": s.get("note")} for s in (foot.get("sources") or [])],
        "trending_posts": posts[:TOP_POSTS],
        "top_voices": voices,
    }
    if len(posts) < MIN_FEED:
        payload["engine"] = "none"
        payload["synthesis"] = None
        payload["note"] = ("Too few live mentions to call a trend. Try a broader "
                           "topic, or connect X / Reddit for a fuller feed.")
        return payload, 200
    synth, engine = analyze(topic, posts, voices, use_llm)
    payload["engine"] = engine
    payload["synthesis"] = synth
    return payload, 200
