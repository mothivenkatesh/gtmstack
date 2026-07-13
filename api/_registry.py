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


MODULES = [TranscriptModule(), PersonaModule(), SignalsModule(), ReportModule(),
           MonitorModule(), GroupsModule(), JobsModule(), CleanModule(),
           PlaysModule(), AuthModule(), WatchdogModule()]
REGISTRY = {m.id: m for m in MODULES}
