"""
Connectors via Nango (unified API). GTMstack talks to Nango's REST API to run the
OAuth connect flow and proxy authenticated requests to a user's SaaS tools
(Salesforce, HubSpot, Slack, ...), keyed by the GTMstack user id.

Env-gated on NANGO_SECRET_KEY, like every other capability: without it,
configured() is False and the Connectors tab stays inert. Nango Cloud hosts the
OAuth callback on its own domain, so this works identically from localhost and any
host, no tunnel. Pure requests, no SDK.

Exact Nango request/response shapes are confirmed against a live key when the first
connection is made; the structure and gating below do not change.
"""
from __future__ import annotations

import os

try:
    import requests
except Exception:                      # pragma: no cover
    requests = None

NANGO_BASE = os.getenv("NANGO_BASE_URL", "https://api.nango.dev")
TIMEOUT = 30


def configured() -> bool:
    return bool(os.getenv("NANGO_SECRET_KEY") and requests)


def _headers(extra=None):
    h = {"Authorization": f"Bearer {os.getenv('NANGO_SECRET_KEY')}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def connect_session(user_id, integrations=None):
    """Create a Connect session token for the frontend connect UI, scoped to this
    end user. integrations: optional list of provider config keys to allow.
    Returns (payload, status)."""
    if not configured():
        return {"error": "Connectors are not set up (add NANGO_SECRET_KEY)."}, 503
    body = {"end_user": {"id": str(user_id)}}
    if integrations:
        body["allowed_integrations"] = integrations
    try:
        r = requests.post(f"{NANGO_BASE}/connect/sessions",
                          headers=_headers(), json=body, timeout=TIMEOUT)
        if r.status_code in (200, 201):
            d = r.json() or {}
            tok = (d.get("data") or {}).get("token") or d.get("token")
            return {"token": tok}, 200
        return {"error": f"Nango session failed (HTTP {r.status_code})."}, 502
    except Exception as e:
        return {"error": f"Nango unreachable ({type(e).__name__})."}, 502


def list_connections(user_id):
    """Which integrations this user has connected. Never raises; returns
    {connections:[provider_config_key,...], configured}."""
    if not configured():
        return {"connections": [], "configured": False}
    try:
        r = requests.get(f"{NANGO_BASE}/connection",
                         headers=_headers(), params={"endUserId": str(user_id)},
                         timeout=TIMEOUT)
        if r.status_code == 200:
            d = r.json() or {}
            conns = d.get("connections") or d.get("data") or []
            keys = [c.get("provider_config_key") or c.get("provider") for c in conns]
            return {"connections": [k for k in keys if k], "configured": True}
        return {"connections": [], "configured": True, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"connections": [], "configured": True, "error": type(e).__name__}


def proxy(user_id, provider, method, endpoint, params=None, data=None):
    """Authenticated request to a connected provider via Nango's proxy. Nango
    injects the OAuth token and forwards to the provider. Returns (payload, status)."""
    if not configured():
        return {"error": "Connectors are not set up."}, 503
    h = _headers({"Connection-Id": str(user_id), "Provider-Config-Key": provider})
    url = f"{NANGO_BASE}/proxy{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    try:
        r = requests.request(method.upper(), url, headers=h, params=params,
                             json=data, timeout=TIMEOUT)
        ok = 200 <= r.status_code < 300
        try:
            body = r.json()
        except Exception:
            body = {"raw": (r.text or "")[:500]}
        return body, (200 if ok else r.status_code)
    except Exception as e:
        return {"error": f"Proxy failed ({type(e).__name__})."}, 502
