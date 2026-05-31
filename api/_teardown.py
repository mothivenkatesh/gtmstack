"""
GTMstack — Creator teardown engine.

Give it a handle. It pulls the creator's recent public posts (the Signals
person engine) and a model names the patterns worth copying: the hooks that
open their posts, the formats they lean on, the themes they own, the cadence
you can infer, and the single move to steal this week. One model call, JSON
out, with a transparent heuristic fallback when no model is configured. The
model is provider-agnostic (see _llm): Anthropic, or any OpenAI-compatible
endpoint such as a RunPod-hosted reasoning model.

This is the analysis half of the 'creator_teardown' play: the play runs Signals
and this engine as two visible steps, so a caller can inspect the posts that
were read before trusting the patterns drawn from them. Shared by app.py
(Flask) and the Vercel handler through the plays layer.
"""
from __future__ import annotations

from _signals import lookup as signals_lookup
from _util import eng_num as _eng_num, eng_str as _eng_str

MAX_POSTS = 24    # how many recent posts we feed the model
MIN_POSTS = 3     # below this there is nothing worth tearing down


def _top_post(posts):
    """The single most-engaged post, scored by its largest engagement metric.
    Returns the post dict or None when nothing carries engagement."""
    best, score = None, 0.0
    for p in posts:
        s = max((_eng_num(e.get("value")) for e in p.get("engagement") or []),
                default=0.0)
        if s > score:
            best, score = p, s
    return best


def collect_posts(sources, cap=MAX_POSTS):
    """Flatten ok sources into [{platform, kind, text, ago, engagement}].
    Skips rows with no text (pure metadata), so the model only sees real
    posts. Order follows the Signals card (newest-leaning per platform)."""
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
                "ago": a.get("ago") or "",
                "engagement": a.get("engagement") or [],
            })
    return posts[:cap]


def _llm_teardown(handle, posts):
    """One model call. Returns the teardown dict or raises (caller falls back).
    Every pattern carries citations to the posts it was drawn from, so the
    'every insight traces to underlying posts' guardrail is enforced in code."""
    import json
    from _llm import chat
    from _reliability import confidence, ground, audit_line

    lines = []
    for i, p in enumerate(posts, 1):
        eng = _eng_str(p["engagement"])
        tag = f'{p["platform"]}·{p["kind"]}' + (f'·{p["ago"]}' if p["ago"] else "") \
            + (f'·{eng}' if eng else "")
        lines.append(f'{i}. [{tag}] {p["text"]}')
    corpus = "\n".join(lines)

    sys = (
        "You reverse-engineer how a creator wins attention, so a GTM team can copy "
        "the pattern and not the words. Be concrete and blunt. Quote at most a few "
        "words from any single post and never reproduce a whole post. Cite the post "
        "numbers each pattern is drawn from, and never invent a pattern the posts do "
        "not support: leave a category empty rather than padding it."
    )
    user = (
        f"Here are {len(posts)} recent posts from @{handle}, each numbered and tagged "
        f"[platform·kind·age·engagement]:\n\n{corpus}\n\n"
        "Name the repeatable patterns. For each one, cite the post numbers it is "
        "drawn from. Return ONLY a JSON object in this exact shape:\n"
        '{"summary": "<2 plain sentences: what this creator is good at>", '
        '"hooks": [{"text": "<an opening move that recurs, named as a tactic>", "cites": [<post #s>]}, ...], '
        '"formats": [{"text": "<a post structure or format they lean on>", "cites": [<post #s>]}, ...], '
        '"themes": [{"text": "<a topic or angle they own>", "cites": [<post #s>]}, ...], '
        '"cadence": "<one line on the rhythm you can infer>", '
        '"steal": "<the single highest-leverage move to copy this week>"}'
    )
    raw = chat(sys, user, max_tokens=1100)
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    d = json.loads(raw)
    hooks = ground(d.get("hooks"), posts)
    formats = ground(d.get("formats"), posts)
    themes = ground(d.get("themes"), posts)
    conf = confidence(posts)
    return {
        "summary": str(d.get("summary") or "").strip(),
        "hooks": hooks,
        "formats": formats,
        "themes": themes,
        "cadence": str(d.get("cadence") or "").strip(),
        "steal": str(d.get("steal") or "").strip(),
        "confidence": conf,
        "audit": audit_line(conf, [hooks, formats, themes]),
    }


def _heuristic_teardown(posts):
    """No-key fallback. Honest and shallow: counts by platform and kind, and
    grounds the most-engaged post as the format to study (with a real citation).
    Names itself as such so the UI never passes it off as model analysis."""
    from _reliability import confidence, audit_line
    by_platform, by_kind = {}, {}
    for p in posts:
        by_platform[p["platform"]] = by_platform.get(p["platform"], 0) + 1
        by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1
    plats = ", ".join(f"{v} on {k}" for k, v in sorted(
        by_platform.items(), key=lambda kv: -kv[1]))
    kinds = ", ".join(f"{v} {k}" for k, v in sorted(
        by_kind.items(), key=lambda kv: -kv[1]))
    formats = [{"text": f"Post mix: {kinds}.", "cites": [], "evidence": [],
                "grounded": False}]
    # Ground the single most-engaged post as the format to study. This is the one
    # honest, evidence-backed signal a no-model read can surface.
    top = _top_post(posts)
    steal = ""
    if top:
        idx = posts.index(top) + 1
        eng = _eng_str(top["engagement"])
        snip = " ".join(top["text"].split())[:48].rstrip()
        where = f'{top["platform"]} {top["kind"]}'
        steal = (f'Study your strongest post first, a {where}'
                 + (f' ({eng})' if eng else "")
                 + f': "{snip}…". Copy its opening and structure, not its words.')
        formats.append({
            "text": f"Strongest post to study: a {where}" + (f" ({eng})" if eng else ""),
            "cites": [idx],
            "evidence": [{"n": idx, "platform": top["platform"],
                          "snippet": " ".join(top["text"].split())[:80]}],
            "grounded": True})
    conf = confidence(posts)
    return {
        "summary": (f"Read {len(posts)} recent posts: {plats}. "
                    "Connect a model for the full pattern analysis."),
        "hooks": [],
        "formats": formats,
        "themes": [],
        "cadence": "",
        "steal": steal,
        "confidence": conf,
        "audit": audit_line(conf, [formats]),
    }


def analyze(handle, posts, use_llm=None):
    """Run the teardown over already-collected posts. Returns (result, engine)
    where engine is 'ai' | 'model'. Never raises: a model failure degrades to
    the heuristic so the play step still completes."""
    from _llm import configured
    engine = "model"
    result = None
    want = configured() if use_llm is None else use_llm
    if want:
        try:
            result = _llm_teardown(handle, posts)
            engine = "ai"
        except Exception:
            result = None
    if result is None:
        result = _heuristic_teardown(posts)
        engine = "model"
    return result, engine


def teardown(handle, sources=None, use_llm=None):
    """Standalone composite (Signals -> analyze), for direct/agent calls.
    Returns (payload, status). The play uses the two pieces above instead, so
    each engine call shows up as its own step."""
    handle = (handle or "").strip().lstrip("@")
    if not handle:
        return {"error": "Enter a handle or name to tear down."}, 400
    foot, st = signals_lookup(handle, sources, unit="person")
    if st != 200:
        return foot, st
    src = foot.get("sources") or []
    posts = collect_posts(src)
    found = [s for s in src if s.get("status") == "ok"]
    payload = {
        "handle": handle,
        "posts_analyzed": len(posts),
        "platforms_read": [s.get("platform") for s in found],
        "platform_status": [{"platform": s.get("platform"), "status": s.get("status"),
                             "note": s.get("note")} for s in src],
        "evidence": posts,
    }
    if len(posts) < MIN_POSTS:
        payload["engine"] = "none"
        payload["teardown"] = None
        payload["note"] = ("Not enough public posts to tear down. Connect X or "
                           "LinkedIn for a logged-in read, or try a creator who "
                           "posts on GitHub, Reddit, or YouTube.")
        return payload, 200
    result, engine = analyze(handle, posts, use_llm)
    payload["engine"] = engine
    payload["teardown"] = result
    return payload, 200
