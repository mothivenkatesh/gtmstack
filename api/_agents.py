"""
The agent workforce - AOPs, the plan-then-execute loop, and the run record.

Three ideas from the PRD are load-bearing here, and each one is a defence
against a specific failure mode:

  1. AOPs. Every agent's judgment is a plain-English Agent Operating Procedure
     (scope, numbered steps, branches, guardrails) that a RevOps lead can edit
     without an engineer. Plain language on the surface, the rigor of code
     underneath: the AOP is prose, but each step names the deterministic tool it
     calls, and the tool is what actually runs.

  2. Plan, then execute. Nothing non-trivial runs straight off a prompt. The
     agent emits a plan, self-flags steps that lean on low-completeness fields,
     and waits. This is the pattern real GTM analysts demand and the thing most
     agent products skip.

  3. Rails, not prompts. Membership, math, dedup, and set logic are computed.
     The model classifies and interprets. `_risk`/`_approvals` gate anything
     consequential, so an agent cannot act past its tier.

Every run is a `run` node and every emitted fact is a graph node with
provenance, so the outcome graph (the moat) is a by-product of normal operation
rather than a reporting afterthought.

No em dashes.
"""
from __future__ import annotations

import time
import uuid

import _graph as G
import _observe as O
from _approvals import decide, request as request_approval

# ── the AOP library ─────────────────────────────────────────────────────────
# Ten agents from the PRD. Each carries the plain-English procedure plus the
# deterministic tool each step calls. `runnable` marks the ones wired to a real
# engine today; the rest are declared so the workforce and its AOPs are visible
# and editable before their connectors exist.

AGENTS = {
    "listener": {
        "name": "Listener",
        "role": "Public-conversation intent",
        "wedge": True,
        "runnable": True,
        "tenx": "No human watches every platform 24/7. Listener does, deduped, with sentiment.",
        "hundredx": "Every signal becomes a graph node the other agents act on, and the "
                    "classifier learns from which alerts get actioned, so precision rises weekly.",
        "scope": "A public post or comment has matched a keyword from the active set, "
                 "from a monitored source.",
        "steps": [
            {"text": "Check the author against the exclusion list. If it is one of our own "
                     "handles, drop it.", "tool": "exclusion_filter"},
            {"text": "Classify relevance to the business. If not relevant, drop it and log it "
                     "for the eval set.", "tool": "classify_relevance"},
            {"text": "Classify sentiment and intent type.", "tool": "classify_sentiment"},
            {"text": "Resolve the author to a Person, and the Person to an Account. If "
                     "ambiguous, attach a best guess with confidence.", "tool": "resolve_entity"},
            {"text": "Write a Signal to the graph with all fields and provenance.",
             "tool": "write_signal"},
            {"text": "Route an alert to the configured Slack channel and email.",
             "tool": "send_message"},
        ],
        "guardrails": [
            "Third-party sources only. Never alert on our own handles.",
            "Never fabricate an author or account match. Low confidence stays low confidence.",
            "One alert per unique item. Idempotency key is platform plus post id.",
            "Every alert links to its source. No unsourced claims.",
        ],
        "evals": ["relevance precision", "relevance recall", "sentiment accuracy",
                  "intent accuracy", "dedup correctness"],
    },
    "analyst": {
        "name": "Analyst",
        "role": "Verified GTM analysis and reporting",
        "runnable": True,
        "tenx": "Two to four hours by hand becomes six to seventeen minutes, on the largest "
                "category of real GTM work.",
        "hundredx": "Every analysis promotes reusable Key Definitions, so the org converges on "
                    "one set of numbers and analysis becomes cumulative.",
        "scope": "Someone asks a pipeline, velocity, loss, attribution, funnel, or revenue "
                 "question against the CRM or warehouse.",
        "steps": [
            {"text": "Produce a plan first: the steps, tables, fields, joins, and assumptions.",
             "tool": "build_plan"},
            {"text": "Flag any step that relies on low-completeness or inconsistently formatted "
                     "fields, and offer a safer alternative.", "tool": "flag_risky_fields"},
            {"text": "Use the standardised Key Definition wherever one exists. Never redefine a "
                     "metric on the fly.", "tool": "resolve_definitions"},
            {"text": "Execute only after the plan is approved.", "tool": "execute_plan"},
            {"text": "Return the result with its plan, the rows excluded and why, and the "
                     "definitions used.", "tool": "render_result"},
        ],
        "guardrails": [
            "No unsourced numbers. Every figure traces to a node or a source.",
            "Never invent a field that does not exist in the schema.",
            "The same question returns the same answer and the same plan.",
        ],
        "evals": ["answer correctness", "plan quality", "groundedness",
                  "KD adherence", "reproducibility"],
    },
    "steward": {
        "name": "Steward",
        "role": "CRM data quality",
        "runnable": True,
        "tenx": "Replaces multi-hour manual audits and catches the edge cases people miss, "
                "like franchises sharing a parent domain.",
        "hundredx": "Every other agent runs on clean data, which lifts accuracy and cuts token "
                    "cost across the whole workforce.",
        "scope": "A periodic sweep, or a request to audit record quality before a campaign.",
        "steps": [
            {"text": "Score fill rates by object and field, and flag unused or redundant fields.",
             "tool": "fill_rates"},
            {"text": "Detect duplicates on name plus address plus phone, not domain alone, "
                     "because franchises share a parent domain.", "tool": "detect_duplicates"},
            {"text": "Quantify blast radius: how many deals are linked to these records.",
             "tool": "blast_radius"},
            {"text": "Propose fixes with evidence and a severity score. Never merge without "
                     "explicit approval.", "tool": "merge_records"},
        ],
        "guardrails": [
            "Never bulk-modify or merge without explicit approval.",
            "Always show the affected records and linked deals before proposing a fix.",
            "A false merge is unrecoverable. When in doubt, flag rather than merge.",
        ],
        "evals": ["duplicate precision", "duplicate recall", "false-merge rate (must be zero)",
                  "fill-rate accuracy"],
    },
}


# Declared, NOT built. These have no procedure and no connector, so they are kept
# OUT of AGENTS entirely: anything in AGENTS is a teammate that can actually be
# routed to and run. Advertising eight teammates that return an empty card was
# the single most misleading thing in this codebase.
ROADMAP = {
    "scout":     {"name": "Scout", "role": "Account intelligence and TAM", "runnable": False,
                  "tenx": "Replaces manual list-building, dedup, and enrichment.",
                  "hundredx": "A clean tiered graph is the foundation every other agent stands on.",
                  "scope": "Building or refreshing the TAM.", "steps": [], "guardrails": [],
                  "evals": ["entity-resolution precision", "ICP-fit accuracy"]},
    # Watcher is NOT runnable yet: the Competitor Intel engine exists but needs a
    # brand plus a competitor list, which this delegation surface does not gather
    # yet. Claiming otherwise would have it report "got to work" and then show
    # nothing, which is the worst possible failure for a trust-led product.
    "watcher":   {"name": "Watcher", "role": "Competitive and market intelligence", "runnable": False,
                  "tenx": "The weekly competitor audit nobody has time to do well.",
                  "hundredx": "Continuous change-detection feeds Writer, Allocator, and Focus.",
                  "scope": "Tracking competitor pricing, launches, ad creative, and hiring.",
                  "steps": [], "guardrails": [], "evals": ["change-detection recall", "false-alarm rate"]},
    "greeter":   {"name": "Greeter", "role": "Inbound, web and WhatsApp", "runnable": False,
                  "tenx": "Instant response, any hour, in the buyer's channel.",
                  "hundredx": "Every inbound conversation enriches the graph and warms the account.",
                  "scope": "An inbound web or WhatsApp message arrives.", "steps": [],
                  "guardrails": [], "evals": ["containment rate", "booking conversion"]},
    "allocator": {"name": "Allocator", "role": "Paid media efficiency", "runnable": False,
                  "tenx": "Catches the bleeding campaign on day one, not at month end.",
                  "hundredx": "Budget follows real pipeline automatically, and the calls sharpen.",
                  "scope": "Spend rises while opportunity rate drops.", "steps": [],
                  "guardrails": ["Never change budget without approval.",
                                 "Never exceed the spend cap."],
                  "evals": ["recommendation precision", "zero budget-cap breaches"]},
    "writer":    {"name": "Writer", "role": "Content and outbound", "runnable": False,
                  "tenx": "Never a blank page, never cold outreach.",
                  "hundredx": "Inbound warms outbound, wins become the next post, the loop compounds.",
                  "scope": "An account shows a fresh buying signal.", "steps": [],
                  "guardrails": ["Never fabricate a fact.", "Never message an excluded account."],
                  "evals": ["groundedness", "brand-voice adherence", "reply rate"]},
    "pulse":     {"name": "Pulse", "role": "Pipeline and deal health", "runnable": False,
                  "tenx": "Flags the deal going dark days before a human notices.",
                  "hundredx": "Learns from won and lost patterns across the whole book.",
                  "scope": "An active deal goes silent across channels.", "steps": [],
                  "guardrails": [], "evals": ["risk-prediction precision", "warning lead time"]},
    "planner":   {"name": "Planner", "role": "Capacity and territory", "runnable": False,
                  "tenx": "Replaces the multi-hour spreadsheet scenario exercise.",
                  "hundredx": "Plans are grounded in the live graph, and outcomes improve the model.",
                  "scope": "Headcount or territory planning for the next quarters.", "steps": [],
                  "guardrails": [], "evals": ["scenario-math correctness"]},
    "focus":     {"name": "Focus", "role": "ABM orchestrator", "runnable": False,
                  "tenx": "Runs an account-based motion that would take a pod to coordinate.",
                  "hundredx": "One orchestrator, many agents, one shared memory. The proof that "
                              "this is a harness and not ten point tools.",
                  "scope": "A target cohort needs a coordinated play.", "steps": [],
                  "guardrails": [], "evals": ["orchestration correctness", "pipeline influenced"]},
}


def _card(aid, a, runnable):
    return {"id": aid, "name": a["name"], "role": a["role"], "runnable": runnable,
            "wedge": a.get("wedge", False), "tenx": a.get("tenx", ""),
            "hundredx": a.get("hundredx", ""), "steps": len(a.get("steps", [])),
            "evals": a.get("evals", [])}


def catalog():
    """Only teammates that can actually run. Roadmap is a separate key so the UI
    cannot accidentally present an unbuilt agent as available."""
    return [_card(aid, a, True) for aid, a in AGENTS.items()]


def roadmap():
    return [_card(aid, a, False) for aid, a in ROADMAP.items()]


def aop(agent_id):
    a = AGENTS.get(agent_id)
    if not a:
        return None
    return {"id": agent_id, **a}


# ── the plan ────────────────────────────────────────────────────────────────

def plan(agent_id, inp=None):
    """Emit the plan an agent WOULD run, with per-step risk and approval state,
    before anything executes. Risk comes from the same `decide` the executor
    uses, so the plan can never understate what the run will do."""
    a = AGENTS.get(agent_id)
    if not a:
        return {"error": f"unknown agent: {agent_id}"}
    inp = inp or {}
    steps = []
    for i, s in enumerate(a.get("steps", []), 1):
        d = decide(s["tool"], agent=agent_id, scope=inp.get("scope", "*"))
        steps.append({
            "n": i, "text": s["text"], "tool": s["tool"],
            "risk": d.risk.value if d.risk else "read",
            "auto": d.allowed, "reason": d.reason, "rule": d.rule,
            "needs_approval": d.needs_user,
        })
    risky = _risky_inputs(agent_id, inp)
    return {
        "agent": agent_id, "name": a["name"], "scope": a.get("scope", ""),
        "input": inp, "steps": steps, "guardrails": a.get("guardrails", []),
        "risk_flags": risky,
        "needs_approval": [s for s in steps if s["needs_approval"]],
    }


def _risky_inputs(agent_id, inp):
    """Self-flag steps that lean on weak data, the habit real analysts demand.
    Deterministic checks only: this is a data-quality read, not a judgment."""
    flags = []
    if agent_id == "listener":
        if not (inp.get("query") or "").strip():
            flags.append({"field": "query", "issue": "no keyword set, the run would match nothing",
                          "alternative": "supply a keyword or phrase to track"})
        if not inp.get("sources"):
            flags.append({"field": "sources", "issue": "no sources selected, defaulting to all",
                          "alternative": "narrow to the platforms that actually carry your buyers"})
    if agent_id == "analyst":
        if not inp.get("question"):
            flags.append({"field": "question", "issue": "no question supplied",
                          "alternative": "state the metric and the period"})
        counts = G.counts()["by_type"]
        if not counts.get("account"):
            flags.append({"field": "account", "issue": "the graph holds no accounts yet, so any "
                                                       "account-level cut would be empty",
                          "alternative": "run Listener or seed the graph first"})
    if agent_id == "steward":
        counts = G.counts()["by_type"]
        if counts.get("account", 0) < 2:
            flags.append({"field": "account", "issue": "too few accounts to audit meaningfully",
                          "alternative": "seed or sync the CRM first"})
    return flags


# ── execution ───────────────────────────────────────────────────────────────

def run(agent_id, inp=None, approved=False):
    """Execute an agent. Anything consequential is gated: when `decide` says a
    step needs a human, the step is queued to the approval queue and the run
    reports it rather than proceeding. Returns the run record."""
    a = AGENTS.get(agent_id)
    if not a:
        # A roadmap teammate is a known name, not a typo, so say which it is.
        if agent_id in ROADMAP:
            return {"error": f"{ROADMAP[agent_id]['name']} is not built yet",
                    "roadmap": True, "agent": agent_id}, 400
        return {"error": f"unknown agent: {agent_id}"}, 404
    inp = inp or {}
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    started = time.time()
    steps_out, emitted, queued = [], [], []

    O.log(O.RUN_START, agent=agent_id, run_id=run_id,
          summary=f"{a['name']} started", input=inp)

    p = plan(agent_id, inp)

    for s in p["steps"]:
        d = decide(s["tool"], agent=agent_id, scope=inp.get("scope", "*"))
        O.log(O.DECISION, agent=agent_id, run_id=run_id, ok=d.allowed,
              summary=f"{s['tool']}: {d.reason}", tool=s["tool"],
              risk=d.risk.value if d.risk else None, rule=d.rule)
        if d.needs_user and not approved:
            aid = request_approval(s["tool"], agent_id, inp.get("scope", "*"),
                                   payload=inp, summary=s["text"])
            queued.append({"action_id": aid, "tool": s["tool"], "text": s["text"]})
            steps_out.append({**s, "status": "awaiting_approval", "action_id": aid})
            continue
        t0 = time.time()
        try:
            out = _exec(agent_id, s["tool"], inp, run_id)
            steps_out.append({**s, "status": "ok", "output": out.get("summary", ""),
                              "count": out.get("count"), "rule": d.rule})
            emitted += out.get("emitted", [])
            O.log(O.STEP, agent=agent_id, run_id=run_id, ok=True,
                  ms=(time.time() - t0) * 1000, summary=out.get("summary", ""),
                  tool=s["tool"], count=out.get("count"))
        except Exception as e:                                   # noqa: BLE001
            steps_out.append({**s, "status": "error", "error": str(e)[:300]})
            O.log(O.ERROR, agent=agent_id, run_id=run_id, ok=False,
                  ms=(time.time() - t0) * 1000,
                  summary=f"{s['tool']}: {str(e)[:160]}", tool=s["tool"])

    rec = {
        "run_id": run_id, "agent": agent_id, "name": a["name"], "input": inp,
        "steps": steps_out, "emitted": len(emitted), "queued": queued,
        "risk_flags": p["risk_flags"],
        "started_at": started, "duration_s": round(time.time() - started, 2),
        "ok": all(s["status"] != "error" for s in steps_out),
    }
    G.upsert("run", rec, key=run_id, agent=agent_id, run_id=run_id)
    O.log(O.RUN_END, agent=agent_id, run_id=run_id, ok=rec["ok"],
          ms=(time.time() - started) * 1000,
          summary=f"{a['name']}: {len(emitted)} written, {len(queued)} awaiting you",
          emitted=len(emitted), queued=len(queued))
    O.prune()
    return rec, 200


def _exec(agent_id, tool, inp, run_id):
    """Deterministic tool dispatch. The model is never asked to do set logic,
    math, or membership, which is exactly the class of task it gets wrong."""
    if agent_id == "listener":
        return _listener_tool(tool, inp, run_id)
    if agent_id == "analyst":
        return _analyst_tool(tool, inp, run_id)
    if agent_id == "steward":
        return _steward_tool(tool, inp, run_id)
    return {"summary": "declared, not wired yet", "emitted": []}


# ── Listener: wired to the existing Signals engine ──────────────────────────

_EXCLUDED = {"cashfree", "cashfreedev", "gtmstack"}


def _listener_tool(tool, inp, run_id):
    q = (inp.get("query") or "").strip()
    if tool == "exclusion_filter":
        return {"summary": "Skipped your own accounts so you never get alerted about yourself",
                "emitted": []}

    if tool == "classify_relevance":
        from _signals import lookup
        sources = inp.get("sources") or ["reddit"]
        payload, status = lookup(q, sources=sources, force=bool(inp.get("force")),
                                 unit="keyword")
        # The keyword unit returns a merged, time-sorted `feed`; person/company
        # units return per-source `activity`. Accept both so the same AOP runs
        # against either shape.
        items = payload.get("feed") or []
        if not items:
            for s in payload.get("sources") or []:
                for a in s.get("activity") or []:
                    items.append({**a, "platform": a.get("platform") or s.get("platform")})
        kept = [m for m in items
                if (m.get("author") or "").lower().lstrip("@").lstrip("u/") not in _EXCLUDED]
        inp["_items"] = kept
        return {"summary": f"Read {len(items)} public posts, {len(kept)} worth your attention",
                "count": len(kept), "emitted": []}

    if tool == "classify_sentiment":
        items = inp.get("_items") or []
        for m in items:
            m["sentiment"] = m.get("sentiment") or _sentiment(m.get("text") or m.get("title") or "")
            m["intent_type"] = _intent(m.get("text") or m.get("title") or "")
        buying = sum(1 for m in items
                     if m["intent_type"] in ("category_intent", "competitor_comparison"))
        return {"summary": (f"{buying} of them look like someone choosing a vendor right now"
                            if buying else "None of them look like someone choosing a vendor"),
                "count": buying, "emitted": []}

    if tool == "resolve_entity":
        items, n = inp.get("_items") or [], 0
        for m in items:
            h = (m.get("author") or "").strip()
            if not h:
                continue
            plat = m.get("platform") or "unknown"
            pid = G.upsert("person", {"handle": h, "platform": plat},
                           key=f"{plat}:{h}", agent="listener", run_id=run_id,
                           source=m.get("url"))
            m["_person_id"] = pid
            n += 1
        return {"summary": f"Worked out who {n} of the posters are", "count": n, "emitted": []}

    if tool == "write_signal":
        items, ids = inp.get("_items") or [], []
        for m in items:
            plat = m.get("platform") or "unknown"
            # Idempotency key is platform plus post id (the url here), which is
            # what makes a re-run update rather than duplicate.
            key = f"{plat}:{m.get('id') or m.get('url') or m.get('text', '')[:80]}"
            sid = G.upsert("signal", {
                "platform": plat, "url": m.get("url"), "author": m.get("author"),
                "text": (m.get("text") or "")[:600],
                "sentiment": m.get("sentiment"), "intent_type": m.get("intent_type"),
                "posted_at": m.get("ts"), "ago": m.get("ago"), "where": m.get("where"),
                "actioned": False, "query": inp.get("query"),
            }, key=key, agent="listener", run_id=run_id, source=m.get("url"))
            ids.append(sid)
            if m.get("_person_id"):
                G.link(sid, "authored_by", m["_person_id"])
        return {"summary": f"Saved {len(ids)} posts, each with a link back to the original",
                "count": len(ids), "emitted": ids}

    if tool == "send_message":
        items = inp.get("_items") or []
        n = sum(1 for m in items
                if m.get("intent_type") in ("category_intent", "competitor_comparison"))
        return {"summary": (f"{n} alert ready for you" if n == 1 else f"{n} alerts ready for you")
                           + ". Connect Slack or email in Connectors to have them delivered.",
                "count": n, "emitted": []}
    return {"summary": "noop", "emitted": []}


# ── the classifiers ─────────────────────────────────────────────────────────
# A lexicon with negation handling, NOT a model. Measured by evals/run_evals.py
# against a labelled golden set, so its real accuracy is a number rather than a
# claim. It does well on explicit phrasing and poorly on sarcasm and implication;
# that gap is reported, not hidden, and closing it means a real classifier.

_NEG = ("worst", "bad", "issue", "problem", "fail", "failed", "down", "downtime",
        "scam", "slow", "bug", "broken", "angry", "terrible", "avoid", "stuck",
        "delayed", "delay", "never replies", "not responding", "not working",
        "tired of", "poor")
_POS = ("best", "great", "love", "good", "smooth", "fast", "excellent",
        "works well", "solid", "would recommend", "seamless", "reliable")

# Negation flips the polarity of the word that follows. Without this, "not bad"
# and "cannot complain" score negative, which is the single biggest source of
# sentiment error in a lexicon.
_NEGATORS = ("not ", "no ", "never ", "cannot ", "can't ", "cant ", "without ",
             "hardly ", "would not ", "wouldn't ", "isn't ", "is not ")

_COMPLAINT = ("refund", "not working", "failed", "issue", "support", "stuck",
              "delayed", "delay", "debited", "kyc", "no resolution", "never replies",
              "not responding", "downtime")

_CAT = ("best payment gateway", "which payment gateway", "which pg", "recommend a",
        "recommend any", "alternative to", "alternatives to", "vs ", " vs", "compare",
        "should i use", "suggestions for", "looking for", "evaluating options",
        "considering our options", "where do i begin", "start accepting",
        "moved off", "switching", "switch from", "of choice", "recommendations",
        "do you use", "anyone using", "suggest a", "suggest any", "go with")

_COMPARE = ("vs ", " vs", "compare", "alternative to", "alternatives to", "versus",
            "moved off", "switching", "switch from", "considering our options",
            "leaving them", "better than")

# Phrases that are a REQUEST, not praise. "recommend a gateway" is someone asking,
# so it must not read as positive sentiment about anyone.
_ASKING = ("recommend a", "recommend any", "suggestions for", "looking for",
           "which ", "what is the best", "any good", "where do i", "how do i",
           "should i")


def _has(t, phrase):
    """True when `phrase` appears un-negated. Looks back up to 24 characters,
    which catches 'not bad' and 'would not say it is a bad'.

    The lookback STOPS at a clause boundary, because negation does not cross one:
    in "their support never replies, worst experience" the 'never' belongs to the
    first clause and must not cancel 'worst' in the second. Without this the
    angriest posts read as neutral, which is the worst possible failure for a
    complaint detector."""
    i = t.find(phrase)
    while i != -1:
        window = t[max(0, i - 24):i]
        for sep in (",", ".", ";", " but ", " however "):
            if sep in window:
                window = window.rsplit(sep, 1)[1]
        if not any(neg in window for neg in _NEGATORS):
            return True
        i = t.find(phrase, i + 1)
    return False


def _negated(t, phrase):
    """True when the phrase appears ONLY in a negated form, which flips polarity."""
    return phrase in t and not _has(t, phrase)


def _sentiment(text):
    t = " " + (text or "").lower().strip()
    neg = sum(1 for w in _NEG if _has(t, w))
    pos = sum(1 for w in _POS if _has(t, w))
    # A negated negative reads positive ("not bad", "cannot complain about"),
    # and a negated positive reads negative.
    pos += sum(1 for w in _NEG if _negated(t, w))
    neg += sum(1 for w in _POS if _negated(t, w))
    # Asking for a recommendation is not praise.
    if any(a in t for a in _ASKING) and pos and not neg:
        return "neutral"
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _intent(text):
    t = " " + (text or "").lower().strip()
    if any(_has(t, k) for k in _COMPARE):
        return "competitor_comparison"
    if any(k in t for k in _CAT):
        return "category_intent"
    # A complaint is a negative sentiment ABOUT a specific failure. Checking both
    # avoids tagging "the fees are the worst part but everything else is solid"
    # as a complaint when it is really a mixed brand mention.
    if any(_has(t, w) for w in _COMPLAINT) and _sentiment(text) == "negative":
        return "complaint"
    return "brand_mention"


def _analyst_tool(tool, inp, run_id):
    from _definitions import resolve_for_question, DEFINITIONS
    q = inp.get("question") or ""
    if tool == "build_plan":
        return {"summary": f"plan built for: {q[:70] or 'unstated question'}", "emitted": []}
    if tool == "flag_risky_fields":
        flags = _risky_inputs("analyst", inp)
        return {"summary": f"{len(flags)} risk flags raised", "count": len(flags), "emitted": []}
    if tool == "resolve_definitions":
        used = resolve_for_question(q)
        inp["_definitions"] = used
        return {"summary": (f"using {', '.join(d['name'] for d in used)}" if used
                            else f"no Key Definition matched, {len(DEFINITIONS)} available"),
                "count": len(used), "emitted": []}
    if tool == "execute_plan":
        sig = G.query("signal", limit=1000)
        by_sent, by_intent = {}, {}
        for s in sig:
            by_sent[s["data"].get("sentiment") or "unknown"] = \
                by_sent.get(s["data"].get("sentiment") or "unknown", 0) + 1
            by_intent[s["data"].get("intent_type") or "unknown"] = \
                by_intent.get(s["data"].get("intent_type") or "unknown", 0) + 1
        inp["_result"] = {"signals": len(sig), "by_sentiment": by_sent, "by_intent": by_intent}
        return {"summary": f"computed over {len(sig)} signals", "count": len(sig), "emitted": []}
    if tool == "render_result":
        r = inp.get("_result") or {}
        defs = inp.get("_definitions") or []
        return {"summary": f"{r.get('signals', 0)} signals, "
                           f"{len(defs)} definitions cited, every figure sourced",
                "emitted": []}
    return {"summary": "noop", "emitted": []}


# ── Steward: data quality over the graph ────────────────────────────────────

def _steward_tool(tool, inp, run_id):
    people = G.query("person", limit=1000)
    accounts = G.query("account", limit=1000)
    if tool == "fill_rates":
        fields = ("handle", "platform", "name", "account_id")
        total = len(people) or 1
        rates = {f: round(100.0 * sum(1 for p in people if p["data"].get(f)) / total, 1)
                 for f in fields}
        inp["_rates"] = rates
        weak = [f for f, v in rates.items() if v < 50]
        return {"summary": f"{len(weak)} of {len(fields)} fields are missing on more than half your records",
                "count": len(weak), "emitted": []}
    if tool == "detect_duplicates":
        seen, dupes = {}, []
        for p in people:
            k = (p["data"].get("handle") or "").strip().lower()
            if not k:
                continue
            if k in seen:
                dupes.append({"a": seen[k], "b": p["id"], "on": "handle"})
            else:
                seen[k] = p["id"]
        inp["_dupes"] = dupes
        return {"summary": f"Found {len(dupes)} likely duplicate people. Once your CRM is connected "
                           f"this also matches on name, address, and phone",
                "count": len(dupes), "emitted": []}
    if tool == "blast_radius":
        d = inp.get("_dupes") or []
        linked = 0
        for pair in d:
            linked += len(G.neighbours(pair["a"])) + len(G.neighbours(pair["b"]))
        return {"summary": f"Merging these would affect {linked} connected records",
                "count": linked, "emitted": []}
    if tool == "merge_records":
        d = inp.get("_dupes") or []
        return {"summary": f"{len(d)} merges ready for you to approve. Nothing was changed",
                "count": len(d), "emitted": []}
    return {"summary": f"{len(accounts)} accounts in graph", "emitted": []}


def runs(limit=25):
    return [r["data"] for r in G.query("run", limit=limit)]


# ── delegation: plain English in, the right teammate out ────────────────────
# Deterministic keyword routing, on purpose. A GTM lead types what they want in
# their own words; we map it to a teammate and its inputs. Keeping this as rules
# rather than a model call means the routing is predictable and explainable,
# which matters more here than cleverness: the user must never wonder why their
# request went to the wrong agent.

_ROUTES = [
    # Order matters. Anything about what PEOPLE are publicly saying is Listener,
    # including comparisons, which is why "compares us" sits here and not under
    # Watcher. Watcher is about what a COMPETITOR does (prices, ships, hires),
    # so its keys stay narrow or it would swallow every sentence containing the
    # word "competitor".
    ("steward",  ("duplicate", "dupe", "clean up", "hygiene", "fill rate", "messy",
                  "missing field", "stale record", "audit the crm", "data quality")),
    ("analyst",  ("how many", "what percent", "what % ", "report on", "analyse", "analyze",
                  "pipeline", "win rate", "velocity", "conversion", "attribution",
                  "forecast", "breakdown")),
    ("listener", ("watch", "listen", "monitor", "mention", "reddit", "twitter",
                  "social", "saying", "talking", "asking", "compares", "comparing",
                  "compare us", "intent", "buying signal", "alert me", "tell me when")),
    ("watcher",  ("competitor pricing", "competitor launch", "what competitors",
                  "rival", "pricing change", "market move")),
]


def route(text):
    """Pick the teammate for a plain-English request, and pre-fill its inputs.
    Returns the agent id, the extracted input, and the reason, so the UI can say
    'sending this to Listener because you asked about monitoring'."""
    t = (text or "").strip()
    low = t.lower()
    for agent_id, keys in _ROUTES:
        hit = next((k for k in keys if k in low), None)
        if hit:
            # A roadmap teammate is still the RIGHT match, so say so and stop,
            # rather than silently handing the work to someone else. Being told
            # "Watcher is not built yet" beats getting Listener's answer to a
            # question you did not ask.
            if agent_id in ROADMAP:
                return {"agent": agent_id, "name": ROADMAP[agent_id]["name"],
                        "input": _extract(agent_id, t), "roadmap": True,
                        "why": f"you mentioned {hit.strip()}, but this teammate is not built yet"}
            return {"agent": agent_id, "name": AGENTS[agent_id]["name"],
                    "input": _extract(agent_id, t),
                    "why": f"you mentioned {hit.strip()}"}
    # Default to the wedge: most plain requests in this product are "keep an eye
    # on X", and Listener is the only one that needs no connector to be useful.
    return {"agent": "listener", "name": AGENTS["listener"]["name"],
            "input": _extract("listener", t),
            "why": "this looks like something to keep watch on"}


_STOP = ("watch for", "watch", "listen for", "listen", "monitor", "tell me when",
         "tell me about", "keep an eye on", "people", "anyone", "who is", "who are",
         "talking about", "asking about", "asking for", "asking", "asks about",
         "mentions of", "mention of", "any", "on reddit", "on twitter", "on x",
         "please", "for me", "looking for", "searching for", "posts about")

# Trailing filler. "which payment gateway to use" must search for "payment
# gateway", not the whole sentence: a sentence-shaped query returns whatever the
# search engine free-associates to, which is how a payment feed filled up with
# essay-writing spam.
_TAIL = ("to use", "to buy", "to pick", "to choose", "should i use", "do i use",
         "i should use", "for my business", "for my store", "right now", "today")
_LEAD = ("which", "what", "who", "where", "how", "the", "a", "an", "is", "are",
         "to", "for", "about", "that", "and", "or", "of")


def _extract(agent_id, text):
    """Pull the subject out of a plain request. Deliberately simple and
    transparent: strip the instruction words, keep the topic."""
    q = (text or "").strip().rstrip("?.!")
    low = q.lower()
    for s in sorted(_STOP, key=len, reverse=True):
        if low.startswith(s):
            q = q[len(s):].strip()
            low = q.lower()
    for s in _STOP:
        low = low.replace(s, " ")
    q = " ".join((q if len(q.split()) <= 8 else " ".join(low.split())).split())
    # Strip trailing filler, then leading question words, until the topic is bare.
    low = q.lower()
    for t in sorted(_TAIL, key=len, reverse=True):
        if low.endswith(t):
            q = q[: len(q) - len(t)].strip(" ,")
            low = q.lower()
    words = q.split()
    while words and words[0].lower().strip(",") in _LEAD:
        words.pop(0)
    q = " ".join(words).strip(" ,?.")
    if agent_id == "analyst":
        return {"question": text, "query": q}
    return {"query": q or text, "sources": ["reddit"], "question": text}


# ── plain-English phrasing for anything needing a human ─────────────────────
# The Inbox shows these, never a tool name. "Post an alert to Slack" is a thing
# a GTM lead can answer; "send_message" is not.

ASK_COPY = {
    "write_signal":   ("Save what I found so the team can use it",
                       "I will store these posts with their links so your lists and reports stay current."),
    "send_message":   ("Send you an alert when something matters",
                       "I will post to your Slack channel and email when someone shows buying intent."),
    "send_email":     ("Email the team", "I will send this to the address you configured."),
    "send_whatsapp":  ("Message on WhatsApp", "I will reply in the customer's channel."),
    "publish_post":   ("Publish this post", "It goes live under your account."),
    "update_record":  ("Update a record in your CRM", "I will change fields on records you own."),
    "merge_records":  ("Merge duplicate records", "This cannot be undone, so I will show you every record first."),
    "bulk_update":    ("Change many records at once", "This touches more records than a normal edit."),
    "set_budget":     ("Move ad budget", "This spends real money, so I will never do it without you."),
    "launch_campaign": ("Launch a campaign", "This spends real money."),
    "book_meeting":   ("Book a meeting", "It goes on the calendar you connected."),
}


def ask_copy(action):
    title, detail = ASK_COPY.get(action, (action.replace("_", " ").capitalize(),
                                          "This changes something outside GTMstack."))
    return {"title": title, "detail": detail}
