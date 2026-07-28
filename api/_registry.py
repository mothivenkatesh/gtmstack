"""
GTMstack module registry - the backend mirror of the frontend's manifest system.

Every feature is a Module class exposing one uniform interface:

    class Module:
        id / name / desc                      # metadata (the manifest)
        get(req: Req)  -> Resp                # read side
        post(req: Req) -> Resp                # write side

Both servers dispatch through REGISTRY - the Flask dev server (app.py) via a
generic /api/<id> route, and each Vercel function (api/<id>.py) via the shared
make_handler() shim in _http.py - so request parsing, cron gating, downloads,
and cookies live HERE, once, instead of twice per endpoint.

Engine imports are lazy (inside methods): Python caches them after the first
call, and a Vercel function's cold start only pays for the engines it uses.

No em dashes.
"""
from __future__ import annotations

import os


class Req:
    """Uniform request: everything a module may need, server-agnostic."""

    def __init__(self, method="GET", params=None, body=None, headers=None,
                 cookies=None, host_url="/", is_secure=False):
        self.method = method
        self.params = params or {}        # query string, single values
        self.body = body or {}            # parsed JSON body ({} when absent)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.cookies = cookies or {}
        self.host_url = host_url          # e.g. "http://localhost:5000/"
        self.is_secure = is_secure


class Resp:
    """Uniform response. payload is a dict for JSON, or str/bytes for files;
    redirects and cookies ride in headers (Location / Set-Cookie)."""

    def __init__(self, payload, status=200, ctype="application/json", headers=None):
        self.payload = payload
        self.status = status
        self.ctype = ctype
        self.headers = headers or {}


def _download(text, ctype, fname):
    return Resp(text, 200, ctype + "; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{fname}"'})


class Module:
    """Base class: metadata + default 405s + the shared cron gate."""

    id = ""
    name = ""
    desc = ""

    def meta(self):
        return {"id": self.id, "name": self.name, "desc": self.desc}

    def get(self, req: Req) -> Resp:
        return Resp({"error": "method not allowed"}, 405)

    def post(self, req: Req) -> Resp:
        return Resp({"error": "method not allowed"}, 405)

    def _cron_ok(self, req: Req) -> bool:
        """POST gate: when CRON_SECRET is set, the X-Cron-Secret header must match."""
        secret = os.getenv("CRON_SECRET")
        return not secret or req.headers.get("x-cron-secret") == secret

    def _harness_ok(self, req: Req):
        """Gate for the harness endpoints, which are a different class from the
        read-only lookup tools: they run agents and mutate the context graph, so
        an open one lets a stranger write to your graph and burn your source
        quota.

        Secure by default in production, zero friction locally:
          - HARNESS_SECRET set  -> the X-Harness-Secret header must match.
          - unset, on Vercel    -> DENIED. Fail closed, because a public deploy
                                   with no secret is the case we are guarding.
          - unset, local        -> allowed, so `python app.py` needs no config.

        Returns None when allowed, or a Resp to return as-is.
        """
        secret = os.getenv("HARNESS_SECRET")
        if secret:
            if req.headers.get("x-harness-secret") == secret:
                return None
            return Resp({"error": "unauthorized",
                         "detail": "this endpoint needs the X-Harness-Secret header"}, 401)
        if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
            return Resp({"error": "unauthorized",
                         "detail": "HARNESS_SECRET is not set on this deployment, so the "
                                   "harness endpoints are disabled"}, 401)
        return None


# ── feature modules ──────────────────────────────────────────────────────────

class TranscriptModule(Module):
    id, name, desc = "transcript", "YouTube Transcript", "Pull clean text from any YouTube video"
    _api = None                                  # built once, reused across requests

    def get(self, req):
        from _core import fetch_transcript, build_api
        if TranscriptModule._api is None:
            TranscriptModule._api = build_api()
        payload, status = fetch_transcript(
            req.params.get("url", ""), req.params.get("lang"),
            req.params.get("translate"), api=TranscriptModule._api)
        return Resp(payload, status)


class PersonaModule(Module):
    id, name, desc = "persona", "Synthetic Persona", "See how developers react to your copy"

    def get(self, req):
        from _personas import persona_roster
        return Resp({"personas": persona_roster()})

    def post(self, req):
        from _personas import preview
        payload, status = preview(
            req.body.get("text", ""), req.body.get("type", "landing"),
            req.body.get("personas") or None)
        return Resp(payload, status)


class SignalsModule(Module):
    id, name, desc = "signals", "Signals", "The data intelligence layer for AI agents"

    def get(self, req):
        from _signals import sources_status
        return Resp({"sources": sources_status()})

    def post(self, req):
        from _signals import lookup
        payload, status = lookup(
            req.body.get("query", ""), req.body.get("sources") or None,
            req.body.get("handles") or None, bool(req.body.get("force")),
            req.body.get("unit") or "person")
        return Resp(payload, status)


class ReportModule(Module):
    id, name, desc = "report", "Daily signal briefs", "Carlsen-ordered keyword-group briefs"

    def get(self, req):
        from _groups import list_groups
        from _report import reports_index, latest_report, get_report
        if req.params.get("groups"):
            return Resp({"groups": list_groups()})
        if req.params.get("id"):
            return Resp(get_report(req.params["id"]) or {"error": "not found"})
        gid = req.params.get("group")
        if gid and req.params.get("list"):
            return Resp({"reports": reports_index(gid)})
        if gid:
            return Resp(latest_report(gid) or {"error": "no report yet", "group_id": gid})
        return Resp({"groups": list_groups(), "reports": reports_index()})

    def post(self, req):
        if not self._cron_ok(req):
            return Resp({"error": "unauthorized"}, 401)
        from _report import run_report
        payload, status = run_report(
            req.body.get("group", ""), req.body.get("sources") or None,
            float(req.body.get("budget_s") or 45), req.body.get("use_llm"))
        return Resp(payload, status)


class MonitorModule(Module):
    id, name, desc = "monitor", "Competitive monitor", "Reddit/Quora/reviews/X mention scan"

    def get(self, req):
        from _monitor import overview, staleness_hours
        from _mentions import recent
        if req.params.get("staleness"):
            return Resp({"hours": staleness_hours()})
        gid = req.params.get("group")
        if gid:
            return Resp({"group_id": gid, "mentions": recent(gid, 200)})
        return Resp(overview())

    def post(self, req):
        if not self._cron_ok(req):
            return Resp({"error": "unauthorized"}, 401)
        from _monitor import run_monitor
        return Resp(run_monitor(only=req.body.get("only"),
                                catchup=bool(req.body.get("catchup"))))


class GroupsModule(Module):
    id, name, desc = "groups", "Keyword groups", "The groups the briefs + monitor scan"

    def get(self, req):
        from _groups import list_groups
        return Resp({"groups": list_groups()})

    def post(self, req):
        if not self._cron_ok(req):
            return Resp({"error": "unauthorized"}, 401)
        from _groups import save_group, delete_group
        if req.body.get("delete"):
            return Resp({"ok": delete_group(req.body.get("id", ""))})
        saved = save_group(req.body)
        return Resp({"group": saved}) if saved else Resp({"error": "bad group"}, 400)


class JobsModule(Module):
    id, name, desc = "jobs", "Async jobs", "Bulk lookups, webhooks, CSV/JSON export"

    def get(self, req):
        from _jobs import get as jobs_get, recent, export
        job_id = req.params.get("id")
        if not job_id:
            return Resp({"jobs": recent()})
        fmt = req.params.get("format")
        if fmt:
            body, ctype, fname = export(job_id, fmt)
            if body is None:
                return Resp({"error": "Job not finished or not found."}, 404)
            return _download(body, ctype, fname)
        job = jobs_get(job_id)
        return Resp(job) if job else Resp({"error": "Job not found."}, 404)

    def post(self, req):
        from _jobs import submit
        job = submit(req.body)
        done = bool(job and job.get("status") in ("done", "error"))
        return Resp(job, 200 if done else 202)


class CleanModule(Module):
    id, name, desc = "clean", "NoBounce", "Validate and de-dupe an email list for agents"

    def post(self, req):
        from _clean import clean, to_csv, to_json
        payload, status = clean(
            req.body.get("text", ""), req.body.get("emails") or None,
            bool(req.body.get("check_smtp")))
        fmt = (req.params.get("format") or req.body.get("format") or "").lower()
        if status == 200 and fmt in ("csv", "json"):
            only = (req.params.get("only") or req.body.get("only")) == "clean"
            text = to_csv(payload, only) if fmt == "csv" else to_json(payload, only)
            return _download(text, "text/csv" if fmt == "csv" else "application/json",
                             f"clean-emails.{fmt}")
        return Resp(payload, status)


class PlaysModule(Module):
    id, name, desc = "plays", "Plays", "Composite multi-step runs an agent can call"

    def get(self, req):
        from _plays import list_plays
        return Resp({"plays": list_plays()})

    def post(self, req):
        from _plays import run_play
        payload, status = run_play(req.body.get("play", ""), req.body.get("input") or {})
        return Resp(payload, status)


class AuthModule(Module):
    id, name, desc = "auth", "Accounts", "Passwordless magic-link sign-in + run history"

    def _cookie(self, req, value, max_age):
        import _accounts
        secure = "Secure; " if req.is_secure else ""
        return (f"{_accounts.COOKIE}={value}; Path=/; HttpOnly; {secure}"
                f"SameSite=Lax; Max-Age={max_age}")

    def _session(self, req):
        import _accounts
        return req.cookies.get(_accounts.COOKIE)

    def get(self, req):
        import _accounts
        action = req.params.get("action", "")
        if action == "verify":
            sess, ok, first = _accounts.consume_link(req.params.get("token", ""))
            if ok:
                return Resp(None, 302, headers={
                    "Location": "/?welcome=1" if first else "/",
                    "Set-Cookie": self._cookie(req, sess, _accounts.SESSION_MAX_AGE)})
            return Resp(None, 302, headers={"Location": "/?auth=expired"})
        if action == "me":
            return Resp(_accounts.whoami(self._session(req)))
        if action == "runs":
            return Resp(_accounts.list_runs(self._session(req)))
        return Resp({"error": "unknown action"}, 400)

    def post(self, req):
        import _accounts
        action = req.body.get("action")
        if action == "request":
            payload, status = _accounts.request_link(req.body.get("email", ""), req.host_url)
            return Resp(payload, status)
        if action == "logout":
            return Resp({"ok": True}, headers={"Set-Cookie": self._cookie(req, "", 0)})
        if action == "run":
            return Resp(_accounts.record_run(
                self._session(req), req.body.get("tool", ""), req.body.get("summary", "")))
        return Resp({"error": "unknown action"}, 400)


class WatchdogModule(Module):
    id, name, desc = "watchdog", "Staleness watchdog", "Alerts when the monitor goes stale"

    def get(self, req):
        from _monitor import staleness_hours, latest_run
        try:
            import _email
        except Exception:
            _email = None
        threshold = float(os.getenv("MONITOR_STALE_HOURS", "26"))
        hours = staleness_hours()
        stale = hours is None or hours > threshold
        alerted = False
        recipient = os.getenv("MONITOR_ALERT_EMAIL")
        if stale and recipient and _email:
            lr = latest_run() or {}
            when = "never" if hours is None else f"{hours}h ago"
            body = (f"The GTMstack competitive monitor has not run recently.\n"
                    f"Last successful run: {when}\n"
                    f"Last finished_at: {lr.get('finished_at', 'unknown')}\n"
                    f"Threshold: {threshold}h\n\n"
                    f"Check that the Mac running the launchd job is awake and logged in.")
            try:
                _email.send(recipient, "[GTMstack] monitor is stale", body)
                alerted = True
            except Exception:
                pass
        return Resp({"stale": stale, "hours": hours,
                     "threshold_hours": threshold, "alerted": alerted})


# ── harness modules (the GTM harness: graph, agents, cohorts, approvals) ─────
# Five thin Module classes over the harness engines. Same contract as every
# other feature: metadata, get, post. The engines hold the logic.

class GraphModule(Module):
    id, name, desc = "graph", "Context Graph", "The revenue ontology every agent reads and writes"

    def get(self, req):
        import _graph as G
        if req.params.get("id"):
            node = G.get(req.params["id"])
            if not node:
                return Resp({"error": "not found"}, 404)
            return Resp({"node": node, "neighbours": G.neighbours(node["id"])})
        t = req.params.get("type")
        if t:
            return Resp({"type": t, "nodes": G.query(t, limit=int(req.params.get("limit", 100)))})
        return Resp({"counts": G.counts()})

    def post(self, req):
        import _graph as G
        from _cohorts import seed as seed_cohorts
        from _definitions import seed as seed_defs
        if req.body.get("action") == "reset":
            G.reset()
            seed_defs(); seed_cohorts()
            return Resp({"ok": True, "reset": True, "counts": G.counts()})
        if req.body.get("action") == "seed":
            seed_defs(); seed_cohorts()
            return Resp({"ok": True, "counts": G.counts()})
        return Resp({"error": "unknown action"}, 400)


class AgentsModule(Module):
    id, name, desc = "agents", "Agents", "The agent workforce, their AOPs, plans, and runs"

    def get(self, req):
        from _agents import catalog, aop, runs, roadmap
        if req.params.get("id"):
            a = aop(req.params["id"])
            return Resp(a) if a else Resp({"error": "unknown agent"}, 404)
        if req.params.get("runs"):
            return Resp({"runs": runs(limit=int(req.params.get("limit", 25)))})
        return Resp({"agents": catalog(), "roadmap": roadmap()})

    def post(self, req):
        from _agents import plan, run, route
        # Plain-English delegation: the GTM lead types what they want, we pick
        # the teammate. This is the front door, so it comes first.
        if req.body.get("ask"):
            r = route(req.body["ask"])
            if req.body.get("mode") == "route":
                return Resp(r)
            rec, status = run(r["agent"], r["input"],
                              approved=bool(req.body.get("approved")))
            return Resp({**rec, "routed": r}, status)
        agent = req.body.get("agent")
        if not agent:
            return Resp({"error": "agent required"}, 400)
        inp = req.body.get("input") or {}
        if req.body.get("mode") == "plan":
            return Resp(plan(agent, inp))
        rec, status = run(agent, inp, approved=bool(req.body.get("approved")))
        return Resp(rec, status)


class McpModule(Module):
    """MCP endpoint: the five GTMstack tools, callable by any AI agent.

    GET returns the catalog as plain JSON (handy for humans and for a quick
    curl); POST speaks JSON-RPC 2.0, which is what MCP clients actually use.
    The handlers live in _mcp.py and call the same engines as the UI.
    """
    id, name, desc = "mcp", "MCP", "GTMstack tools, callable by any AI agent"

    def get(self, req):
        from _mcp import TOOLS, SERVER_INFO, PROTOCOL_VERSION
        return Resp({"server": SERVER_INFO, "protocolVersion": PROTOCOL_VERSION,
                     "transport": "streamable-http (POST JSON-RPC 2.0 to this URL)",
                     "tools": [{"name": t["name"], "title": t["title"],
                                "description": t["description"]} for t in TOOLS]})

    def post(self, req):
        from _mcp import handle
        body = req.body
        if isinstance(body, list):                       # JSON-RPC batch
            out = [r for r in (handle(m) for m in body) if r is not None]
            return Resp(out if out else {}, 200 if out else 202)
        resp = handle(body)
        if resp is None:                                 # notification, no reply
            return Resp({}, 202)
        return Resp(resp)


class InboxModule(Module):
    """The human-attention queue: the one place a GTM lead answers their team.

    Ported in spirit from OpenWorker's Inbox (coworker/inbox.py): approvals,
    questions, and notifications in one queue, resolved once, answerable from
    any surface. This is what makes the product feel like a coworker rather than
    a control panel, which is exactly what the first cut of this UI got wrong.
    """
    id, name, desc = "inbox", "Inbox", "What your team needs from you"

    def get(self, req):
        from _approvals import pending, policies, stats
        from _agents import ask_copy, AGENTS
        from _risk import RiskClass, tier_meta
        items = []
        for p in pending():
            d = p["data"]
            copy = ask_copy(d.get("action", ""))
            agent = AGENTS.get(d.get("agent"), {})
            items.append({
                "id": p["id"], "kind": "approval",
                "title": copy["title"], "detail": copy["detail"],
                "agent": agent.get("name", d.get("agent")),
                "spends_money": d.get("risk") == "spend",
                "context": d.get("summary", ""),
                "requested_at": d.get("requested_at"),
            })
        s = stats()
        # Standing grants ride along: "what have I permanently allowed, and how
        # do I take it back" is part of the same question as "what needs me now".
        # Phrased as outcomes, since this is the coworker surface, not a console.
        standing = []
        for p in policies():
            d = p["data"]
            copy = ask_copy(d.get("action", ""))
            standing.append({"id": p["id"], "title": copy["title"],
                             "agent": AGENTS.get(d.get("agent"), {}).get(
                                 "name", d.get("agent") or "any teammate"),
                             "granted_at": d.get("granted_at")})
        return Resp({"items": items, "count": len(items),
                     "settled": s.get("standing_policies", 0),
                     "standing": standing, "stats": s,
                     "tiers": [{"risk": r.value, **tier_meta(r)} for r in RiskClass]})

    def post(self, req):
        from _approvals import resolve, revoke
        if req.body.get("action") == "revoke":
            revoke(req.body.get("id"))
            return Resp({"ok": True, "revoked": req.body.get("id")})
        return Resp(resolve(req.body.get("id"), req.body.get("outcome", "once"),
                            req.body.get("scope")))


class CohortsModule(Module):
    id, name, desc = "cohorts", "Cohorts", "Smart segments, the unit of GTM action"

    def get(self, req):
        from _cohorts import all as all_cohorts, members, suggest
        if req.params.get("key"):
            return Resp(members(req.params["key"],
                                limit=int(req.params.get("limit", 100))))
        if req.params.get("suggest"):
            return Resp({"suggestions": suggest()})
        return Resp({"cohorts": all_cohorts()})

    def post(self, req):
        from _cohorts import create
        return Resp(create(req.body.get("name"), req.body.get("plain"),
                           req.body.get("node", "signal"), req.body.get("predicate"),
                           req.body.get("kind", "dynamic"), req.body.get("play")))


class DefinitionsModule(Module):
    id, name, desc = "definitions", "Key Definitions", "One authoritative definition per metric"

    def get(self, req):
        from _definitions import all as all_defs
        return Resp({"definitions": all_defs()})

    def post(self, req):
        from _definitions import promote
        return Resp(promote(req.body.get("name"), req.body.get("formula"),
                            req.body.get("inputs"), req.body.get("owner", "RevOps"),
                            req.body.get("source_run")))


class WatchModule(Module):
    """Standing watches plus the value surface. This is the endpoint a scheduler
    hits, so POST is cron-gated the same way the other unattended jobs are."""
    id, name, desc = "watch", "Watches", "Keywords checked on a schedule, delivered once"

    def get(self, req):
        import _watch, _deliver
        if req.params.get("value"):
            return Resp(_deliver.value())
        return Resp({"watches": _watch.list_watches(), "status": _watch.status(),
                     "delivery": _deliver.configured(), "value": _deliver.value()})

    def post(self, req):
        import _watch, _deliver
        act = req.body.get("action")
        if act == "add":
            return Resp(_watch.add(req.body.get("query"), req.body.get("sources"),
                                   int(req.body.get("interval_s") or _watch.DEFAULT_INTERVAL_S),
                                   req.body.get("label")))
        if act == "remove":
            return Resp(_watch.remove(req.body.get("id")))
        if act == "mark":
            return Resp(_deliver.mark(req.body.get("signal"), req.body.get("outcome"),
                                      req.body.get("note")))
        if act in ("run", "run_due"):
            # The scheduled path. Gated so a public deployment cannot be used to
            # burn source quota by anyone who finds the URL.
            if not self._cron_ok(req):
                return Resp({"error": "unauthorized"}, 401)
            return Resp(_watch.run_due() if act == "run_due" else _watch.run_all())
        return Resp({"error": "unknown action"}, 400)


class CrmModule(Module):
    """CRM sync. Read-only: pulling is safe and immediately useful, while
    writing back is a SPEND-tier action against someone's system of record and
    needs the approval ladder before it goes anywhere near production."""
    id, name, desc = "crm", "CRM", "Sync HubSpot contacts, companies, and deals into the graph"

    def get(self, req):
        import _crm
        return Resp(_crm.status())

    def post(self, req):
        import _crm
        objs = req.body.get("objects") or ["contacts", "companies", "deals"]
        out = _crm.sync(tuple(objs))
        return Resp(out, 200 if out.get("ok") else 400)


class DocsModule(Module):
    """Durable storage for user documents (Tables) plus first-party analytics.

    Replaces browser localStorage, which is per-browser, per-profile, wiped by a
    cache clear, invisible to the server, and unshareable. A table built on a
    laptop must not vanish when the user opens the app on their phone."""
    id, name, desc = "docs", "Documents", "Durable user documents and product analytics"

    def get(self, req):
        import _docs
        if req.params.get("usage"):
            return Resp(_docs.usage())
        k = req.params.get("key")
        if k:
            d = _docs.get(k)
            return Resp({"key": k, "data": d, "found": d is not None})
        return Resp({"docs": _docs.listing(req.params.get("kind", "table")),
                     "backend": _docs.backend()})

    def post(self, req):
        import _docs
        act = req.body.get("action")
        if act == "track":
            # Analytics are fire-and-forget: a failed write must never surface
            # to the user as an error in the tool they were actually using.
            _docs.track(req.body.get("name", "view"), req.body.get("tool"),
                        req.body.get("session"), **(req.body.get("data") or {}))
            return Resp({"ok": True})
        if act == "delete":
            _docs.delete(req.body.get("key"))
            return Resp({"ok": True})
        key = req.body.get("key")
        if not key:
            return Resp({"error": "key required"}, 400)
        _docs.put(key, req.body.get("data"), req.body.get("kind", "table"))
        return Resp({"ok": True, "key": key, "backend": _docs.backend()})


class ObserveModule(Module):
    """What the agents actually did. RISK.md flagged no-observability as
    critical; this is the answer to "is it healthy" and "why did it do that"."""
    id, name, desc = "observe", "Activity", "Runs, decisions, errors, and health"

    def get(self, req):
        import _observe as O
        if req.params.get("run"):
            return Resp({"events": O.recent(200, run_id=req.params["run"])})
        import _otel
        return Resp({"metrics": O.metrics(), "tracing": _otel.status(),
                     "recent": O.recent(int(req.params.get("limit", 60)),
                                        kind=req.params.get("kind"))})


def _recorded(mod):
    """Wrap a tool module so its work lands in the context graph.

    The gap this closes: the toolkit and the harness were two disconnected
    systems sharing a sidebar. Run Signals by hand and the result rendered and
    vanished; run it through Listener and it became nodes with provenance. Same
    engine, same data, completely different consequence, which made "one graph,
    many doors" untrue and meant half the product contributed nothing to the
    moat it claims.

    Applied at the registry rather than inside each engine, so the engines stay
    pure and testable and there is exactly one place to look.
    """
    original = mod.post

    def wrapped(req, _original=original, _mod=mod):
        resp = _original(req)
        try:
            if getattr(resp, "status", 500) < 300:
                import _toolgraph
                _toolgraph.record(_mod.id, req.body or {}, resp.payload)
        except Exception:                                        # noqa: BLE001
            pass          # recording must never break the tool it observes
        return resp

    mod.post = wrapped
    return mod


def _gated(mod):
    """Wrap a module's get/post with the harness gate.

    Applied here, once, rather than as a guard line inside all fourteen entry
    points: a gate you have to remember to add is a gate you eventually forget,
    and the one you forget is the hole. Both dispatchers (app.py and _http.py)
    call get/post on these same instances, so wrapping the instance covers both
    deployments with no dispatcher change.
    """
    for name in ("get", "post"):
        original = getattr(mod, name)

        def wrapped(req, _original=original, _mod=mod):
            denied = _mod._harness_ok(req)
            return denied if denied is not None else _original(req)

        setattr(mod, name, wrapped)
    return mod


# The harness endpoints run agents and mutate the context graph, unlike the
# read-only lookup tools, so they are gated. See Module._harness_ok.
HARNESS = [_gated(m) for m in (GraphModule(), AgentsModule(), CohortsModule(),
                               InboxModule(), McpModule(), DefinitionsModule(),
                               ObserveModule(), WatchModule(), CrmModule())]
# Docs is NOT harness-gated: it stores the user's own documents and receives
# analytics pings from the browser, both of which must work without a secret.
MODULES_EXTRA = [DocsModule()]

# Tool modules whose output is worth remembering. Read-only lookups and admin
# endpoints (auth, jobs, groups, watchdog) are not: recording them would fill the
# graph with noise and bury the signal.
TOOLS = [_recorded(m) for m in (SignalsModule(), PersonaModule(), CleanModule(),
                                TranscriptModule())]

MODULES = TOOLS + MODULES_EXTRA + [ReportModule(), MonitorModule(), GroupsModule(), JobsModule(),
                   PlaysModule(), AuthModule(), WatchdogModule()] + HARNESS
REGISTRY = {m.id: m for m in MODULES}
