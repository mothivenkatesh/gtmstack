"""
YouTube Transcript API — local Flask dev server.

The keyless method: youtube-transcript-api reads YouTube's own caption tracks
via the internal InnerTube / timedtext endpoints (no API key, no quota). This
server does the fetch (so the browser dodges CORS + YouTube's IP gate) and the
single-page UI in index.html calls it. Core logic lives in api/_core.py so the
exact same code path also runs as a Vercel serverless function.

Run:   python app.py        ->  http://localhost:5000
Optional translation (YouTube IP-blocks &tlang= from datacenter IPs):
    set WEBSHARE_PROXY_USER / WEBSHARE_PROXY_PASS   (Webshare residential), or
    set YT_PROXY=http://user:pass@host:port          (any residential proxy)
"""
import os
import sys

from flask import Flask, request, jsonify, send_from_directory, Response, redirect
from flask_cors import CORS

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    """Minimal .env loader, no dependency. KEY=VALUE per line, # comments and
    optional surrounding quotes allowed. Never overwrites a var already set in
    the real environment, so explicit env values still win. Lets Signals creds
    (GITHUB_TOKEN, REDDIT_CLIENT_ID/SECRET, LINKEDIN_PROFILE_DIR) persist across
    restarts instead of being re-exported by hand each time."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(HERE, ".env"))
# api/ holds the shared core (so the Vercel function and this server agree).
sys.path.insert(0, os.path.join(HERE, "api"))
from _core import fetch_transcript, build_api  # noqa: E402
from _personas import preview, persona_roster  # noqa: E402
from _signals import lookup as signals_lookup, sources_status  # noqa: E402
from _jobs import (  # noqa: E402
    submit as jobs_submit, get as jobs_get, recent as jobs_recent,
    export as jobs_export)
from _clean import (  # noqa: E402
    clean as clean_validate, to_csv as clean_csv, to_json as clean_json)
from _plays import (  # noqa: E402
    list_plays as plays_list, run_play as plays_run)
from _groups import list_groups as report_groups  # noqa: E402
from _report import (  # noqa: E402
    run_report, reports_index, latest_report, get_report)
from _monitor import (  # noqa: E402
    overview as monitor_overview, run_monitor, staleness_hours)
from _mentions import recent as monitor_recent  # noqa: E402

app = Flask(__name__, static_folder=HERE, static_url_path="")
CORS(app)
api = build_api()  # build once, reuse across requests


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.get("/api/transcript")
def transcript():
    payload, status = fetch_transcript(
        request.args.get("url", ""),
        request.args.get("lang"),
        request.args.get("translate"),
        api=api,
    )
    return jsonify(payload), status


@app.get("/api/persona")
def persona_list():
    return jsonify(personas=persona_roster())


@app.post("/api/persona")
def persona_preview():
    body = request.get_json(silent=True) or {}
    payload, status = preview(
        body.get("text", ""),
        body.get("type", "landing"),
        body.get("personas") or None,
    )
    return jsonify(payload), status


@app.get("/api/signals")
def signals_status():
    return jsonify(sources=sources_status())


@app.post("/api/signals")
def signals_lookup_route():
    body = request.get_json(silent=True) or {}
    payload, status = signals_lookup(
        body.get("query", ""),
        body.get("sources") or None,
        body.get("handles") or None,
        bool(body.get("force")),
        body.get("unit") or "person",
    )
    return jsonify(payload), status


@app.get("/api/report")
def report_read():
    """Read side for the Reports tab: groups, a report index, or one report."""
    if request.args.get("groups"):
        return jsonify(groups=report_groups())
    if request.args.get("id"):
        return jsonify(get_report(request.args["id"]) or {"error": "not found"})
    gid = request.args.get("group")
    if gid and request.args.get("list"):
        return jsonify(reports=reports_index(gid))
    if gid:
        return jsonify(latest_report(gid) or {"error": "no report yet", "group_id": gid})
    return jsonify(groups=report_groups(), reports=reports_index())


@app.post("/api/report")
def report_run():
    """Run a group's report now (the launchd CLI calls run_report directly)."""
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("X-Cron-Secret") != secret:
        return jsonify(error="unauthorized"), 401
    body = request.get_json(silent=True) or {}
    payload, status = run_report(
        body.get("group", ""),
        body.get("sources") or None,
        float(body.get("budget_s") or 45),
        body.get("use_llm"),
    )
    return jsonify(payload), status


@app.get("/api/monitor")
def monitor_read():
    """Read side for the Monitor panel: overview, one group's mentions, or the
    staleness watchdog value."""
    if request.args.get("staleness"):
        return jsonify(hours=staleness_hours())
    gid = request.args.get("group")
    if gid:
        return jsonify(group_id=gid, mentions=monitor_recent(gid, 200))
    return jsonify(monitor_overview())


@app.post("/api/monitor")
def monitor_run():
    """Run the competitive monitor now. CRON_SECRET-gated like the report."""
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("X-Cron-Secret") != secret:
        return jsonify(error="unauthorized"), 401
    body = request.get_json(silent=True) or {}
    summary = run_monitor(only=body.get("only"), catchup=bool(body.get("catchup")))
    return jsonify(summary)


@app.get("/api/groups")
def groups_read():
    return jsonify(groups=report_groups())


@app.post("/api/groups")
def groups_write():
    """Create or edit a keyword group. CRON_SECRET-gated writes (read-only on the
    hosted deploy). Hand-editing api/_store/groups.json is the documented interim."""
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("X-Cron-Secret") != secret:
        return jsonify(error="unauthorized"), 401
    from _groups import save_group, delete_group
    body = request.get_json(silent=True) or {}
    if body.get("delete"):
        return jsonify(ok=delete_group(body.get("id", "")))
    saved = save_group(body)
    return (jsonify(group=saved), 200) if saved else (jsonify(error="bad group"), 400)


@app.post("/api/jobs")
def jobs_create():
    """Submit a lookup as an async job. Returns 202 + a queued job (poll it), or
    200 + a finished job when running inline (SIGNALS_SYNC_JOBS=1)."""
    body = request.get_json(silent=True) or {}
    job = jobs_submit(body)
    done = bool(job and job.get("status") in ("done", "error"))
    return jsonify(job), (200 if done else 202)


@app.get("/api/jobs")
def jobs_read():
    """No id -> recent jobs. ?id=X -> that job. ?id=X&format=csv|json -> export."""
    job_id = request.args.get("id")
    if not job_id:
        return jsonify(jobs=jobs_recent())
    fmt = request.args.get("format")
    if fmt:
        body, ctype, fname = jobs_export(job_id, fmt)
        if body is None:
            return jsonify(error="Job not finished or not found."), 404
        return Response(body, headers={
            "Content-Type": ctype,
            "Content-Disposition": f'attachment; filename="{fname}"'})
    job = jobs_get(job_id)
    if not job:
        return jsonify(error="Job not found."), 404
    return jsonify(job)


@app.post("/api/clean")
def clean_route():
    """Validate + dedupe a contact list. Returns agent-ready rows. With
    ?format=csv|json (and optional ?only=clean) returns a downloadable file."""
    body = request.get_json(silent=True) or {}
    payload, status = clean_validate(
        body.get("text", ""),
        body.get("emails") or None,
        bool(body.get("check_smtp")),
    )
    fmt = (request.args.get("format") or body.get("format") or "").lower()
    if status == 200 and fmt in ("csv", "json"):
        only = (request.args.get("only") or body.get("only")) == "clean"
        text = clean_csv(payload, only) if fmt == "csv" else clean_json(payload, only)
        ctype = "text/csv" if fmt == "csv" else "application/json"
        fname = f"clean-emails.{fmt}"
        return Response(text, headers={
            "Content-Type": ctype + "; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{fname}"'})
    return jsonify(payload), status


@app.get("/api/plays")
def plays_index():
    """List the composite plays an agent (or the Home UI) can run."""
    return jsonify(plays=plays_list())


@app.post("/api/plays")
def plays_execute():
    """Run a play inline: {play, input}. Returns a steps[] array; never 500s on
    a bad step (the failure lands in the step with status 'error')."""
    body = request.get_json(silent=True) or {}
    payload, status = plays_run(body.get("play", ""), body.get("input") or {})
    return jsonify(payload), status


@app.route("/api/auth", methods=["GET", "POST"])
def auth_route():
    """Passwordless sign-in, same controller as the Vercel function."""
    import _accounts
    if request.method == "GET":
        action = request.args.get("action", "")
        if action == "verify":
            sess, ok, first = _accounts.consume_link(request.args.get("token", ""))
            resp = redirect(("/?welcome=1" if first else "/") if ok else "/?auth=expired")
            if ok:
                resp.set_cookie(_accounts.COOKIE, sess, max_age=_accounts.SESSION_MAX_AGE,
                                httponly=True, samesite="Lax", secure=request.is_secure)
            return resp
        if action == "me":
            return jsonify(_accounts.whoami(request.cookies.get(_accounts.COOKIE)))
        if action == "runs":
            return jsonify(_accounts.list_runs(request.cookies.get(_accounts.COOKIE)))
        return jsonify({"error": "unknown action"}), 400
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action == "request":
        payload, status = _accounts.request_link(body.get("email", ""), request.host_url)
        return jsonify(payload), status
    if action == "logout":
        resp = jsonify({"ok": True})
        resp.delete_cookie(_accounts.COOKIE)
        return resp
    if action == "run":
        return jsonify(_accounts.record_run(
            request.cookies.get(_accounts.COOKIE), body.get("tool", ""), body.get("summary", "")))
    return jsonify({"error": "unknown action"}), 400


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  YouTube Transcript API  ->  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
