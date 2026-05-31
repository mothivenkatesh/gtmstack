"""
Synthetic Dev Persona engine for GTMstack.

Five developer archetypes, distilled from a corpus of ~17.5K real developer
voices across HackerNews / Reddit / Dev.to / GitHub / Quora. You paste a piece
of go-to-market copy (a landing headline, a cold email, an ad, a social post, a
sales line) and each persona reacts the way that kind of developer actually
would, with a verdict and a fit score, before you spend a rupee launching it.

Two engines, same output shape:
  • model  — a fast, deterministic heuristic grounded in how each archetype
             evaluates copy (works with no key, always on).
  • ai     — richer in-character reactions from a live model, used automatically
             when one is configured (ANTHROPIC_API_KEY, or any OpenAI-compatible
             endpoint via GTMSTACK_LLM_BASE_URL, e.g. a RunPod-hosted model).
"""
import re

# ── the five synthetic dev personas ──────────────────────────────────────────
# weights: how much each signal moves THIS persona. positives are scaled up,
# the three penalty signals (fluff, contact_sales, wall_of_text) pull down.
PERSONAS = [
    {
        "id": "indie", "name": "The Indie Hacker", "emoji": "🛠️",
        "tagline": "22–30, shipping a side project on React + Vercel, pre-revenue",
        "cares": ["working code in their stack", "pricing they can see", "time to first result", "a free way to start"],
        "turnoffs": ["“Contact Sales”", "no code sample", "setup longer than an evening", "marketing walls"],
        "weights": {"code": 3, "pricing": 3, "speed": 3, "social": 2, "community": 1, "ai": 1, "security": 0, "agency": 0,
                    "fluff": -2, "contact_sales": -3, "wall_of_text": -2},
    },
    {
        "id": "cto", "name": "The Startup CTO", "emoji": "🚀",
        "tagline": "25–35, technical founder at $1K–50K MRR, ships under pressure",
        "cares": ["reliability at scale", "what happens when it breaks", "speed that protects cash flow", "proof other builders trust it"],
        "turnoffs": ["feature lists with no substance", "no support story", "vague reliability claims"],
        "weights": {"pain": 3, "security": 2, "speed": 2, "social": 2, "community": 1, "code": 2, "pricing": 1, "ai": 1, "agency": 0,
                    "fluff": -2, "contact_sales": -2, "wall_of_text": -1},
    },
    {
        "id": "agency", "name": "The Agency Dev", "emoji": "🧰",
        "tagline": "24–40, builds on WordPress / Shopify for paying clients",
        "cares": ["a plugin that just works", "setup under an hour", "a brand the client recognizes", "commission they can earn"],
        "turnoffs": ["custom code required", "no ready integration", "no partner program"],
        "weights": {"agency": 3, "pricing": 2, "speed": 2, "community": 1, "social": 1, "code": 1, "ai": 0, "security": 0, "pain": 1,
                    "fluff": -1, "contact_sales": -2, "wall_of_text": -1},
    },
    {
        "id": "infra", "name": "The Senior Infra Engineer", "emoji": "🛡️",
        "tagline": "30–45, Staff/Principal, reads breach postmortems before integrating",
        "cares": ["security posture", "uptime and SLAs", "consistency from sandbox to production", "an honest failure story"],
        "turnoffs": ["“best-in-class” superlatives", "no security detail", "marketing over metrics"],
        "weights": {"security": 3, "pain": 2, "code": 2, "community": 1, "pricing": 1, "ai": 1, "social": 0, "speed": 1, "agency": 0,
                    "fluff": -3, "contact_sales": -1, "wall_of_text": 0},
    },
    {
        "id": "ai", "name": "The AI-Native Builder", "emoji": "🤖",
        "tagline": "22–35, wiring LLM agents, wants the layer an AI can one-shot",
        "cares": ["MCP / agent-native access", "an API an AI assistant can wire up", "bleeding-edge that just works", "examples it can copy"],
        "turnoffs": ["no AI/agent story", "legacy-feeling docs", "nothing for an agent to call"],
        "weights": {"ai": 3, "code": 2, "speed": 2, "community": 1, "social": 1, "pricing": 1, "security": 1, "pain": 0, "agency": 0,
                    "fluff": -2, "contact_sales": -1, "wall_of_text": -1},
    },
]

# ── signal detection (what the copy actually contains) ────────────────────────
SIGNALS = {
    "code":          r"```|</?\w+>|\bconst \b|\bimport \b|\bnpm \b|\bpip \b|\bcurl \b|\bfunction\b|\bapi\.|\.then\(|sdk|endpoint",
    "pricing":       r"(₹|rs\.?\s?\d|\$\d|\b\d{1,2}(\.\d+)?\s?%|\bfree\b|per month|/mo\b|pricing|no card)",
    "speed":         r"(\b\d+\s?(min|minute|hour|hr|day)s?\b|go live|live in|in minutes|quickstart|get started in|ship today)",
    "pain":          r"(freeze|frozen|hold|held|suspend|ghost|outage|downtime|stuck|broke|broken|failed|no support|wait days)",
    "social":        r"(\bdevelopers?\b.{0,18}(use|switched|love|trust)|\b\d[\d,]*[kK+]?\s?(developers|builders|teams|users)|switched from|testimonial)",
    "community":     r"(discord|community|\bdocs\b|documentation|tutorial|open[- ]source|github|examples?)",
    "ai":            r"(\bmcp\b|\bai\b|\bagent|\bllm\b|claude|gpt|copilot|one[- ]?shot|agentic)",
    "security":      r"(security|breach|compliance|\bsla\b|uptime|soc ?2|pci|audit|reliab|encrypt|99\.\d%)",
    "agency":        r"(plugin|woocommerce|wordpress|shopify|magento|commission|referral|white[- ]?label|for your clients?)",
    "fluff":         r"(seamless|robust|world[- ]class|revolution|cutting[- ]edge|best[- ]in[- ]class|empower|unlock|next[- ]gen|game[- ]?chang|leverage|synerg|supercharge|elevate)",
    "contact_sales": r"(contact sales|book a demo|talk to sales|request a quote|get in touch|schedule a call)",
}

CTYPES = {
    "landing": "landing page",
    "email":   "cold email",
    "ad":      "ad",
    "social":  "social post",
    "sales":   "sales line",
}

# small per-content-type emphasis (multiplies a couple of signal weights)
CTYPE_BOOST = {
    "email":  {"pain": 1.4, "fluff": 1.4},   # subject must name a pain, fluff dies fast
    "ad":     {"speed": 1.3, "wall_of_text": 1.6, "fluff": 1.3},
    "social": {"social": 1.3, "fluff": 1.3},
    "sales":  {"pain": 1.3, "security": 1.2},
    "landing": {},
}


def _signals(text):
    t = text.lower()
    found = {k: len(re.findall(pat, t)) for k, pat in SIGNALS.items()}
    found["wall_of_text"] = 1 if (len(text) > 600 and found["code"] == 0) else 0
    return found


def _voice(p_id, s, score):
    """An in-character one-liner, chosen by the dominant signal for this persona."""
    has = lambda k: s.get(k, 0) > 0
    L = {
        "indie": {
            "contact_sales": "“Contact Sales” for a dev tool? Tab closed. I just wanted a price and a code sample.",
            "no_pricing":    "Where’s the pricing? If I can’t see what it costs in 5 seconds I’m back on Google.",
            "code":          "Okay, there’s a snippet in my stack and a free start. I’ll actually try this tonight.",
            "speed":         "“Live in minutes” with code on the page is exactly the bar. I might ship with this.",
            "fluff":         "This reads like a brochure. Show me code and a number, not “seamless” anything.",
            "pos":           "Reads buildable. A price and a copy-paste example would seal it.",
            "neg":           "Nothing here tells me how fast I go live or what it costs. Next.",
        },
        "cto": {
            "pain":          "It names the exact thing that burned me last quarter. That gets my attention.",
            "security":      "Reliability and a real support story matter more than features. This is close.",
            "social":        "If builders I trust already switched, I’ll book the eval. Social proof beats the pitch.",
            "fluff":         "Feature list, no substance. Tell me what happens at 3am when it breaks.",
            "pos":           "Solid. I’d want an SLA and one migration story before I move my team.",
            "neg":           "I’m shipping under pressure. This doesn’t say why it’s safer than what I run today.",
        },
        "agency": {
            "agency":        "A real plugin plus a commission line? That’s a client I can set up this week.",
            "no_pricing":    "My client asks ‘how much.’ If the page won’t say, I can’t recommend it.",
            "speed":         "Under-an-hour setup is the whole game for client work. Promising.",
            "fluff":         "I need a working plugin and a brand my client knows, not a manifesto.",
            "pos":           "Workable for client builds. Show the plugin and what I earn per client.",
            "neg":           "No ready integration and nothing in it for me. I’ll use what I already install.",
        },
        "infra": {
            "fluff":          "“Best-in-class” is a red flag. Give me uptime numbers and a breach policy.",
            "security":       "Security posture and sandbox-to-prod parity stated up front. That earns a real look.",
            "pain":           "It’s honest about failure modes. Honesty reads as competence to me.",
            "code":           "Consistent API and visible docs. I’ll read the reference before I trust the copy.",
            "pos":            "Credible. I’d still read your postmortems before integrating.",
            "neg":            "All marketing, no metrics. I can’t put this in front of production.",
        },
        "ai": {
            "ai":            "MCP / agent-native? My coding assistant can wire this up. That’s why I’d pick it.",
            "code":          "If an AI can one-shot the integration from these examples, I’m in.",
            "speed":         "Fast + agent-friendly is the combo I look for. Worth a spike.",
            "fluff":         "No agent story, no examples an AI can copy. Not built for how I work.",
            "pos":           "On-trend. Add an MCP/agent example and you’ve got me.",
            "neg":           "Nothing here for an agent to call. I’ll keep using whatever just works in my workflow.",
        },
    }[p_id]
    # priority order of conditions
    if has("contact_sales") and "contact_sales" in L: return L["contact_sales"]
    if has("fluff") and not has("code") and "fluff" in L: return L["fluff"]
    if p_id == "ai" and has("ai"): return L["ai"]
    if p_id == "agency" and has("agency"): return L["agency"]
    if p_id == "infra" and has("security"): return L["security"]
    if p_id == "cto" and has("pain"): return L["pain"]
    if p_id in ("indie",) and not has("pricing") and "no_pricing" in L: return L["no_pricing"]
    if p_id == "agency" and not has("pricing") and "no_pricing" in L: return L["no_pricing"]
    if has("code") and "code" in L: return L["code"]
    if has("speed") and "speed" in L: return L["speed"]
    if has("social") and "social" in L: return L["social"]
    if has("pain") and "pain" in L: return L["pain"]
    return L["pos"] if score >= 55 else L["neg"]


def _worked_fix(p, s):
    pos = [k for k in ("code", "pricing", "speed", "pain", "social", "community", "ai", "security", "agency")
           if s.get(k, 0) > 0 and p["weights"].get(k, 0) > 0]
    label = {"code": "a code sample", "pricing": "visible pricing", "speed": "a fast time-to-value",
             "pain": "a named pain point", "social": "developer social proof", "community": "docs / community",
             "ai": "an AI / agent angle", "security": "a security or reliability signal", "agency": "a plugin / partner angle"}
    worked = ", ".join(label[k] for k in pos[:3]) if pos else "nothing this persona weights highly"
    # the highest-weighted thing that's missing
    want = sorted([(p["weights"].get(k, 0), k) for k in p["weights"] if p["weights"].get(k, 0) > 0 and s.get(k, 0) == 0], reverse=True)
    fixmap = {"code": "add a copy-paste code snippet in a common stack",
              "pricing": "put a real price on the page (kill any “Contact Sales”)",
              "speed": "promise a concrete time-to-first-result (e.g. “live in 15 minutes”)",
              "pain": "open by naming the exact pain they feel today",
              "social": "add proof a real developer switched or uses it",
              "community": "link docs, examples, or a live community",
              "ai": "show an MCP / agent example an AI assistant can run",
              "security": "state uptime, an SLA, or your failure-handling honestly",
              "agency": "show the plugin and the per-client commission upfront"}
    fix = fixmap[want[0][1]] if want else "tighten the copy; it already hits this persona’s bar"
    if s.get("fluff", 0) and p["weights"].get("fluff", 0) < 0:
        fix = "cut the buzzwords (“seamless”, “world-class”); " + fix
    return worked, fix


def _heuristic(text, ctype, p):
    s = _signals(text)
    boost = CTYPE_BOOST.get(ctype, {})
    score = 46.0
    for k, wt in p["weights"].items():
        n = min(s.get(k, 0), 2)
        if n == 0:
            continue
        wt = wt * boost.get(k, 1.0)
        score += wt * n * (6 if wt < 0 else 5)
    score = int(max(6, min(97, round(score))))
    verdict = "Would engage" if score >= 70 else ("On the fence" if score >= 45 else "Would skip")
    worked, fix = _worked_fix(p, s)
    return {"id": p["id"], "name": p["name"], "emoji": p["emoji"], "tagline": p["tagline"],
            "score": score, "verdict": verdict, "reaction": _voice(p["id"], s, score),
            "worked": worked, "fix": fix}


# ── optional Claude upgrade ───────────────────────────────────────────────────
def _llm_preview(text, ctype, chosen):
    import json
    from _llm import chat
    roster = "\n".join(
        f'- id "{p["id"]}" = {p["name"]} ({p["tagline"]}). Cares about: {", ".join(p["cares"])}. '
        f'Turned off by: {", ".join(p["turnoffs"])}.' for p in chosen)
    sys = (
        "You simulate how real developers react to go-to-market copy. You are a composite of ~17,500 "
        "developer voices from HackerNews, Reddit, Dev.to, GitHub and Quora. Be blunt and specific, "
        "the way developers actually talk. Never use marketing language yourself."
    )
    user = (
        f"Content type: {CTYPES.get(ctype, ctype)}.\nThe copy to react to:\n\"\"\"\n{text}\n\"\"\"\n\n"
        f"React AS each of these personas:\n{roster}\n\n"
        "Return ONLY a JSON array, one object per persona, in this exact shape:\n"
        '[{"id": "<persona id>", "score": <0-100 how likely THIS persona engages>, '
        '"verdict": "Would engage" | "On the fence" | "Would skip", '
        '"reaction": "<one blunt in-character sentence, max 24 words>", '
        '"worked": "<what landed, short>", "fix": "<the single highest-impact change, short>"}]'
    )
    raw = chat(sys, user, max_tokens=1200)
    raw = raw[raw.find("["): raw.rfind("]") + 1]
    arr = json.loads(raw)
    by_id = {a.get("id"): a for a in arr}
    out = []
    for p in chosen:
        a = by_id.get(p["id"], {})
        out.append({"id": p["id"], "name": p["name"], "emoji": p["emoji"], "tagline": p["tagline"],
                    "score": int(max(0, min(100, a.get("score", 50)))),
                    "verdict": a.get("verdict") or "On the fence",
                    "reaction": a.get("reaction") or "", "worked": a.get("worked") or "", "fix": a.get("fix") or ""})
    return out


def preview(text, ctype="landing", persona_ids=None, use_llm=None):
    text = (text or "").strip()
    if not text:
        return {"error": "Paste some copy to preview."}, 400
    if len(text) > 4000:
        text = text[:4000]
    ids = persona_ids or [p["id"] for p in PERSONAS]
    chosen = [p for p in PERSONAS if p["id"] in ids] or PERSONAS

    from _llm import configured
    engine = "model"
    results = None
    want_llm = configured() if use_llm is None else use_llm
    if want_llm:
        try:
            results = _llm_preview(text, ctype, chosen)
            engine = "ai"
        except Exception:
            results = None
    if results is None:
        results = [_heuristic(text, ctype, p) for p in chosen]

    overall = round(sum(r["score"] for r in results) / len(results))
    verdict = "Launch-ready" if overall >= 70 else ("Promising, needs work" if overall >= 45 else "Rework before launch")
    return {"overall": overall, "verdict": verdict, "engine": engine,
            "content_type": ctype, "results": results}, 200


def persona_roster():
    """Lightweight list for the UI to render persona chips."""
    return [{"id": p["id"], "name": p["name"], "emoji": p["emoji"], "tagline": p["tagline"],
             "cares": p["cares"]} for p in PERSONAS]
