"""
GTMstack - shared enrichment (sentiment + author company).

One home for the sentiment lexicon and the batched LLM tagger, so the daily
report (_report.py) and the competitive monitor (_monitor.py) tag posts the same
way instead of drifting apart. When a model is configured (ANTHROPIC_API_KEY or
an OpenAI-compatible endpoint via _llm) it does one batched JSON call; otherwise
it falls back to the lexicon. Never raises.

No em dashes.
"""
from __future__ import annotations

import json

# Sentiment lexicons, tuned for payment-company chatter. Negative words carry
# the payments-specific failure vocabulary (holds, rolling reserve, settlement).
_NEG = ("hold", "held", "frozen", "froze", "stuck", "worst", "scam", "fraud", "cheat",
        "deactivat", "blocked", "withheld", "issue", "problem", "avoid", "terrible",
        "pathetic", "horrible", "harass", "no support", "poor support", "not settled",
        "rolling reserve", "disput", "complaint", "nightmare", "useless", "failing",
        "failed", "delay", "rejected", "hidden", "pain", "bug", "down", "outage",
        "disappointed", "refund")
_POS = ("best", "great", "smooth", "recommend", "love", "better than", "reliable",
        "happy", "switched to", "works well", "fast", "no issues", "solid",
        "seamless", "easy to integrate", "approved", "instantly", "instant",
        "excellent")


def heuristic_sentiment(text):
    """Lexicon sentiment: positive | negative | neutral. Deterministic, no model."""
    t = (text or "").lower()
    neg = sum(1 for k in _NEG if k in t)
    pos = sum(1 for k in _POS if k in t)
    if neg > pos and neg:
        return "negative"
    if pos > neg and pos:
        return "positive"
    return "neutral"


def profile_url(platform, author):
    a = (author or "").lstrip("@").strip()
    if not a:
        return ""
    return {
        "github": f"https://github.com/{a}",
        "reddit": f"https://www.reddit.com/user/{a}",
        "x": f"https://x.com/{a}",
    }.get(platform, "")          # youtube/linkedin/reviews: author is a name


def _model_tag(items):
    """One batched model call. items = [{text, platform, author}, ...].
    Returns {index: {"sentiment": s, "company": c}} for the rows the model tagged,
    or {} when no model or the call fails. Never raises."""
    try:
        from _llm import configured, chat
    except Exception:
        return {}
    if not configured() or not items:
        return {}
    try:
        lines = [
            f'{i}. [{p.get("platform","")}'
            f'{("/@" + p["author"]) if p.get("author") else ""}] '
            f'{(p.get("text") or "")[:300]}'
            for i, p in enumerate(items, 1)
        ]
        sysmsg = (
            "You tag social posts and reviews about payment companies. For each "
            "numbered item return its sentiment toward the company discussed "
            "(positive, negative, or neutral) and the company the AUTHOR works "
            "for, inferred from the text and handle. Use \"Unknown\" if the "
            "author's employer is not evident. Do not invent a company."
        )
        user = ("Items:\n" + "\n".join(lines) + "\n\nReturn ONLY a JSON array: "
                '[{"i": <number>, "sentiment": "positive|negative|neutral", '
                '"company": "<employer or Unknown>"}, ...]')
        raw = chat(sysmsg, user, max_tokens=1500)
        raw = raw[raw.find("["): raw.rfind("]") + 1]
        out = {}
        for row in json.loads(raw):
            i = int(row.get("i", 0)) - 1
            s = str(row.get("sentiment", "")).lower().strip()
            comp = str(row.get("company", "")).strip()
            out[i] = {
                "sentiment": s if s in ("positive", "negative", "neutral") else None,
                "company": comp or None,
            }
        return out
    except Exception:
        return {}


def enrich_mentions(mentions, cap=60, use_llm=None):
    """Tag each mention dict IN PLACE with sentiment / company / enrich_mode and
    return the list. The model call is capped by COUNT (the first `cap` mentions),
    not by rank, because every exported row needs a sentiment column; the overflow
    keeps its lexicon tag. enrich_mode records how each row was tagged so the UI
    can badge model-vs-lexicon honestly.

    use_llm forces the model on/off; default None means 'use it if configured'.
    """
    if not mentions:
        return mentions

    # lexicon baseline for every row
    for m in mentions:
        m["sentiment"] = m.get("sentiment") or heuristic_sentiment(m.get("text"))
        m.setdefault("company", "Unknown")
        m["enrich_mode"] = "lexicon"

    want = None
    if use_llm is not False:
        try:
            from _llm import configured
            want = configured() if use_llm is None else use_llm
        except Exception:
            want = False
    if not want:
        return mentions

    head = mentions[:cap]
    tags = _model_tag([
        {"text": m.get("text"), "platform": m.get("where") or m.get("platform"),
         "author": m.get("author")} for m in head
    ])
    for i, m in enumerate(head):
        t = tags.get(i)
        if not t:
            continue
        if t.get("sentiment"):
            m["sentiment"] = t["sentiment"]
        if t.get("company"):
            m["company"] = t["company"]
        m["enrich_mode"] = "model"
    return mentions
