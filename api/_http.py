"""
Shared Vercel handler factory. Every api/<id>.py serverless function is a
3-line shim:

    from _http import make_handler
    handler = make_handler("<module id>")

make_handler() returns a BaseHTTPRequestHandler subclass that translates the
raw HTTP request into a _registry.Req, dispatches to the module's get()/post(),
and writes the _registry.Resp back (JSON, file download, or redirect). Request
parsing therefore lives in exactly one place for all functions.

No em dashes.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from _registry import REGISTRY, Req, Resp


def make_handler(module_id=None):
    """Build a handler. With a module id it serves that one module (the local
    Flask path and the per-endpoint shims). With None it resolves the module
    from the REQUEST PATH, which is what lets a single serverless function serve
    every /api/* route.

    That single-function mode exists because Vercel's Hobby plan caps a
    deployment at 12 Serverless Functions and this app has 19 endpoints. It is
    also simply the better shape: app.py already dispatches every route through
    one generic handler over the same REGISTRY, so the two deployments now match
    instead of diverging."""
    fixed = REGISTRY[module_id] if module_id else None

    class Handler(BaseHTTPRequestHandler):
        def _module(self):
            """The fixed module, or the one named by the path."""
            if fixed is not None:
                return fixed
            seg = urlparse(self.path).path.strip("/").split("/")
            mid = seg[1] if len(seg) > 1 and seg[0] == "api" else (seg[0] if seg else "")
            return REGISTRY.get(mid)

        def _req(self, method, body=None):
            q = parse_qs(urlparse(self.path).query)
            params = {k: v[0] for k, v in q.items()}
            cookies = {}
            for part in (self.headers.get("cookie", "") or "").split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies[k] = v
            host = self.headers.get("host", "")
            proto = self.headers.get("x-forwarded-proto", "https")
            return Req(method=method, params=params, body=body or {},
                       headers=dict(self.headers), cookies=cookies,
                       host_url=f"{proto}://{host}/", is_secure=proto == "https")

        def _write(self, resp):
            self.send_response(resp.status)
            if resp.payload is not None:
                self.send_header("Content-Type",
                                 resp.ctype if ";" in resp.ctype or "charset" in resp.ctype
                                 else resp.ctype + "; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            if resp.payload is None:
                return
            body = resp.payload
            if isinstance(body, (dict, list)):
                body = json.dumps(body)
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.wfile.write(body)

        def do_GET(self):
            m = self._module()
            if m is None:
                return self._write(Resp({"error": "not found"}, 404))
            self._write(m.get(self._req("GET")))

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or "{}")
            except Exception:
                return self._write_error()
            m = self._module()
            if m is None:
                return self._write(Resp({"error": "not found"}, 404))
            self._write(m.post(self._req("POST", body)))

        def _write_error(self):
            from _registry import Resp
            self._write(Resp({"error": "Send a JSON body."}, 400))

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cron-Secret")
            self.end_headers()

    return Handler
