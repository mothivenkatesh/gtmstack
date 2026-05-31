"""
GTMstack — Plays (composite, agent-callable multi-step tools).

A play chains existing single-tool engines into ONE run an agent can call and
branch on. Each play takes a small input dict and returns:
    { "play": id, "ok": bool, "steps": [ {tool, label, status, summary,
      output, error}, ... ] }
so a caller can read the final result OR inspect any intermediate stage.

Phase 1 ships ONE play, on purpose. Today's four tools are mostly terminal:
only the content axis composes cleanly. 'video_messaging' pulls a video's
transcript (the extract engine) and runs it through the dev-persona engine, to
show how the target developer audience would react to that video's messaging.
It reads best on a pitch / launch / demo video, where the transcript actually
carries the GTM claims the personas weigh.

The marquee contact-axis plays (prospect -> enrich -> validate -> route to
CRM / Slack) are deferred: every step needs a connector none of the four tools
provide. That is the Phase-2 (Activepieces) trigger, documented in CLAUDE.md.
Adding a play later = one entry in PLAYS with a run() that calls engines in
sequence; the API surface and UI do not change.

Shared by app.py (Flask) and api/plays.py (Vercel). Runs INLINE: the returned
payload already carries every step's result, so there is nothing to poll.
"""
from __future__ import annotations

from _core import build_api, fetch_transcript
from _personas import preview as persona_preview
from _signals import lookup as signals_lookup
from _teardown import collect_posts, analyze as teardown_analyze
from _trends import collect_feed, top_voices, analyze as trends_analyze, \
    MIN_FEED, TOP_POSTS
from _content_perf import collect_own_posts, analyze as contentperf_analyze, \
    MIN_POSTS as CP_MIN
from _compete import analyze as compete_analyze

# CTYPES lives in _personas; keep a local copy of the keys so a bad 'ctype'
# input degrades to a sane default without importing the whole map.
_CTYPE_KEYS = ("landing", "email", "ad", "social", "sales")
_PREVIEW_CHARS = 600   # how much transcript the response echoes back for the UI

# Build the transcript API once (honours WEBSHARE_PROXY_* / YT_PROXY like app.py).
_yt_api = None


def _api():
    global _yt_api
    if _yt_api is None:
        _yt_api = build_api()
    return _yt_api


def _step(tool, label, status, summary, output=None, error=None):
    """One stage of a play. status: ok | error."""
    return {"tool": tool, "label": label, "status": status,
            "summary": summary, "output": output, "error": error}


def _run_video_messaging(inp):
    """extract(url) -> persona(transcript). Returns the play result dict."""
    url = (inp.get("url") or "").strip()
    ctype = (inp.get("ctype") or "landing").strip().lower()
    if ctype not in _CTYPE_KEYS:
        ctype = "landing"
    persona_ids = inp.get("personas") or None
    pid = "video_messaging"

    if not url:
        return {"play": pid, "ok": False, "steps": [_step(
            "extract", "Pull transcript", "error",
            "Paste a video URL to run this play.", error="missing url")]}

    # Step 1 — transcript.
    tp, ts = fetch_transcript(url, inp.get("lang"), None, api=_api())
    if ts != 200:
        return {"play": pid, "ok": False, "steps": [_step(
            "extract", "Pull transcript", "error",
            tp.get("error") or f"Transcript failed (HTTP {ts}).",
            error=tp.get("error"))]}
    plain = (tp.get("plain") or "").strip()
    s1 = _step(
        "extract", "Pull transcript", "ok",
        f'{tp.get("word_count", 0):,} words · {tp.get("duration_ts", "")} · '
        f'{(tp.get("language") or "").strip()}',
        output={
            "video_id": tp.get("video_id"),
            "word_count": tp.get("word_count"),
            "duration_ts": tp.get("duration_ts"),
            "language": tp.get("language"),
            "preview": plain[:_PREVIEW_CHARS] + ("…" if len(plain) > _PREVIEW_CHARS else ""),
        })
    if not plain:
        s1["status"] = "error"
        s1["summary"] = "The transcript came back empty, so there is nothing to react to."
        return {"play": pid, "ok": False, "steps": [s1]}

    # Step 2 — dev-persona reactions to the transcript.
    pp, ps = persona_preview(plain, ctype, persona_ids)
    if ps != 200:
        return {"play": pid, "ok": False, "steps": [s1, _step(
            "persona", "Persona reactions", "error",
            pp.get("error") or f"Persona run failed (HTTP {ps}).",
            error=pp.get("error"))]}
    s2 = _step(
        "persona", "Persona reactions", "ok",
        f'Overall {pp.get("overall")}/100 · {pp.get("verdict")} '
        f'({"live AI" if pp.get("engine") == "ai" else "built-in model"})',
        output=pp)
    return {"play": pid, "ok": True, "steps": [s1, s2]}


def _run_creator_teardown(inp):
    """signals(person) -> teardown(posts). Pull a creator's recent posts, then
    a model names the patterns worth copying. Returns the play result dict."""
    handle = (inp.get("handle") or "").strip().lstrip("@")
    pid = "creator_teardown"

    if not handle:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Pull recent posts", "error",
            "Enter a creator handle or name to run this play.",
            error="missing handle")]}

    # Step 1 — pull the creator's public footprint and flatten it to posts.
    foot, st = signals_lookup(handle, inp.get("sources"), unit="person")
    if st != 200:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Pull recent posts", "error",
            foot.get("error") or f"Signals lookup failed (HTTP {st}).",
            error=foot.get("error"))]}
    src = foot.get("sources") or []
    posts = collect_posts(src)
    found = [s for s in src if s.get("status") == "ok"]
    # Summarise by where the posts actually came from, not which sources merely
    # resolved: a platform can return 'ok' with zero text-bearing activity.
    dist = {}
    for p in posts:
        dist[p["platform"]] = dist.get(p["platform"], 0) + 1
    dist_str = ", ".join(f"{n} {plat}" for plat, n in sorted(
        dist.items(), key=lambda kv: -kv[1])) or "none"
    s1 = _step(
        "signals", "Pull recent posts", "ok",
        f'{len(posts)} posts: {dist_str}',
        output={
            "handle": handle,
            "platforms_read": [s.get("platform") for s in found],
            "platform_status": [{"platform": s.get("platform"),
                                 "status": s.get("status"),
                                 "note": s.get("note")} for s in src],
            "evidence": posts,
        })
    if len(posts) < 3:
        s1["status"] = "error"
        s1["summary"] = ("Not enough public posts to tear down. Connect X or "
                         "LinkedIn for a logged-in read, or try a creator who "
                         "posts on GitHub, Reddit, or YouTube.")
        return {"play": pid, "ok": False, "steps": [s1]}

    # Step 2 — model names the repeatable patterns.
    result, engine = teardown_analyze(handle, posts)
    n = len(result.get("hooks", [])) + len(result.get("formats", [])) \
        + len(result.get("themes", []))
    band = (result.get("confidence") or {}).get("band", "")
    s2 = _step(
        "teardown", "Find the patterns", "ok",
        f'{n} patterns · {band} confidence · {len(posts)} posts '
        f'({"live AI" if engine == "ai" else "built-in model"})',
        output={"engine": engine, **result})
    return {"play": pid, "ok": True, "steps": [s1, s2]}


def _run_trend_discovery(inp):
    """signals(keyword) -> trends(feed). Scan a topic, rank by velocity, name the
    voices, and a model reads where to jump in. Returns the play result dict."""
    topic = (inp.get("topic") or "").strip()
    pid = "trend_discovery"

    if not topic:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Scan the niche", "error",
            "Enter a topic or keyword to run this play.", error="missing topic")]}

    # Step 1 — scan the dev-native channels for live mentions.
    foot, st = signals_lookup(topic, inp.get("sources"), unit="keyword")
    if st != 200:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Scan the niche", "error",
            foot.get("error") or f"Signals lookup failed (HTTP {st}).",
            error=foot.get("error"))]}
    posts = collect_feed(foot.get("feed") or [])
    src = foot.get("sources") or []
    dist = {}
    for p in posts:
        dist[p["platform"]] = dist.get(p["platform"], 0) + 1
    dist_str = ", ".join(f"{n} {plat}" for plat, n in sorted(
        dist.items(), key=lambda kv: -kv[1])) or "none"
    s1 = _step(
        "signals", "Scan the niche", "ok",
        f'{len(posts)} mentions: {dist_str}',
        output={
            "topic": topic,
            "platform_status": [{"platform": s.get("platform"),
                                 "status": s.get("status"),
                                 "note": s.get("note")} for s in src],
            "evidence": posts[:6],
        })
    if len(posts) < MIN_FEED:
        s1["status"] = "error"
        s1["summary"] = ("Too few live mentions to call a trend. Try a broader "
                         "topic, or connect X / Reddit for a fuller feed.")
        return {"play": pid, "ok": False, "steps": [s1]}

    # Step 2 — rank by velocity, name the voices, read the trend.
    voices = top_voices(posts)
    result, engine = trends_analyze(topic, posts, voices)
    band = (result.get("confidence") or {}).get("band", "")
    s2 = _step(
        "trends", "Rank and read the trend", "ok",
        f'{len(posts)} ranked · {len(voices)} voices · {band} confidence '
        f'({"live AI" if engine == "ai" else "built-in model"})',
        output={"engine": engine, "topic": topic,
                "trending_posts": posts[:TOP_POSTS], "top_voices": voices, **result})
    return {"play": pid, "ok": True, "steps": [s1, s2]}


def _run_content_performance(inp):
    """signals(own posts) -> content performance. Reads your own recent posts and
    says what works: format winners, themes, best time. Returns the result dict."""
    handle = (inp.get("handle") or "").strip().lstrip("@")
    pid = "content_performance"

    if not handle:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Read your posts", "error",
            "Enter your handle to read your content.", error="missing handle")]}

    # Step 1 — pull the user's own recent posts.
    foot, st = signals_lookup(handle, inp.get("sources"), unit="person")
    if st != 200:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Read your posts", "error",
            foot.get("error") or f"Signals lookup failed (HTTP {st}).",
            error=foot.get("error"))]}
    posts = collect_own_posts(foot.get("sources") or [])
    src = foot.get("sources") or []
    dist = {}
    for p in posts:
        dist[p["platform"]] = dist.get(p["platform"], 0) + 1
    dist_str = ", ".join(f"{n} {plat}" for plat, n in sorted(
        dist.items(), key=lambda kv: -kv[1])) or "none"
    s1 = _step(
        "signals", "Read your posts", "ok",
        f'{len(posts)} posts: {dist_str}',
        output={
            "handle": handle,
            "platform_status": [{"platform": s.get("platform"),
                                 "status": s.get("status"),
                                 "note": s.get("note")} for s in src],
            "evidence": posts[:6],
        })
    if len(posts) < CP_MIN:
        s1["status"] = "error"
        s1["summary"] = ("Not enough of your posts found. Connect the platform "
                         "you post on, or check the handle.")
        return {"play": pid, "ok": False, "steps": [s1]}

    # Step 2 — what works: format winners, themes, best time.
    result, engine = contentperf_analyze(handle, posts)
    band = (result.get("confidence") or {}).get("band", "")
    s2 = _step(
        "contentperf", "What's working", "ok",
        f'{len(result.get("format_winners", []))} format reads · {band} confidence '
        f'({"live AI" if engine == "ai" else "built-in model"})',
        output={"engine": engine, **result})
    return {"play": pid, "ok": True, "steps": [s1, s2]}


def _run_competitor_intel(inp):
    """signals(each brand) -> compete. Scan your brand + competitors, then return
    share of voice, market positioning, channel mix, top voices, and the voices
    shared across competitors. Returns the play result dict."""
    your_brand = (inp.get("your_brand") or "").strip()
    competitors = [c.strip() for c in (inp.get("competitors") or "").split(",")
                   if c.strip()]
    pid = "competitor_intel"

    if not your_brand:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Scan the brands", "error",
            "Enter your brand to run the comparison.", error="missing brand")]}
    if not competitors:
        return {"play": pid, "ok": False, "steps": [_step(
            "signals", "Scan the brands", "error",
            "Enter at least one competitor brand (comma-separated).",
            error="missing competitors")]}

    result = compete_analyze(your_brand, competitors)
    brands = result["brands"]
    sov = result["share_of_voice"]

    # Step 1 — what got scanned (merge each brand's per-platform status into pills).
    merged = {}
    for st_list in (result.get("platform_status") or {}).values():
        for s in st_list:
            p = s.get("platform")
            if p and (p not in merged or s.get("status") == "ok"):
                merged[p] = s
    total_posts = sum(r["posts"] for r in sov)
    dist = ", ".join(f'{r["brand"]} {r["posts"]}' for r in
                     sorted(sov, key=lambda r: -r["posts"]))
    s1 = _step(
        "signals", "Scan the brands", "ok",
        f'{total_posts} posts across {len(brands)} brands: {dist}',
        output={"platform_status": list(merged.values()), "evidence": []})
    if total_posts == 0:   # truly nothing came back (every source empty)
        s1["status"] = "error"
        s1["summary"] = ("No mentions found for these brands right now. Try "
                         "better-known names, or the sources may be rate-limited "
                         "(realtime re-scrapes every run); retry in a minute.")
        return {"play": pid, "ok": False, "steps": [s1]}

    # Step 2 — the competitor-intelligence panels.
    leader = sov[0]["brand"] if sov else ""
    you = next((r for r in sov if r["you"]), None)
    you_rank = f'#{you["rank"]} of {len(sov)}' if you else "n/a"
    s2 = _step(
        "compete", "Competitor intelligence", "ok",
        f'{leader} leads on reach · you are {you_rank} · '
        f'{len(result["overlap"])} shared voices',
        output={**result})
    return {"play": pid, "ok": True, "steps": [s1, s2]}


PLAYS = {
    "video_messaging": {
        "id": "video_messaging",
        "name": "Video messaging check",
        "desc": ("Pull a video's transcript and see how your five target "
                 "developer personas would react to its messaging. Reads best "
                 "on a pitch, launch, or demo video."),
        "category": "Content research",
        "steps": ["Pull transcript", "Persona reactions"],
        "input": [
            {"key": "url", "label": "Video URL", "required": True},
            {"key": "ctype", "label": "Treat the messaging as",
             "default": "landing", "options": list(_CTYPE_KEYS)},
        ],
        "run": _run_video_messaging,
    },
    "creator_teardown": {
        "id": "creator_teardown",
        "name": "Creator teardown",
        "desc": ("Give it a creator's handle. It pulls their recent public posts "
                 "and names the patterns worth copying: the hooks, formats, "
                 "themes, cadence, and the one move to steal this week."),
        "category": "Content research",
        "steps": ["Pull recent posts", "Find the patterns"],
        "input": [
            {"key": "handle", "label": "Creator handle or name", "required": True},
        ],
        "run": _run_creator_teardown,
    },
    "trend_discovery": {
        "id": "trend_discovery",
        "name": "Trend & top-voice scan",
        "desc": ("Give it a topic. It scans the dev-native channels, ranks what's "
                 "moving by velocity (engagement per hour, shown), names the voices "
                 "worth engaging, and reads where to jump in."),
        "category": "Content research",
        "steps": ["Scan the niche", "Rank and read the trend"],
        "input": [
            {"key": "topic", "label": "Topic or keyword", "required": True},
        ],
        "run": _run_trend_discovery,
    },
    "content_performance": {
        "id": "content_performance",
        "name": "Content performance read",
        "desc": ("Give it your own handle. It reads your recent posts and says what "
                 "works: the formats that earn engagement, the themes that land, and "
                 "the best time to post, each tied to the posts behind it."),
        "category": "Content research",
        "steps": ["Read your posts", "What's working"],
        "input": [
            {"key": "handle", "label": "Your handle or name", "required": True},
        ],
        "run": _run_content_performance,
    },
    "competitor_intel": {
        "id": "competitor_intel",
        "name": "Competitor intelligence",
        "desc": ("Give it your brand and your competitors. It reads who is posting "
                 "and tagging about each across the dev-native channels and returns "
                 "share of voice, market positioning, top voices, and the voices "
                 "shared across competitors."),
        "category": "Content research",
        "steps": ["Scan the brands", "Competitor intelligence"],
        "input": [
            {"key": "your_brand", "label": "Your brand", "required": True},
            {"key": "competitors", "label": "Competitor brands (comma-separated)",
             "required": True},
        ],
        "run": _run_competitor_intel,
    },
}


def list_plays():
    """Metadata only (no run fn) so the UI and agents can discover plays."""
    return [{k: p[k] for k in ("id", "name", "desc", "category", "steps", "input")}
            for p in PLAYS.values()]


def run_play(play_id, inp=None):
    """Execute a play by id. Returns (payload, status). Never raises for an
    unknown play or a failing step: an unknown id is a 404, a step blowing up
    lands in the steps array with status 'error' (the play is still a 200, the
    caller branches on ok / per-step status)."""
    p = PLAYS.get((play_id or "").strip())
    if not p:
        return {"error": f"Unknown play: {play_id!r}."}, 404
    try:
        return p["run"](inp or {}), 200
    except Exception as e:   # an engine raised unexpectedly; report, do not 500
        return {"play": p["id"], "ok": False, "steps": [_step(
            "play", p["name"], "error", f"{type(e).__name__}: {e}",
            error=str(e))]}, 200
