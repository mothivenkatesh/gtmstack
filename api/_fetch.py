"""
GTMforce — resilient transport (the uninterrupted-scrape cascade).

One deterministic, LLM-free fetch path every Signals adapter shares, so a single
flaky source or a rate-limit never takes the run down. The seven layers, in order:

  1. Official API       the adapter's choice of endpoint            (caller owns)
  2. Auth session       the adapter's cookies / headers             (caller owns)
  3. Browser-grade HTTP  curl_cffi impersonate (TLS/JA3), requests fallback
  4. Rate governor + backoff   per-host politeness gap + exponential backoff that
                               honours Retry-After, so we stay polite and under limits
  5. Proxy pool (BYO)    rotate proxies YOU supply (env), cooldown a proxy on failure
  6. Cache / archive     the caller passes an `archive` fallback (Wayback,
                         Arctic-Shift, last-good cache) used only when live is exhausted
  7. Circuit breaker     after N hard failures a host trips open for a cooldown, so we
                         fail fast and the other sources keep going

Layers 1-2 belong to the adapter (it builds the URL + auth); 3-7 live here.
Compliant by design: no stealth browser, no bot-detection bypass. Proxies are
bring-your-own and the caller owns the per-site ToS call (see CLAUDE.md). Pure
Python, no model calls, safe to run on a cron or serverless.
"""
from __future__ import annotations

import os
import random
import threading
import time

try:
    import requests
except Exception:           # pragma: no cover
    requests = None
try:
    from curl_cffi import requests as _curl
except Exception:           # pragma: no cover
    _curl = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Tunables, all env-overridable. Defaults are polite and add no latency to a
# healthy run (MIN_INTERVAL 0); they only kick in under failure or rate limits.
MAX_RETRIES      = int(os.getenv("FETCH_MAX_RETRIES", "3"))
BACKOFF_BASE     = float(os.getenv("FETCH_BACKOFF_BASE", "0.8"))    # seconds
BACKOFF_CAP      = float(os.getenv("FETCH_BACKOFF_CAP", "8"))
MIN_INTERVAL     = float(os.getenv("FETCH_MIN_INTERVAL", "0"))      # per-host gap
BREAKER_FAILS    = int(os.getenv("FETCH_BREAKER_FAILS", "4"))
BREAKER_COOLDOWN = float(os.getenv("FETCH_BREAKER_COOLDOWN", "60"))
PROXY_COOLDOWN   = float(os.getenv("FETCH_PROXY_COOLDOWN", "120"))
RETRY_STATUS     = {429, 500, 502, 503, 504}


class Blocked(Exception):
    """A host's circuit breaker is open; the live fetch was skipped this call."""


# ── per-host state: politeness clock + failure breaker ────────────────────────
class _HostState:
    __slots__ = ("lock", "last_req", "fails", "open_until")

    def __init__(self):
        self.lock = threading.Lock()
        self.last_req = 0.0
        self.fails = 0
        self.open_until = 0.0


_HOSTS = {}
_HOSTS_LOCK = threading.Lock()


def _host_of(url):
    try:
        return url.split("/", 3)[2].lower()
    except Exception:
        return str(url)


def _state(host):
    with _HOSTS_LOCK:
        st = _HOSTS.get(host)
        if st is None:
            st = _HOSTS[host] = _HostState()
        return st


def _backoff(attempt):
    """Exponential backoff with full jitter, capped."""
    return min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt)) * (0.5 + random.random())


def _retry_after(resp):
    try:
        v = resp.headers.get("Retry-After")
        return float(v) if v else None
    except Exception:
        return None


def _ok(st):
    with st.lock:
        st.fails = 0
        st.open_until = 0.0


def _fail(st):
    with st.lock:
        st.fails += 1
        if st.fails >= BREAKER_FAILS:
            st.open_until = time.time() + BREAKER_COOLDOWN


# ── layer 5: bring-your-own proxy pool ────────────────────────────────────────
_PROXY_RESTED = {}      # proxy url -> epoch until which it is cooling down


def _proxy_list():
    raw = os.getenv("GTMFORCE_PROXIES") or os.getenv("WEBSHARE_PROXY_URL") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def _pick_proxy():
    now = time.time()
    live = [p for p in _proxy_list() if _PROXY_RESTED.get(p, 0) <= now]
    if not live:
        return None
    url = random.choice(live)
    return {"http": url, "https": url}


def _rest_proxy(proxydict):
    if proxydict:
        url = proxydict.get("https") or proxydict.get("http")
        if url:
            _PROXY_RESTED[url] = time.time() + PROXY_COOLDOWN


def session_proxy():
    """A proxy dict for a long-lived session (e.g. the X browser session), or
    None. Lets the auth-session adapters share the BYO proxy pool."""
    return _pick_proxy()


# ── observability: per-host breaker snapshot for source status ────────────────
def status():
    now = time.time()
    out = {}
    with _HOSTS_LOCK:
        for h, st in _HOSTS.items():
            out[h] = {"fails": st.fails, "open": st.open_until > now,
                      "open_for": max(0.0, round(st.open_until - now, 1))}
    return out


def _transport_get(url, headers, timeout, impersonate, proxydict):
    if _curl is not None:
        kw = {"headers": headers, "timeout": timeout, "impersonate": impersonate}
        if proxydict:
            kw["proxies"] = proxydict
        return _curl.get(url, **kw)
    if requests is None:
        raise RuntimeError("no HTTP client available")
    return requests.get(url, headers=headers, timeout=timeout, proxies=proxydict)


def get(url, headers=None, timeout=12, impersonate="chrome", host=None,
        retries=MAX_RETRIES, archive=None):
    """The layer 3-7 cascade around a single GET.

    Returns a response object (the caller inspects .status_code / .json() / .text
    exactly as before). On a retryable status (429/5xx) it backs off and retries,
    honouring Retry-After. When the host breaker is open it fails fast: it calls
    `archive()` if given, else raises Blocked. When live is exhausted it falls to
    `archive()` if given, else returns the last response or raises the last error.
    """
    hdr = {"user-agent": UA, "accept-language": "en-US,en;q=0.9"}
    if headers:
        hdr.update(headers)
    host = host or _host_of(url)
    st = _state(host)

    # layer 7: breaker open -> skip live, fail fast (or serve archive)
    if st.open_until > time.time():
        if archive is not None:
            return archive()
        raise Blocked(f"{host} circuit open for "
                      f"{round(st.open_until - time.time(), 1)}s")

    # layer 4: per-host politeness gap
    with st.lock:
        wait = MIN_INTERVAL - (time.time() - st.last_req)
        if wait > 0:
            time.sleep(wait)
        st.last_req = time.time()

    last_exc, last_resp = None, None
    for attempt in range(retries + 1):
        proxydict = _pick_proxy()                      # layer 5
        try:
            r = _transport_get(url, hdr, timeout, impersonate, proxydict)
        except Exception as e:                         # network / proxy failure
            last_exc = e
            _rest_proxy(proxydict)
            if attempt < retries:
                time.sleep(_backoff(attempt))
            continue

        code = getattr(r, "status_code", 0)
        if code in RETRY_STATUS and attempt < retries:  # layer 4: back off + retry
            last_resp = r
            ra = _retry_after(r)
            time.sleep(ra if ra is not None else _backoff(attempt))
            continue
        if code in RETRY_STATUS:                        # retries exhausted
            _fail(st)
            return archive() if archive is not None else r
        _ok(st)                                         # success (incl. 4xx auth)
        return r

    # all attempts raised at the transport level
    _fail(st)
    if archive is not None:
        return archive()
    if last_resp is not None:
        return last_resp
    raise last_exc if last_exc else RuntimeError(f"fetch failed for {host}")
