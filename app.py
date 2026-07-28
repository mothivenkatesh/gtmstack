"""
GTMstack local Flask dev server.

One generic route dispatches every /api/<module> request through the module
REGISTRY (api/_registry.py), the same classes the Vercel functions use, so the
two deployments cannot drift. This file only wires HTTP to the registry and
serves the static frontend.

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
from _registry import REGISTRY, Req  # noqa: E402

app = Flask(__name__, static_folder=HERE, static_url_path="")
CORS(app)


# `static_folder=HERE` serves the whole project directory, which means the dev
# server will happily hand out .env, cookies, and internal docs to anyone who
# asks. Production is already safe (.vercelignore keeps them off the deploy),
# but "it is only localhost" is not a guarantee: this app has webhook features,
# so tunnelling the dev server through ngrok is a normal thing to do, and that
# turns a local convenience into nine leaked credentials.
#
# Mirrors .vercelignore. Keep the two in step.
_BLOCKED_NAMES = {
    ".env", ".env.example", "app.py", "daily_report.py", "connect_sources.py",
    "claude.md", "risk.md", "roadmap.md", "monitor_plan.md", "design_system.md",
    "case_study_notes.md", "ui_generation_context.md", "requirements.txt",
    "vercel.json", ".vercelignore", ".gitignore", "mcp_server.py",
}
_BLOCKED_PREFIXES = (".git", ".venv", ".vercel", ".claude", "api/_store",
                     "tests", "launchd", "evals", "__pycache__", ".gtmstack")
_BLOCKED_SUFFIXES = (".py", ".db", ".sqlite", ".pyc", ".log", ".pem", ".key")


def _is_blocked(path):
    p = (path or "").lstrip("/").replace("\\", "/")
    low = p.lower()
    name = low.rsplit("/", 1)[-1]
    if name in _BLOCKED_NAMES or low in _BLOCKED_NAMES:
        return True
    if any(low.startswith(pre) for pre in _BLOCKED_PREFIXES):
        return True
    if low.endswith(_BLOCKED_SUFFIXES):
        return True
    # Anything that looks like a credential store, whatever it is called.
    return any(w in low for w in ("cookie", "secret", "credential", "token"))


@app.before_request
def _block_sensitive_static():
    """Refuse before Flask's static handler ever sees the path.

    A real API route is ONE segment (/api/signals). Anything deeper is a file on
    disk that merely starts with the same prefix, so /api/_store/graph.db must
    still be checked: exempting the whole /api/ tree is how the graph database
    stayed downloadable after the first pass at this.
    """
    p = request.path
    if p.startswith("/api/") and "/" not in p[5:].rstrip("/"):
        return None
    if _is_blocked(p):
        return jsonify({"error": "not found"}), 404
    return None


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/api/<mod_id>", methods=["GET", "POST"])
def api_dispatch(mod_id):
    """Every API endpoint: translate the Flask request into a registry Req,
    dispatch to the module, translate its Resp back."""
    m = REGISTRY.get(mod_id)
    if not m:
        return jsonify(error="unknown module"), 404
    req = Req(method=request.method,
              params={k: v for k, v in request.args.items()},
              body=request.get_json(silent=True) or {},
              headers=dict(request.headers),
              cookies=dict(request.cookies),
              host_url=request.host_url,
              is_secure=request.is_secure)
    r = m.get(req) if request.method == "GET" else m.post(req)
    if r.status in (301, 302) and "Location" in r.headers:
        resp = redirect(r.headers["Location"], code=r.status)
        for k, v in r.headers.items():
            if k != "Location":
                resp.headers[k] = v
        return resp
    if isinstance(r.payload, (dict, list)):
        resp = jsonify(r.payload)
    else:
        resp = Response(r.payload or "", content_type=r.ctype)
    for k, v in r.headers.items():
        resp.headers[k] = v
    return resp, r.status


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  GTMstack dev server  ->  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
