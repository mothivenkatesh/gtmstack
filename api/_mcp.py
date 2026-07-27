"""
MCP server - GTMstack's tools, callable by any AI agent.

This is the surface the roadmap has been pointing at since Signals shipped
("Channels: GTMstack shell now; an MCP server + API later"). Every tool in this
app was already built to be agent-callable rather than only clickable; MCP is
the standard wrapper that makes that real for Claude, Cursor, and anything else
that speaks the protocol.

Five tools are exposed, each a thin adapter over the SAME engine the UI calls,
so there is one implementation and the two surfaces cannot drift:

    gtm_persona          _personas.preview      how developers react to your copy
    gtm_youtube_transcript _core.fetch_transcript  clean text from any video
    gtm_signals          _signals.lookup        who someone is, what they just did
    gtm_nobounce         _clean.clean           validate + de-dupe an email list
    gtm_competitor_intel _plays competitor_intel share of voice vs competitors

Transport: JSON-RPC 2.0 over HTTP POST, which is the streamable-HTTP transport
MCP clients use. Stdio is a thin shim on top (see mcp_server.py) so the same
handlers serve both without a second implementation.

Design notes worth keeping:
  - Tool names are prefixed `gtm_` so they do not collide in a client that has
    many servers mounted.
  - Schemas are hand-written rather than generated. An agent picks a tool from
    its description, so the description is a product surface, not a comment.
  - Every tool degrades the way the UI does (a dead source is a status, not an
    exception), because an agent handles a partial result far better than it
    handles a 500.

No em dashes.
"""
from __future__ import annotations

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "gtmstack", "version": "1.0.0"}

# ── tool catalog ────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "gtm_signals",
        "title": "Signals",
        "description": (
            "Find out who a person or company is and what they did most recently across "
            "GitHub, Reddit, LinkedIn, X, and YouTube, in real time. Also tracks a keyword "
            "and returns a live, newest-first feed of public mentions. Use this to research "
            "a prospect before outreach, map a company's people, or catch buying-intent "
            "posts (for example someone publicly asking which vendor to pick). Reads are "
            "live, not a stale nightly dump. A source with no credentials returns a "
            "needs_connection status instead of failing the whole call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "A name, handle, email, company name or domain, "
                                         "or the phrase to track."},
                "unit": {"type": "string", "enum": ["person", "company", "keyword"],
                         "default": "person",
                         "description": "person = one individual's footprint; company = the "
                                        "company plus the people in it; keyword = a live "
                                        "mentions feed."},
                "sources": {"type": "array", "items": {"type": "string"},
                            "description": "Optional subset: github, reddit, linkedin, x, youtube. "
                                           "Defaults to all available."},
                "force": {"type": "boolean", "default": False,
                          "description": "Skip the 30-minute cache and pull fresh."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gtm_persona",
        "title": "Synthetic Persona",
        "description": (
            "Test marketing or product copy against synthetic developer personas before you "
            "ship it. Returns an overall score, a verdict, and per-persona reactions with "
            "what each one liked and objected to. Use this to sanity-check a landing page, "
            "an email, or an ad against a technical audience without running a real study."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The copy to test."},
                "type": {"type": "string", "enum": ["landing", "email", "ad", "docs"],
                         "default": "landing", "description": "What kind of copy this is."},
                "personas": {"type": "array", "items": {"type": "string"},
                             "description": "Optional subset of persona ids. Defaults to all."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "gtm_youtube_transcript",
        "title": "YouTube Transcript",
        "description": (
            "Pull the clean full text out of any YouTube video, with timing segments. No API "
            "key needed. Use this to summarise a talk, mine a competitor's webinar or launch "
            "video for messaging, or feed a transcript into other analysis."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or bare video id."},
                "lang": {"type": "string", "description": "Preferred caption language, e.g. en."},
                "translate": {"type": "string", "description": "Translate captions to this language code."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "gtm_nobounce",
        "title": "NoBounce",
        "description": (
            "Validate and de-duplicate a list of email addresses so you never burn your "
            "sending domain. Accepts raw pasted text or CSV (addresses are pulled out of any "
            "column) and returns one row per address with valid (boolean), verdict "
            "(deliverable, risky, or undeliverable), plus disposable, role-based, free-provider "
            "and typo flags. No mail is ever sent. Branch on `valid` to get everything safe to "
            "send to, or on `verdict` for the strict three-way split."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "Raw list or CSV. One address per line, or any CSV column."},
                "emails": {"type": "array", "items": {"type": "string"},
                           "description": "Alternative to text: an explicit array of addresses."},
            },
        },
    },
    {
        "name": "gtm_competitor_intel",
        "title": "Competitor Intel",
        "description": (
            "Compare your brand against named competitors on the public channels that matter "
            "for B2B and developer products. Returns share of voice (reach percent, post "
            "count, engagement impact), a market-positioning quadrant, a channel breakdown, "
            "top voices, and the influencers who talk about more than one brand. Built from "
            "public posts only. Use this for a competitive snapshot before a launch or a "
            "board update."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "brand": {"type": "string", "description": "Your brand name."},
                "competitors": {"type": "string",
                                "description": "Comma-separated competitor names."},
            },
            "required": ["brand"],
        },
    },
]


# ── dispatch ────────────────────────────────────────────────────────────────

def call_tool(name, args):
    """Run one tool. Returns (payload_dict, is_error). Engine imports are lazy so
    a cold start only pays for the tool actually invoked, matching the registry's
    posture."""
    args = args or {}
    try:
        if name == "gtm_signals":
            from _signals import lookup
            payload, status = lookup(
                args.get("query", ""), args.get("sources") or None, None,
                bool(args.get("force")), args.get("unit") or "person")
            return payload, status >= 400

        if name == "gtm_persona":
            from _personas import preview
            payload, status = preview(
                args.get("text", ""), args.get("type", "landing"),
                args.get("personas") or None)
            return payload, status >= 400

        if name == "gtm_youtube_transcript":
            from _core import fetch_transcript, build_api
            payload, status = fetch_transcript(
                args.get("url", ""), args.get("lang"), args.get("translate"),
                api=build_api())
            return payload, status >= 400

        if name == "gtm_nobounce":
            from _clean import clean
            payload, status = clean(
                args.get("text") or "", args.get("emails") or None, False)
            return payload, status >= 400

        if name == "gtm_competitor_intel":
            from _plays import run_play
            payload, status = run_play("competitor_intel", {
                "brand": args.get("brand", ""),
                "competitors": args.get("competitors", ""),
            })
            return payload, status >= 400

        return {"error": f"unknown tool: {name}"}, True
    except Exception as e:                                        # noqa: BLE001
        # An agent recovers from a described failure far better than from a
        # transport-level crash, so errors come back as content, not as a 500.
        return {"error": f"{type(e).__name__}: {e}"[:400]}, True


# ── JSON-RPC ────────────────────────────────────────────────────────────────

def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg):
    """Handle one JSON-RPC message. Returns a response dict, or None for a
    notification (which by spec gets no reply)."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request")
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "GTMstack exposes five GTM research tools. Use gtm_signals to research a "
                "person, company, or track a keyword for buying intent; gtm_persona to test "
                "copy against developer personas; gtm_youtube_transcript to read any video; "
                "gtm_nobounce to clean an email list before sending; gtm_competitor_intel for "
                "share of voice against named competitors."
            ),
        })

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _result(rid, {})

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        payload, is_error = call_tool(name, params.get("arguments"))
        import json
        return _result(rid, {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)[:120000]}],
            "structuredContent": payload if isinstance(payload, dict) else {"result": payload},
            "isError": bool(is_error),
        })

    return _error(rid, -32601, f"method not found: {method}")
