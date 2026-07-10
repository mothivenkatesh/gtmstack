"""
GTMstack — Signals engine (data intelligence layer).

Give it a name / handle / email and it fans out across the channels developers
actually live in, returning ONE normalized footprint card: who they are plus
what they posted most recently, per platform. `lookup` dispatches by `unit`:
person (default), company (footprint + the people who work there), or keyword
(a merged, time-sorted mentions feed). Async + bulk delivery lives in _jobs.py.

Phase 1 (this file):
  - GitHub      : public REST API, no login. Works out of the box.
  - Reddit      : official OAuth app-only flow (free app id + secret). The
                  unauthenticated .json endpoints now 403 from datacenter IPs.
  - LinkedIn    : Voyager internal API (needs li_at + JSESSIONID via env/cookies).
  - X (Twitter) : authenticated GraphQL when a session is connected (X_PROFILE_DIR),
                  else best-effort public syndication; either way degrades cleanly.

The wedge vs bulk-export vendors (Crustdata, moltsets): freshness + the
dev-native channels. Not "download 50k rows", but "what did THIS person post
today across GitHub, Reddit, LinkedIn, and X."

Design rules:
  - One source failing NEVER breaks the card. Every adapter is wrapped and
    returns a status: ok | needs_connection | not_found | error.
  - Real-time first: results are cached (SQLite) with a short TTL; callers can
    force a fresh pull. The "cached" flag is surfaced so the UI shows freshness.

SELLABLE-PRODUCT GATES (NOT satisfied here — clear before any external launch):
  - Multi-tenant isolation + per-user rate budgets + auth.
  - Warmed burner-account pool + residential proxy rotation. LinkedIn and X ban
    single-cookie / single-IP scraping patterns fast; a sold product cannot lean
    on one personal session.
  - PII handling + lawful-basis review (GDPR / India DPDP), ToS / CFAA posture,
    subject opt-out + deletion path.
  This module is the working SINGLE-TENANT slice. Phase 2 wraps it in that infra.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone

try:
    import requests  # noqa
except Exception:  # pragma: no cover
    requests = None

# curl_cffi impersonates a real browser's TLS/JA3 fingerprint, which gets past
# the TLS-level bot walls that plain `requests` trips (Reddit, X). Optional:
# falls back to requests when unavailable.
try:
    from curl_cffi import requests as _curl  # noqa
except Exception:  # pragma: no cover
    _curl = None

# Shared resilient transport: every adapter's HTTP inherits per-host backoff,
# BYO proxy rotation, and a circuit breaker through this one chokepoint.
from _fetch import get as _fetch_get, session_proxy as _fetch_session_proxy

# ── tunables ────────────────────────────────────────────────────────────────
CACHE_TTL = int(os.getenv("SIGNALS_CACHE_TTL", "1800"))   # 30 min default
HTTP_TIMEOUT = int(os.getenv("SIGNALS_HTTP_TIMEOUT", "12"))
MAX_ACTIVITY = 8
ALL_SOURCES = ("github", "reddit", "linkedin", "x", "youtube")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# Reddit's public JSON allows script-style UAs but 403s browser-mimic UAs from
# datacenter IPs, so the Reddit adapter uses its own descriptive agent.
REDDIT_UA = os.getenv("REDDIT_UA", "gtmstack-signals/0.1 (live-signals; research)")

_DB = os.getenv("SIGNALS_CACHE_DB") or os.path.join(
    tempfile.gettempdir(), "gtmstack_signals.db")


# ── tiny helpers ────────────────────────────────────────────────────────────
def _get(url, headers=None, timeout=HTTP_TIMEOUT, impersonate="chrome"):
    """GET through the shared resilient transport (_fetch): browser TLS
    fingerprint (layer 3), per-host backoff honouring Retry-After (4), BYO proxy
    rotation (5), and a circuit breaker (7), so one blocked source never stalls
    the run. Returns the response object; raises _fetch.Blocked when the host
    breaker is open, which each adapter's try/except degrades to a clean status."""
    return _fetch_get(url, headers=headers, timeout=timeout, impersonate=impersonate)


def _human(n):
    """1234 -> '1.2K', 1_200_000 -> '1.2M'."""
    try:
        n = float(n)
    except Exception:
        return str(n)
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if abs(n) >= div:
            v = n / div
            return (f"{v:.1f}".rstrip("0").rstrip(".")) + unit
    return str(int(n))


def _iso(epoch):
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _ago(epoch):
    try:
        delta = time.time() - float(epoch)
    except Exception:
        return ""
    if delta < 0:
        delta = 0
    mins = delta / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    hrs = mins / 60
    if hrs < 24:
        return f"{int(hrs)}h ago"
    days = hrs / 24
    if days < 30:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days / 30)}mo ago"
    return f"{int(days / 365)}y ago"


def _clean(s, limit=420):
    if not s:
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip()
    return (s[:limit] + "…") if len(s) > limit else s


def _src(platform, status, **kw):
    """Build a normalized source block. Every adapter returns this shape."""
    base = {
        "platform": platform,
        "status": status,            # ok | needs_connection | not_found | error
        "handle": kw.get("handle"),
        "profile_url": kw.get("profile_url"),
        "display_name": kw.get("display_name"),
        "avatar": kw.get("avatar"),
        "headline": kw.get("headline"),
        "location": kw.get("location"),
        "stats": kw.get("stats", []),       # [{label, value}]
        "activity": kw.get("activity", []),  # [{kind, text, url, ts, ago, where, engagement[]}]
        "note": kw.get("note"),
    }
    return base


# ── credentials ─────────────────────────────────────────────────────────────
def _chromium_cookie_jar(profile_dir, domain):
    """Decrypt the FULL cookie jar for `domain` from a local Chromium
    user-data-dir (Windows DPAPI + AES-GCM). Returns {name: value} or None.
    Sending every cookie the browser holds (not just the auth token) is what
    stops LinkedIn and X soft-challenging the request as a bot. Platform/lib
    guarded: returns None off-Windows or without the crypto libs."""
    try:
        import base64
        import shutil
        import win32crypt  # type: ignore
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:
        return None
    try:
        ls = json.load(open(os.path.join(profile_dir, "Local State"), encoding="utf-8"))
        key = win32crypt.CryptUnprotectData(
            base64.b64decode(ls["os_crypt"]["encrypted_key"])[5:],
            None, None, None, 0)[1]
        aes = AESGCM(key)
        db = next((os.path.join(profile_dir, *p) for p in (
            ("Default", "Network", "Cookies"), ("Network", "Cookies"),
            ("Default", "Cookies"), ("Cookies",))
            if os.path.exists(os.path.join(profile_dir, *p))), None)
        if not db:
            return None
        tmp = os.path.join(tempfile.gettempdir(), "gtmf_ck.db")
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(tmp)
        out = {}
        for name, enc in conn.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",)
        ):
            if not enc or enc[:3] not in (b"v10", b"v11"):
                continue
            try:
                raw = aes.decrypt(enc[3:15], enc[15:], None)
            except Exception:
                continue
            try:
                val = raw.decode("ascii")                  # no prefix
            except UnicodeDecodeError:
                val = raw[32:].decode("utf-8", "ignore")   # strip Chrome 130+ hash
            out[name] = val
        conn.close()
        os.remove(tmp)
        return out or None
    except Exception:
        return None


def _browser_session():
    """A session with a real Chrome TLS/JA3 fingerprint when curl_cffi is
    present. Plain `requests` has a Python fingerprint that LinkedIn and X flag
    on sight, which is half of why single-cookie reads get soft-challenged."""
    if _curl is not None:
        s = _curl.Session(impersonate="chrome")
        p = _fetch_session_proxy()      # layer 5: share the BYO proxy pool
        if p:
            s.proxies = p
        return s
    return requests.Session()


def _li_creds():
    """li_at + JSESSIONID from, in order: explicit env, a cookies.json file, or
    a local Chromium profile dir. None if no source is configured."""
    li_at, jsess = os.getenv("LI_AT"), os.getenv("LI_JSESSIONID")
    if li_at and jsess:
        return {"li_at": li_at, "JSESSIONID": jsess}
    path = os.getenv("LINKEDIN_COOKIES")
    if path and os.path.exists(path):
        try:
            c = json.load(open(path, encoding="utf-8"))
            if c.get("li_at") and c.get("JSESSIONID"):
                return {"li_at": c["li_at"], "JSESSIONID": c["JSESSIONID"]}
        except Exception:
            pass
    prof = os.getenv("LINKEDIN_PROFILE_DIR")
    if prof and os.path.isdir(prof):
        jar = _chromium_cookie_jar(prof, "linkedin.com")
        if jar and jar.get("li_at") and jar.get("JSESSIONID"):
            return {"li_at": jar["li_at"], "JSESSIONID": jar["JSESSIONID"]}
    return None


def _li_jar():
    """Full LinkedIn cookie jar for the actual request. Prefers the complete
    browser jar (every cookie, so no soft-challenge); falls back to the minimal
    env/file pair when only those are configured. Source order: an exported
    cookies.json (every cookie the user pasted, freshest), then a local Chromium
    profile, then the minimal env pair."""
    path = os.getenv("LINKEDIN_COOKIES")
    if path and os.path.exists(path):
        try:
            c = json.load(open(path, encoding="utf-8"))
            if isinstance(c, dict) and c.get("li_at") and c.get("JSESSIONID"):
                return dict(c)        # whole flat jar, not just the pair
        except Exception:
            pass
    prof = os.getenv("LINKEDIN_PROFILE_DIR")
    if prof and os.path.isdir(prof):
        jar = _chromium_cookie_jar(prof, "linkedin.com")
        if jar and jar.get("li_at") and jar.get("JSESSIONID"):
            return jar
    c = _li_creds()
    return dict(c) if c else None


def _x_jar():
    """x.com cookie jar, from (in order): explicit env pair, an exported jar
    file, or a logged-in Chromium profile. Needs auth_token + ct0 to be usable.
    The env/file paths exist so macOS (where the Chromium profile decrypt is
    Windows-only) can supply a session directly, e.g. via connect_sources.py."""
    at, ct0 = os.getenv("X_AUTH_TOKEN"), os.getenv("X_CT0")
    if at and ct0:
        return {"auth_token": at, "ct0": ct0}
    path = os.getenv("X_COOKIES")
    if path and os.path.exists(path):
        try:
            c = json.load(open(path, encoding="utf-8"))
            if isinstance(c, dict) and c.get("auth_token") and c.get("ct0"):
                return dict(c)        # whole flat jar, fewer soft-challenges
        except Exception:
            pass
    prof = os.getenv("X_PROFILE_DIR")
    if prof and os.path.isdir(prof):
        jar = _chromium_cookie_jar(prof, "x.com")
        if jar and jar.get("auth_token") and jar.get("ct0"):
            return jar
    return None


def sources_status():
    """Per-platform readiness, so the UI can show live vs needs-connection."""
    reddit_oauth = bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))
    gh_token = bool(os.getenv("GITHUB_TOKEN"))
    return {
        "github":   {"ready": True, "mode": "token" if gh_token else "public",
                     "label": "GitHub",
                     "note": ("Connected with a token (5,000 reads/hour)." if gh_token else
                              "Live on the public API. Add a GITHUB_TOKEN to lift the rate limit.")},
        "reddit":   {"ready": True, "mode": "oauth" if reddit_oauth else "archive",
                     "label": "Reddit",
                     "note": ("Connected via Reddit app." if reddit_oauth else
                              "Keyword feed via keyless archive (PullPush). Add a Reddit app "
                              "(client id + secret) for fresh, real-time results and person/company lookups.")},
        "linkedin": {"ready": _li_creds() is not None, "mode": "voyager",
                     "label": "LinkedIn",
                     "note": ("Connected." if _li_creds()
                              else "Add a LinkedIn session to enable.")},
        "x":        {"ready": _x_jar() is not None,
                     "mode": "session" if _x_jar() else "best-effort",
                     "label": "X",
                     "note": ("Connected via your X session." if _x_jar() else
                              "Public endpoint only (often rate-limited). Add an X session to enable.")},
        "youtube":  {"ready": True, "mode": "public", "label": "YouTube",
                     "note": "Live on public YouTube. No key needed."},
        "trustpilot": {"ready": True, "mode": "public", "label": "TrustPilot",
                       "note": "Live review reads for mapped brands (public JSON)."},
        "quora":    {"ready": False, "mode": "curated", "label": "Quora",
                     "note": ("Question-page reads carry real answer dates. Keyword "
                              "search is login-walled; add curated question URLs to a "
                              "group's quora_questions.")},
        "capterra": {"ready": False, "mode": "best-effort", "label": "Capterra",
                     "note": "Behind Cloudflare; needs curated numeric product ids. "
                             "Gated on a live smoke."},
        "g2":       {"ready": bool(os.getenv("G2_API_KEY")), "mode": "licensed-api",
                     "label": "G2",
                     "note": ("Connected via the licensed G2 data API." if os.getenv("G2_API_KEY")
                              else "Needs a licensed G2 data API key (G2_API_KEY). "
                                   "Scraping G2 is not compliant.")},
    }


# ── Reddit adapter ──────────────────────────────────────────────────────────
# Reddit has largely killed the unauthenticated .json endpoints (they 403 from
# datacenter / flagged IPs). The reliable, ToS-clean path is the official OAuth
# app-only flow (free: register a "script" app, 100 req/min). We try OAuth when
# REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are set, fall back to public JSON, and
# degrade to needs_connection if both are blocked.
def _reddit_token():
    cid, csec = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and csec):
        return None
    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, csec), data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_UA}, timeout=HTTP_TIMEOUT)
        if r.ok:
            return r.json().get("access_token")
    except Exception:
        pass
    return None


def _reddit_fetch(path, token):
    """Return parsed JSON or None. OAuth host when token present, else public."""
    if token:
        url = "https://oauth.reddit.com" + path
        hdr = {"Authorization": f"bearer {token}", "User-Agent": REDDIT_UA}
        try:
            r = requests.get(url, headers=hdr, timeout=HTTP_TIMEOUT)
            return r.status_code, (r.json() if "json" in r.headers.get(
                "content-type", "") else None)
        except Exception:
            return None, None
    url = "https://www.reddit.com" + path
    try:
        r = _get(url, headers={"User-Agent": REDDIT_UA, "Accept": "application/json"})
        return r.status_code, (r.json() if "json" in r.headers.get(
            "content-type", "") else None)
    except Exception:
        return None, None


def _reddit(handle):
    h = re.sub(r"^/?(u/|user/)", "", handle.strip(), flags=re.I).strip().lstrip("@")
    if not h:
        return _src("reddit", "not_found", handle=handle)
    prof = f"https://www.reddit.com/user/{h}"
    token = _reddit_token()

    code, about = _reddit_fetch(f"/user/{h}/about.json?raw_json=1", token)
    if code == 404:
        return _src("reddit", "not_found", handle=h, profile_url=prof)
    if about is None:
        note = ("Reddit blocked this lookup. Add a Reddit app "
                "(REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET) to enable live reads."
                if not token else
                "Reddit session is connected but did not return data. Retry shortly.")
        return _src("reddit", "needs_connection" if not token else "error",
                    handle=h, profile_url=prof, note=note)
    d = about.get("data", {})
    if not d:
        return _src("reddit", "not_found", handle=h, profile_url=prof)

    stats = []
    if d.get("total_karma") is not None:
        stats.append({"label": "Karma", "value": _human(d["total_karma"])})
    if d.get("created_utc"):
        stats.append({"label": "Joined", "value": _ago(d["created_utc"]).replace(" ago", "")})

    _, feed = _reddit_fetch(f"/user/{h}.json?limit=15&raw_json=1", token)
    children = (feed or {}).get("data", {}).get("children", []) if feed else []
    base = "https://www.reddit.com"
    activity = []
    for ch in children:
        k = ch.get("kind")
        c = ch.get("data", {})
        if k == "t3":   # submission
            text = c.get("title") or ""
            extra = c.get("selftext") or ""
            if extra:
                text = f"{text} — {extra}"
            eng = [{"label": "score", "value": _human(c.get("score", 0))},
                   {"label": "comments", "value": _human(c.get("num_comments", 0))}]
            kind = "post"
        elif k == "t1":  # comment
            text = c.get("body") or ""
            eng = [{"label": "score", "value": _human(c.get("score", 0))}]
            kind = "comment"
        else:
            continue
        activity.append({
            "kind": kind,
            "text": _clean(text),
            "url": base + (c.get("permalink") or ""),
            "ts": _iso(c.get("created_utc")),
            "ago": _ago(c.get("created_utc")),
            "where": f"r/{c.get('subreddit')}" if c.get("subreddit") else None,
            "engagement": eng,
        })
        if len(activity) >= MAX_ACTIVITY:
            break

    return _src(
        "reddit", "ok", handle=h, profile_url=prof,
        display_name=f"u/{h}",
        avatar=(d.get("icon_img") or "").split("?")[0] or None,
        headline=_clean(((d.get("subreddit") or {}).get("public_description")), 160),
        stats=stats, activity=activity,
    )


# ── LinkedIn adapter (Voyager internal API) ─────────────────────────────────
def _li_headers(jsess):
    return {
        "csrf-token": jsess,
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
        "x-li-track": ('{"clientVersion":"1.13.1665","mpVersion":"1.13.1665",'
                       '"osName":"web","timezoneOffset":5.5,'
                       '"deviceFormFactor":"DESKTOP","mpName":"voyager-web"}'),
        "user-agent": UA,
        "accept-language": "en-US,en;q=0.9",
    }


def _linkedin(handle):
    creds = _li_creds()
    h = re.sub(r"^/?(in/)", "", handle.strip(), flags=re.I).strip("/").lstrip("@")
    prof = f"https://www.linkedin.com/in/{h}/" if h else None
    if not creds:
        return _src("linkedin", "needs_connection", handle=h, profile_url=prof,
                    note=("Add a LinkedIn session (LI_AT + LI_JSESSIONID env, or "
                          "LINKEDIN_COOKIES path) to pull this profile."))
    jar = _li_jar() or dict(creds)
    jsess = (jar.get("JSESSIONID") or creds["JSESSIONID"]).strip('"')
    ck = dict(jar)
    ck["JSESSIONID"] = f'"{jsess}"'        # Voyager wants the quoted form
    s = _browser_session()                  # real Chrome TLS fingerprint
    H = _li_headers(jsess)                   # csrf-token == unquoted JSESSIONID

    # 1) identity via the modern dash 'memberIdentity' endpoint (small + clean).
    #    The legacy profileView returns HTTP 410 now. A redirect (3xx) means the
    #    session bounced to a login/challenge -> treat as a dead cookie.
    name = headline = location = avatar = None
    urn = None
    dash_url = ("https://www.linkedin.com/voyager/api/identity/dash/profiles"
                f"?q=memberIdentity&memberIdentity={requests.utils.quote(h, safe='')}")
    try:
        dr = s.get(dash_url, headers={**H, "referer": f"https://www.linkedin.com/in/{h}/"},
                   cookies=ck, timeout=HTTP_TIMEOUT, allow_redirects=False)
        if dr.status_code in (301, 302, 303, 307, 308):
            # A 3xx means the session bounced to a login/challenge. With the full
            # cookie jar + browser TLS this is rare; retry once before giving up.
            time.sleep(1.5)
            dr = s.get(dash_url, headers={**H, "referer": f"https://www.linkedin.com/in/{h}/"},
                       cookies=ck, timeout=HTTP_TIMEOUT, allow_redirects=False)
        if dr.status_code in (301, 302, 303, 307, 308):
            return _src("linkedin", "error", handle=h, profile_url=prof,
                        note=("LinkedIn bounced this session to a checkpoint. The "
                              "cookie may be stale, or the account is under a login "
                              "challenge. Open LinkedIn in that Chrome profile, clear "
                              "any prompt, then retry. At scale this needs a warmed "
                              "account pool + proxy rotation (Phase 2)."))
        if dr.status_code in (401, 403):
            return _src("linkedin", "error", handle=h, profile_url=prof,
                        note="LinkedIn session expired or blocked. Refresh the cookie.")
        if dr.status_code == 404:
            return _src("linkedin", "not_found", handle=h, profile_url=prof)
        dj = dr.json() if dr.ok else {}
        for el in dj.get("included", []) or []:
            if el.get("firstName") is not None:
                name = " ".join(x for x in [el.get("firstName"),
                                            el.get("lastName")] if x) or None
                headline = el.get("headline") or headline
                m = re.search(r"urn:li:fsd?_profile:(ACoAA[\w\-]+)",
                              el.get("entityUrn", "") or "")
                if m:
                    urn = f"urn:li:fsd_profile:{m.group(1)}"
            loc = el.get("geoLocation") or el.get("defaultLocalizedName")
            if isinstance(loc, str) and not location and "urn:" not in loc:
                location = loc
    except Exception as e:
        return _src("linkedin", "error", handle=h, profile_url=prof,
                    note=f"Could not read this profile ({type(e).__name__}).")

    # Fallback: the public profile HTML carries the fsd_profile URN reliably.
    if not urn:
        try:
            hp = s.get(f"https://www.linkedin.com/in/{h}/",
                       headers={"user-agent": UA, "accept": "text/html",
                                "accept-language": "en-US,en;q=0.9"},
                       cookies=ck, timeout=HTTP_TIMEOUT, allow_redirects=True)
            ids = re.findall(r"urn:li:fsd_profile:(ACoAA[A-Za-z0-9_-]+)", hp.text)
            if ids:
                urn = f"urn:li:fsd_profile:{max(set(ids), key=ids.count)}"
        except Exception:
            pass

    # 2) profileUpdatesV2 -> recent posts (proven path from voyager_fetch.py)
    activity = []
    if urn:
        try:
            enc = requests.utils.quote(urn, safe="")
            up = s.get(
                "https://www.linkedin.com/voyager/api/identity/profileUpdatesV2"
                f"?q=memberShareFeed&count=10&start=0&profileUrn={enc}",
                headers={**H, "referer": f"https://www.linkedin.com/in/{h}/recent-activity/all/"},
                cookies=ck, timeout=HTTP_TIMEOUT)
            inc = up.json().get("included", []) if up.ok else []
            posts, counts = {}, {}
            for el in inc:
                blob = json.dumps(el, ensure_ascii=False)
                comm = el.get("commentary")
                if isinstance(comm, dict):
                    tt = comm.get("text")
                    txt = (tt.get("text") if isinstance(tt, dict)
                           else tt if isinstance(tt, str) else None)
                    m = re.search(r"urn:li:activity:(\d+)", blob)
                    if txt and m and m.group(1) not in posts:
                        posts[m.group(1)] = txt.strip()
                eu = el.get("entityUrn", "") or ""
                if ("socialActivityCounts" in eu.lower()
                        or el.get("numLikes") is not None
                        or el.get("numComments") is not None):
                    m = re.search(r"urn:li:activity:(\d+)", eu) \
                        or re.search(r"urn:li:activity:(\d+)", blob)
                    if m:
                        counts[m.group(1)] = {
                            "reactions": el.get("numLikes"),
                            "comments": el.get("numComments"),
                            "shares": el.get("numShares"),
                        }
            for aid, txt in posts.items():
                ms = int(aid) >> 22       # snowflake -> epoch ms
                c = counts.get(aid, {})
                eng = []
                if c.get("reactions") is not None:
                    eng.append({"label": "reactions", "value": _human(c["reactions"])})
                if c.get("comments") is not None:
                    eng.append({"label": "comments", "value": _human(c["comments"])})
                activity.append({
                    "kind": "post",
                    "text": _clean(txt),
                    "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/",
                    "ts": _iso(ms / 1000),
                    "ago": _ago(ms / 1000),
                    "where": None,
                    "engagement": eng,
                })
            activity.sort(key=lambda x: x["ts"] or "", reverse=True)
            activity = activity[:MAX_ACTIVITY]
        except Exception:
            activity = []

    if not name and not activity:
        return _src("linkedin", "error", handle=h, profile_url=prof,
                    note="Connected, but LinkedIn returned no readable profile data.")
    return _src("linkedin", "ok", handle=h, profile_url=prof,
                display_name=name or h, headline=_clean(headline, 160),
                location=location, avatar=avatar, activity=activity)


# ── X / Twitter adapter ─────────────────────────────────────────────────────
# Two paths. When an X session is connected (X_PROFILE_DIR points at a logged-in
# Chromium profile) we read the real timeline via the authenticated GraphQL API:
# the live path. Without a session we fall back to the public syndication
# endpoint, which datacenter IPs usually get 429'd on, so it degrades cleanly.
#
# The web app's public Bearer token below is a fixed constant shipped in X's JS
# bundle (identical for every browser, logged in or not). The real per-session
# secret is the cookie pair auth_token + ct0, which never leaves the jar.
_X_BEARER = ("AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
             "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")

# X rotates GraphQL query ids on every frontend deploy. The robust path is
# _x_discover_qids(): read the live operation->queryId map straight from x.com's
# JS bundle (cached ~6h). These static lists are the fallback when discovery is
# unavailable, newest known id first, so a lookup still resolves either way.
_X_QID_USER = ("IGgvgiOx4QZndDHuD3x9TQ", "sLVLhk0bGj3MVFEKTdax1w",
               "xc8f1g7BYqr6VTzTbvNlGw", "Yka-W8dz7RaEuQNkroPkYw",
               "qW5u-DAuXpMEG0zA1F7UGQ", "G3KGOASz96M-Qu0nwmGXNg",
               "1VOOyvKkiI3FMmkeDNxM9A")
_X_QID_TWEETS = ("PNd0vlufvrcIwrAnBYKE9g", "E3opETHurmVJflFsUBVuUQ",
                 "V7H0Ap3_Hh2FyS75OCDO3Q", "QqZBEqganhHwmU9QocsM2g",
                 "9zwVLJ48lmVUk8u_Gh9DmA", "rwBzNG1FUUHGDuOk-3Pqdg")

# Operation-specific GraphQL feature flags. UserByScreenName needs only the
# small set; UserTweets needs the superset. Missing a required flag is a 400, so
# these mirror exactly what a live x.com web client sends.
_X_FEAT_USER = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}
_X_FEAT_TWEETS = dict(_X_FEAT_USER)
_X_FEAT_TWEETS.update({
    "responsive_web_home_pinned_timelines_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "articles_preview_enabled": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
})


def _x_headers(ct0):
    return {
        "authorization": f"Bearer {_X_BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "referer": "https://x.com/",
        "origin": "https://x.com",
        "user-agent": UA,
    }


_X_QID_TTL = int(os.getenv("SIGNALS_X_QID_TTL", "21600"))   # 6h


def _x_discover_qids():
    """Read the live operation->queryId map straight from x.com's JS bundle, so
    the adapter self-heals when X rotates ids on a deploy. Cached ~6h in the same
    SQLite store. Returns {} on any failure, so callers fall back to the static
    candidate lists."""
    try:
        conn = _db()
        row = conn.execute("SELECT ts, payload FROM sig WHERE k=?",
                           ("__x_qids__",)).fetchone()
        conn.close()
        if row and (time.time() - row[0]) < _X_QID_TTL:
            return json.loads(row[1])
    except Exception:
        pass
    qids = {}
    try:
        s = _browser_session()
        jar = _x_jar() or {}
        H = {"user-agent": UA, "accept": "*/*",
             "accept-language": "en-US,en;q=0.9"}
        home = s.get("https://x.com/home", headers=H, cookies=jar,
                     timeout=HTTP_TIMEOUT)
        html = home.text if home.status_code == 200 else ""
        mains = re.findall(r"https://abs\.twimg\.com/responsive-web/client-web/"
                           r"(?:main|api)\.[0-9a-f]+\.js", html)
        for url in list(dict.fromkeys(mains))[:4]:
            try:
                t = s.get(url, headers=H, timeout=HTTP_TIMEOUT).text
            except Exception:
                continue
            for qid, op in re.findall(
                    r'queryId:"([^"]+)",operationName:"([^"]+)"', t):
                qids.setdefault(op, qid)
            for op, qid in re.findall(
                    r'operationName:"([^"]+)",queryId:"([^"]+)"', t):
                qids.setdefault(op, qid)
    except Exception:
        qids = {}
    if qids:
        try:
            conn = _db()
            conn.execute("INSERT OR REPLACE INTO sig (k, ts, payload) VALUES (?,?,?)",
                         ("__x_qids__", time.time(), json.dumps(qids)))
            conn.commit()
            conn.close()
        except Exception:
            pass
    return qids


def _x_gql(s, jar, headers, qids, op, variables, features, method="GET"):
    """Try each candidate query id for `op`; return the parsed JSON of the first
    that returns 200 with a usable body, else None. The live discovered id (when
    available) is tried first, then the static fallback list. Profile reads are
    GET; SearchTimeline must be POST (variables+features+queryId in the body), so
    `method` switches the verb."""
    disc = _x_discover_qids().get(op)
    candidates = ([disc] if disc else []) + [q for q in qids if q != disc]
    qv = requests.utils.quote(json.dumps(variables, separators=(",", ":")))
    qf = requests.utils.quote(json.dumps(features, separators=(",", ":")))
    for qid in candidates:
        base = f"https://x.com/i/api/graphql/{qid}/{op}"
        try:
            if method == "POST":
                r = s.post(base, headers=headers, cookies=jar,
                           json={"variables": variables, "features": features,
                                 "queryId": qid},
                           timeout=HTTP_TIMEOUT, allow_redirects=False)
            else:
                r = s.get(f"{base}?variables={qv}&features={qf}", headers=headers,
                          cookies=jar, timeout=HTTP_TIMEOUT, allow_redirects=False)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            j = r.json()
        except Exception:
            continue
        if j.get("errors") and not j.get("data"):
            continue
        return j
    return None


def _x_tweet_node(node):
    """Unwrap a tweet_results.result (handles TweetWithVisibilityResults)."""
    if not isinstance(node, dict):
        return None
    if node.get("__typename") == "TweetWithVisibilityResults":
        node = node.get("tweet") or {}
    return node if (node.get("legacy") or node.get("rest_id")) else None


def _x_parse_tweets(tj, screen):
    """Pull the most recent posts out of a UserTweets timeline_v2 response."""
    try:
        instr = (((((tj.get("data") or {}).get("user") or {}).get("result")
                   or {}).get("timeline_v2") or {}).get("timeline")
                 or {}).get("instructions", [])
    except Exception:
        instr = []
    entries = []
    for ins in instr or []:
        entries.extend(ins.get("entries", []) or [])
        if ins.get("entry"):
            entries.append(ins["entry"])
    out = []
    for ent in entries:
        if not str(ent.get("entryId", "")).startswith("tweet-"):
            continue  # skip cursors, who-to-follow, conversation modules
        tr = ((((ent.get("content") or {}).get("itemContent") or {})
               .get("tweet_results") or {}).get("result"))
        tw = _x_tweet_node(tr)
        if not tw:
            continue
        leg = tw.get("legacy") or {}
        note = ((((tw.get("note_tweet") or {}).get("note_tweet_results") or {})
                 .get("result")) or {})
        text = note.get("text") or leg.get("full_text") or leg.get("text")
        if not text:
            continue
        tid = leg.get("id_str") or tw.get("rest_id")
        created = leg.get("created_at")
        epoch = None
        if created:
            try:
                epoch = datetime.strptime(
                    created, "%a %b %d %H:%M:%S %z %Y").timestamp()
            except Exception:
                epoch = None
        out.append({
            "kind": "repost" if leg.get("retweeted_status_result") else "post",
            "text": _clean(text),
            "url": (f"https://x.com/{screen}/status/{tid}" if tid
                    else f"https://x.com/{screen}"),
            "ts": _iso(epoch) if epoch else None,
            "ago": _ago(epoch) if epoch else "",
            "where": None,
            "engagement": [
                {"label": "likes", "value": _human(leg.get("favorite_count", 0))},
                {"label": "reposts", "value": _human(leg.get("retweet_count", 0))},
                {"label": "replies", "value": _human(leg.get("reply_count", 0))},
            ],
        })
        if len(out) >= MAX_ACTIVITY:
            break
    return out


def _x_authed(handle, jar):
    """Live read through the authenticated GraphQL API. Returns an ok _src block,
    or None so the caller can fall back to the public path."""
    ct0 = jar.get("ct0")
    if not ct0:
        return None
    s = _browser_session()
    H = _x_headers(ct0)
    uj = _x_gql(s, jar, H, _X_QID_USER, "UserByScreenName",
                {"screen_name": handle, "withSafetyModeUserFields": True},
                _X_FEAT_USER)
    if not uj:
        return None
    res = (((uj.get("data") or {}).get("user") or {}).get("result") or {})
    if not res or res.get("__typename") == "UserUnavailable":
        return None
    rest_id = res.get("rest_id")
    legacy = res.get("legacy") or {}
    core = res.get("core") or {}
    screen = legacy.get("screen_name") or core.get("screen_name") or handle
    name = legacy.get("name") or core.get("name") or f"@{screen}"
    desc = legacy.get("description")
    loc = legacy.get("location") or (res.get("location") or {}).get("location")
    avatar = (legacy.get("profile_image_url_https")
              or (res.get("avatar") or {}).get("image_url") or "")
    avatar = avatar.replace("_normal", "") if avatar else None
    stats = []
    if legacy.get("followers_count") is not None:
        stats.append({"label": "Followers", "value": _human(legacy["followers_count"])})
    if legacy.get("friends_count") is not None:
        stats.append({"label": "Following", "value": _human(legacy["friends_count"])})
    if legacy.get("statuses_count") is not None:
        stats.append({"label": "Posts", "value": _human(legacy["statuses_count"])})
    activity = []
    if rest_id:
        tj = _x_gql(s, jar, H, _X_QID_TWEETS, "UserTweets", {
            "userId": rest_id, "count": 20, "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": False,
            "withVoice": True, "withV2Timeline": True,
        }, _X_FEAT_TWEETS)
        if tj:
            activity = _x_parse_tweets(tj, screen)
    if not activity and not legacy:
        return None
    return _src("x", "ok", handle=screen, profile_url=f"https://x.com/{screen}",
                display_name=name, headline=_clean(desc, 160), avatar=avatar,
                location=_clean(loc, 80) or None, stats=stats, activity=activity)


def _x_syndication(handle):
    """Public syndication endpoint. No login, but datacenter IPs usually get
    429'd, so from a server this mostly returns needs_connection."""
    h = handle
    prof = f"https://x.com/{h}"
    url = ("https://syndication.twitter.com/srv/timeline-profile/screen-name/"
           f"{h}?showReplies=false")
    try:
        r = _get(url, headers={"accept": "text/html,application/xhtml+xml"})
    except Exception as e:
        return _src("x", "needs_connection", handle=h, profile_url=prof,
                    note=f"X public endpoint did not respond ({type(e).__name__}).")
    if r.status_code != 200 or "__NEXT_DATA__" not in r.text:
        return _src("x", "needs_connection", handle=h, profile_url=prof,
                    note=("X locked this down for public reads. Connect an X "
                          "session (X_PROFILE_DIR) for live data."))
    try:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        blob = json.loads(m.group(1))
        page = blob["props"]["pageProps"]
        entries = (page.get("timeline", {}) or {}).get("entries", []) or []
    except Exception:
        return _src("x", "needs_connection", handle=h, profile_url=prof,
                    note="X response could not be parsed. Try a connected session.")
    name = headline = avatar = None
    stats, activity = [], []
    for e in entries:
        tw = (e.get("content") or {}).get("tweet") if isinstance(e.get("content"), dict) else None
        if not isinstance(tw, dict):
            continue
        u = tw.get("user") or {}
        if not name and u:
            name = u.get("name")
            headline = u.get("description")
            avatar = (u.get("profile_image_url_https") or "").replace("_normal", "")
            if u.get("followers_count") is not None:
                stats = [{"label": "Followers", "value": _human(u["followers_count"])}]
        text = tw.get("full_text") or tw.get("text")
        if not text:
            continue
        created = tw.get("created_at")
        epoch = None
        if created:
            try:
                epoch = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y").timestamp()
            except Exception:
                epoch = None
        activity.append({
            "kind": "post", "text": _clean(text),
            "url": f"https://x.com/{h}/status/{tw.get('id_str') or tw.get('id')}",
            "ts": _iso(epoch) if epoch else None, "ago": _ago(epoch) if epoch else "",
            "where": None,
            "engagement": [
                {"label": "likes", "value": _human(tw.get("favorite_count", 0))},
                {"label": "reposts", "value": _human(tw.get("retweet_count", 0))},
            ],
        })
        if len(activity) >= MAX_ACTIVITY:
            break
    if not activity and not name:
        return _src("x", "needs_connection", handle=h, profile_url=prof,
                    note="No public posts readable. A connected session is needed.")
    return _src("x", "ok", handle=h, profile_url=prof,
                display_name=name or f"@{h}", headline=_clean(headline, 160),
                avatar=avatar or None, stats=stats, activity=activity)


def _x(handle):
    """X / Twitter. Authenticated GraphQL when a session is connected, else the
    public syndication endpoint. A source failing never breaks the card."""
    h = handle.strip().lstrip("@").split("/")[-1]
    if not h:
        return _src("x", "not_found", handle=handle)
    jar = _x_jar()
    if jar:
        try:
            block = _x_authed(h, jar)
        except Exception:
            block = None
        if block:
            return block
    syn = _x_syndication(h)
    if syn.get("status") == "ok" or not jar:
        return syn
    # Session was present but the live read failed and public is blocked: be
    # honest that the cookie likely needs a refresh rather than blaming the IP.
    return _src("x", "error", handle=h, profile_url=f"https://x.com/{h}",
                note=("X session did not return data. The cookie may be stale or "
                      "X rotated its API. Re-log into X in that Chrome profile, "
                      "then retry. At scale this needs a warmed account pool + "
                      "proxy rotation (Phase 2)."))


# ── GitHub adapter (public REST API, no login) ──────────────────────────────
# The most dev-native channel and the one source that reads live from any IP
# with zero credentials. Unauthenticated is 60 reads/hour; a free read-only
# GITHUB_TOKEN lifts that to 5,000. Profile + recent public events = who they
# are plus what they shipped most recently.
def _gh_headers():
    """Standard GitHub REST headers, plus Bearer auth when a free read-only
    GITHUB_TOKEN is set (lifts the rate limit from 60 to 5,000 reads/hour)."""
    hdr = {"Accept": "application/vnd.github+json",
           "User-Agent": "gtmstack-signals/0.1",
           "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    return hdr


def _gh_epoch(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def _gh_event(ev):
    """Turn a GitHub public event into (kind, human text, url)."""
    t = ev.get("type") or ""
    repo = (ev.get("repo") or {}).get("name") or ""
    p = ev.get("payload") or {}
    repo_url = f"https://github.com/{repo}" if repo else "https://github.com"
    if t == "PushEvent":
        commits = p.get("commits") or []
        n = p.get("size") or len(commits)
        msg = (commits[-1].get("message") if commits else "") or ""
        first = msg.split("\n")[0]
        text = (f"Pushed {n} commit{'' if n == 1 else 's'} to {repo}"
                if n else f"Pushed to {repo}")
        return "commit", (f"{text}: {first}" if first else text), repo_url
    if t == "PullRequestEvent":
        pr = p.get("pull_request") or {}
        act = (p.get("action") or "updated").capitalize()
        return "pr", f"{act} a pull request in {repo}: {pr.get('title', '')}", \
            pr.get("html_url") or repo_url
    if t == "IssuesEvent":
        iss = p.get("issue") or {}
        act = (p.get("action") or "updated").capitalize()
        return "issue", f"{act} an issue in {repo}: {iss.get('title', '')}", \
            iss.get("html_url") or repo_url
    if t == "IssueCommentEvent":
        iss = p.get("issue") or {}
        com = p.get("comment") or {}
        return "comment", f"Commented in {repo} on “{iss.get('title', '')}”: " \
            f"{com.get('body', '')}", com.get("html_url") or repo_url
    if t == "PullRequestReviewEvent" or t == "PullRequestReviewCommentEvent":
        pr = p.get("pull_request") or {}
        return "comment", f"Reviewed a pull request in {repo}: {pr.get('title', '')}", \
            pr.get("html_url") or repo_url
    if t == "WatchEvent":
        return "star", f"Starred {repo}", repo_url
    if t == "ForkEvent":
        return "fork", f"Forked {repo}", repo_url
    if t == "CreateEvent":
        rt = p.get("ref_type") or "repository"
        return "create", f"Created {rt} in {repo}", repo_url
    if t == "ReleaseEvent":
        rel = p.get("release") or {}
        return "release", f"Released {rel.get('tag_name', '')} in {repo}", \
            rel.get("html_url") or repo_url
    if t == "PublicEvent":
        return "post", f"Open-sourced {repo}", repo_url
    label = t.replace("Event", "") or "Activity"
    return "post", f"{label} in {repo}" if repo else label, repo_url


def _github(handle):
    h = handle.strip().lstrip("@").rstrip("/").split("/")[-1]
    if not h:
        return _src("github", "not_found", handle=handle)
    prof = f"https://github.com/{h}"
    hdr = _gh_headers()
    try:
        r = _get(f"https://api.github.com/users/{h}", headers=hdr)
    except Exception as e:
        return _src("github", "error", handle=h, profile_url=prof,
                    note=f"GitHub did not respond ({type(e).__name__}).")
    if r.status_code == 404:
        return _src("github", "not_found", handle=h, profile_url=prof)
    if r.status_code == 403:
        return _src("github", "needs_connection", handle=h, profile_url=prof,
                    note=("GitHub rate limit hit. Add a free read-only GITHUB_TOKEN "
                          "to lift it to 5,000 reads/hour."))
    if r.status_code != 200:
        return _src("github", "error", handle=h, profile_url=prof,
                    note=f"GitHub returned HTTP {r.status_code}.")
    try:
        d = r.json()
    except Exception:
        return _src("github", "error", handle=h, profile_url=prof,
                    note="GitHub response could not be parsed.")
    if not isinstance(d, dict) or not d.get("login"):
        return _src("github", "not_found", handle=h, profile_url=prof)

    stats = []
    if d.get("followers") is not None:
        stats.append({"label": "Followers", "value": _human(d["followers"])})
    if d.get("public_repos") is not None:
        stats.append({"label": "Repos", "value": _human(d["public_repos"])})
    if d.get("created_at"):
        stats.append({"label": "Joined",
                      "value": _ago(_gh_epoch(d["created_at"])).replace(" ago", "")})

    activity = []
    try:
        er = _get(f"https://api.github.com/users/{h}/events/public?per_page=30", headers=hdr)
        events = er.json() if er.status_code == 200 else []
    except Exception:
        events = []
    seen = set()
    for ev in events if isinstance(events, list) else []:
        kind, text, url = _gh_event(ev)
        if not text:
            continue
        sig = (kind, (ev.get("repo") or {}).get("name"), text[:60])
        if sig in seen:
            continue
        seen.add(sig)
        epoch = _gh_epoch(ev.get("created_at"))
        activity.append({
            "kind": kind,
            "text": _clean(text),
            "url": url,
            "ts": _iso(epoch) if epoch else None,
            "ago": _ago(epoch) if epoch else "",
            "where": (ev.get("repo") or {}).get("name"),
            "engagement": [],
        })
        if len(activity) >= MAX_ACTIVITY:
            break

    headline = _clean(d.get("bio"), 160)
    if d.get("company"):
        co = d["company"].strip()
        headline = f"{headline} · {co}" if headline else co
    return _src("github", "ok", handle=h, profile_url=prof,
                display_name=d.get("name") or h,
                avatar=d.get("avatar_url"),
                headline=headline,
                location=d.get("location"),
                stats=stats, activity=activity)


# ── company-level adapters (unit = company) ─────────────────────────────────
# Same channels as a person, read at the organisation level. GitHub orgs are the
# zero-config live source (public org profile + recently pushed repos + public
# members), so a company lookup returns real data out of the box, same as a
# person. LinkedIn company pages need a session and degrade like person LinkedIn.
def _github_org(name):
    h = name.strip().lstrip("@").rstrip("/").split("/")[-1]
    if not h:
        return _src("github", "not_found", handle=name)
    prof = f"https://github.com/{h}"
    hdr = _gh_headers()
    try:
        r = _get(f"https://api.github.com/orgs/{h}", headers=hdr)
    except Exception as e:
        return _src("github", "error", handle=h, profile_url=prof,
                    note=f"GitHub did not respond ({type(e).__name__}).")
    if r.status_code == 404:
        return _github(h)   # not an org; it may be a personal account
    if r.status_code == 403:
        return _src("github", "needs_connection", handle=h, profile_url=prof,
                    note="GitHub rate limit hit. Add a free read-only GITHUB_TOKEN.")
    if r.status_code != 200:
        return _src("github", "error", handle=h, profile_url=prof,
                    note=f"GitHub returned HTTP {r.status_code}.")
    try:
        d = r.json()
    except Exception:
        return _src("github", "error", handle=h, profile_url=prof,
                    note="GitHub response could not be parsed.")
    stats = []
    if d.get("followers") is not None:
        stats.append({"label": "Followers", "value": _human(d["followers"])})
    if d.get("public_repos") is not None:
        stats.append({"label": "Repos", "value": _human(d["public_repos"])})
    if d.get("created_at"):
        stats.append({"label": "Joined",
                      "value": _ago(_gh_epoch(d["created_at"])).replace(" ago", "")})
    activity = []
    try:
        rr = _get(f"https://api.github.com/orgs/{h}/repos?sort=pushed&per_page=10",
                  headers=hdr)
        repos = rr.json() if rr.status_code == 200 else []
    except Exception:
        repos = []
    for repo in repos if isinstance(repos, list) else []:
        ep = _gh_epoch(repo.get("pushed_at"))
        desc = _clean(repo.get("description"), 140)
        activity.append({
            "kind": "commit",
            "text": (repo.get("name") or "") + (f": {desc}" if desc else ""),
            "url": repo.get("html_url"),
            "ts": _iso(ep) if ep else None, "ago": _ago(ep) if ep else "",
            "where": repo.get("language"),
            "engagement": [
                {"label": "stars", "value": _human(repo.get("stargazers_count", 0))},
                {"label": "forks", "value": _human(repo.get("forks_count", 0))}],
        })
        if len(activity) >= MAX_ACTIVITY:
            break
    return _src("github", "ok", handle=h, profile_url=prof,
                display_name=d.get("name") or h, avatar=d.get("avatar_url"),
                headline=_clean(d.get("description"), 160), location=d.get("location"),
                stats=stats, activity=activity)


def _github_org_people(name, limit=12):
    """Public members of a GitHub org -> the people who work there. Lists logins
    + avatars; unauthenticated this only returns members who made membership
    public, and 403s degrade to an empty list."""
    h = name.strip().lstrip("@").rstrip("/").split("/")[-1]
    if not h:
        return []
    try:
        r = _get(f"https://api.github.com/orgs/{h}/members?per_page={limit}",
                 headers=_gh_headers())
        members = r.json() if r.status_code == 200 else []
    except Exception:
        members = []
    out = []
    for m in members if isinstance(members, list) else []:
        if not m.get("login"):
            continue
        out.append({
            "platform": "github", "handle": m["login"], "display_name": m["login"],
            "avatar": m.get("avatar_url"), "profile_url": m.get("html_url"),
            "headline": None,
        })
    return out


# Display-name slug -> LinkedIn universalName, ONLY for brands whose page slug
# diverges from the obvious slugify. The slugify already resolves cashfree,
# razorpay, payu, easebuzz; add an entry here when a brand's real universalName
# differs (verify it returns 200 before trusting it).
_LI_SLUG = {}


def _linkedin_company(name):
    """Company page via Voyager. Best-effort: with a checkpointed cookie this
    degrades cleanly, same as person LinkedIn."""
    creds = _li_creds()
    h = re.sub(r"^/?(company/)", "", name.strip(), flags=re.I).rstrip("/").lstrip("@").split("/")[-1]
    # Slugify a display name to a universalName guess: "PayU" -> "payu",
    # "Cashfree Payments" -> "cashfree-payments". A small override map fixes the
    # brands whose slug diverges from the obvious slugify.
    h = re.sub(r"\s+", "-", h).lower()
    h = _LI_SLUG.get(h, h)
    prof = f"https://www.linkedin.com/company/{h}/"
    if not creds:
        return _src("linkedin", "needs_connection", handle=h, profile_url=prof,
                    note="Add a LinkedIn session to read company pages.")
    jar = _li_jar() or dict(creds)
    jsess = (jar.get("JSESSIONID") or creds["JSESSIONID"]).strip('"')
    ck = dict(jar)
    ck["JSESSIONID"] = f'"{jsess}"'
    s = _browser_session()
    H = _li_headers(jsess)
    url = ("https://www.linkedin.com/voyager/api/organization/companies"
           f"?decorationId=com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12"
           f"&q=universalName&universalName={requests.utils.quote(h, safe='')}")
    try:
        r = s.get(url, headers={**H, "referer": prof}, cookies=ck,
                  timeout=HTTP_TIMEOUT, allow_redirects=False)
    except Exception as e:
        return _src("linkedin", "error", handle=h, profile_url=prof,
                    note=f"LinkedIn did not respond ({type(e).__name__}).")
    if r.status_code in (301, 302, 303, 307, 308):
        return _src("linkedin", "error", handle=h, profile_url=prof,
                    note=("LinkedIn bounced this session to a checkpoint. Open "
                          "LinkedIn in that Chrome profile, clear any prompt, then "
                          "retry. At scale this needs a warmed pool + proxies (Phase 2)."))
    if r.status_code in (401, 403):
        return _src("linkedin", "error", handle=h, profile_url=prof,
                    note="LinkedIn session expired or blocked. Refresh the cookie.")
    if r.status_code != 200:
        return _src("linkedin", "needs_connection", handle=h, profile_url=prof,
                    note=f"LinkedIn returned HTTP {r.status_code}.")
    # Voyager returns LinkedIn's *normalized* shape: data.*elements points at the
    # primary company URN, the entities live in included[], and followerCount sits
    # in a SEPARATE FollowingInfo entity referenced by the company's *followingInfo
    # URN. Resolve by URN, with a universalName match as the fallback.
    try:
        j = r.json() or {}
    except Exception:
        j = {}
    inc = j.get("included") or []
    by_urn = {e.get("entityUrn"): e for e in inc if e.get("entityUrn")}
    prim = (j.get("data") or {}).get("*elements") or (j.get("data") or {}).get("elements") or []
    c = by_urn.get(prim[0]) if prim else None
    if not c:
        c = next((e for e in inc
                  if (e.get("$type") or "").endswith("organization.Company")
                  and (e.get("universalName") or "").lower() == h.lower()), None)
    if not c:
        return _src("linkedin", "not_found", handle=h, profile_url=prof)
    fi = by_urn.get(c.get("*followingInfo")) or {}
    followers = fi.get("followerCount")
    h = c.get("universalName") or h
    prof = f"https://www.linkedin.com/company/{h}/"
    stats = []
    if followers:
        stats.append({"label": "Followers", "value": _human(followers),
                      "raw": int(followers)})
    cnt = c.get("staffCount") or (c.get("staffCountRange") or {}).get("start")
    if cnt:
        stats.append({"label": "Staff", "value": _human(cnt), "raw": int(cnt)})
    return _src("linkedin", "ok", handle=h, profile_url=prof,
                display_name=c.get("name") or h,
                headline=_clean(c.get("tagline") or c.get("description"), 160),
                stats=stats, activity=[])


_LI_FIRMO_CACHE = {}          # slug-ish key -> (epoch, result)
_LI_FIRMO_TTL = 6 * 3600      # followers move slowly; 6h keeps repeat runs free


def linkedin_firmographics(name):
    """Best-effort LinkedIn audience read for a brand via the user's own session:
    follower count (primary) plus staff count (fallback). Never raises; degrades
    to None on a checkpointed or absent cookie so the comparison still renders.
    Compliant company-page read, not a mention/engager scrape. Cached 6h so a
    repeated comparison doesn't re-hit LinkedIn (gentler on the personal session)."""
    key = (name or "").strip().lower()
    hit = _LI_FIRMO_CACHE.get(key)
    if hit and (time.time() - hit[0]) < _LI_FIRMO_TTL:
        return hit[1]
    try:
        src = _linkedin_company(name)
    except Exception as e:
        return {"followers": None, "followers_h": None, "staff": None,
                "staff_h": None, "status": "error",
                "note": f"LinkedIn read failed ({type(e).__name__})."}
    out = {"followers": None, "followers_h": None, "staff": None, "staff_h": None,
           "status": src.get("status"), "note": src.get("note"),
           "profile_url": src.get("profile_url")}
    for st in src.get("stats") or []:
        if st.get("label") == "Followers":
            out["followers"], out["followers_h"] = st.get("raw"), st.get("value")
        elif st.get("label") == "Staff":
            out["staff"], out["staff_h"] = st.get("raw"), st.get("value")
    # Cache only a clean read; let transient checkpoints/404s retry next run.
    if out["status"] == "ok":
        _LI_FIRMO_CACHE[key] = (time.time(), out)
    return out


def _reddit_sub(name):
    """Company-level Reddit = the eponymous subreddit, when one exists."""
    h = re.sub(r"^/?r/", "", name.strip(), flags=re.I).strip().lstrip("@").split("/")[-1]
    if not h:
        return _src("reddit", "not_found", handle=name)
    prof = f"https://www.reddit.com/r/{h}"
    token = _reddit_token()
    code, about = _reddit_fetch(f"/r/{h}/about.json?raw_json=1", token)
    if code == 404:
        return _src("reddit", "not_found", handle=h, profile_url=prof)
    if about is None:
        return _src("reddit", "needs_connection" if not token else "error",
                    handle=h, profile_url=prof,
                    note=("Reddit blocked this lookup. Add a Reddit app "
                          "(REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET) to enable reads."
                          if not token else
                          "Reddit connected but returned no data. Retry shortly."))
    d = about.get("data", {})
    if not d or d.get("dist") == 0:
        return _src("reddit", "not_found", handle=h, profile_url=prof)
    stats = []
    if d.get("subscribers") is not None:
        stats.append({"label": "Members", "value": _human(d["subscribers"])})
    _, feed = _reddit_fetch(f"/r/{h}/new.json?limit=10&raw_json=1", token)
    children = (feed or {}).get("data", {}).get("children", []) if feed else []
    activity = []
    for ch in children:
        c = ch.get("data", {})
        activity.append({
            "kind": "post", "text": _clean(c.get("title")),
            "url": "https://www.reddit.com" + (c.get("permalink") or ""),
            "ts": _iso(c.get("created_utc")), "ago": _ago(c.get("created_utc")),
            "where": f"u/{c.get('author')}" if c.get("author") else None,
            "engagement": [{"label": "score", "value": _human(c.get("score", 0))},
                           {"label": "comments", "value": _human(c.get("num_comments", 0))}],
        })
        if len(activity) >= MAX_ACTIVITY:
            break
    return _src("reddit", "ok", handle=h, profile_url=prof, display_name=f"r/{h}",
                headline=_clean(d.get("public_description"), 160),
                avatar=(d.get("icon_img") or d.get("community_icon") or "").split("?")[0] or None,
                stats=stats, activity=activity)


# ── keyword / topic adapters (unit = keyword): a live mentions feed ─────────
# What is being said about a topic right now across the dev-native channels.
# GitHub repo search and X search read live; Reddit search needs a Reddit app.
def _github_search(q):
    qq = (q or "").strip()
    if not qq:
        return _src("github", "not_found", handle=q)
    url = ("https://api.github.com/search/repositories?q="
           f"{requests.utils.quote(qq)}&sort=updated&order=desc&per_page=10")
    try:
        r = _get(url, headers=_gh_headers())
    except Exception as e:
        return _src("github", "error", handle=qq,
                    note=f"GitHub did not respond ({type(e).__name__}).")
    if r.status_code == 403:
        return _src("github", "needs_connection", handle=qq,
                    note="GitHub search rate limit hit. Add a free GITHUB_TOKEN.")
    if r.status_code != 200:
        return _src("github", "error", handle=qq,
                    note=f"GitHub returned HTTP {r.status_code}.")
    items = (r.json() or {}).get("items", []) if r.ok else []
    activity = []
    for repo in items:
        ep = _gh_epoch(repo.get("pushed_at") or repo.get("updated_at"))
        desc = _clean(repo.get("description"), 140)
        activity.append({
            "kind": "create",
            "text": (repo.get("full_name") or "") + (f": {desc}" if desc else ""),
            "url": repo.get("html_url"),
            "ts": _iso(ep) if ep else None, "ago": _ago(ep) if ep else "",
            "where": repo.get("language"),
            "author": (repo.get("owner") or {}).get("login"),
            "engagement": [{"label": "stars", "value": _human(repo.get("stargazers_count", 0))}],
        })
        if len(activity) >= MAX_ACTIVITY:
            break
    return _src("github", "ok", handle=qq, display_name=f"GitHub · “{qq}”",
                activity=activity)


# X SearchTimeline query ids (rotate per deploy, same self-heal as the others;
# _x_discover_qids() supplies the live id first, these are the fallback).
_X_QID_SEARCH = ("-TFXKoMnMTKdEXcCn-eahw", "nKAncKPF1fV1xltvF3UUlw",
                 "KI9jCXUx3Ymt-hDKLOZb9Q", "UN1i3zUiCWa-6r-Uaho4fw",
                 "gkjsKepM6gl_HmFWoWKfgg", "7jT5GT59P8IFjgxwqnEdQw")


def _x_search(q):
    jar = _x_jar()
    if not jar:
        return _src("x", "needs_connection", handle=q,
                    note="Add an X session (X_PROFILE_DIR) for live search.")
    s = _browser_session()
    H = _x_headers(jar["ct0"])
    j = _x_gql(s, jar, H, _X_QID_SEARCH, "SearchTimeline",
               {"rawQuery": q, "count": 20, "querySource": "typed_query",
                "product": "Latest"}, _X_FEAT_TWEETS, method="POST")
    if not j:
        return _src("x", "error", handle=q,
                    note="X search did not return data. The session may need a refresh.")
    instr = (((((j.get("data") or {}).get("search_by_raw_query") or {})
               .get("search_timeline") or {}).get("timeline") or {})
             .get("instructions", []))
    activity = []
    for ins in instr or []:
        for ent in ins.get("entries", []) or []:
            if not str(ent.get("entryId", "")).startswith("tweet-"):
                continue
            tr = ((((ent.get("content") or {}).get("itemContent") or {})
                   .get("tweet_results") or {}).get("result"))
            tw = _x_tweet_node(tr)
            if not tw:
                continue
            leg = tw.get("legacy") or {}
            note = ((((tw.get("note_tweet") or {}).get("note_tweet_results") or {})
                     .get("result")) or {})
            text = note.get("text") or leg.get("full_text") or leg.get("text")
            if not text:
                continue
            uc = (((tw.get("core") or {}).get("user_results") or {}).get("result") or {})
            author = ((uc.get("legacy") or {}).get("screen_name")
                      or (uc.get("core") or {}).get("screen_name"))
            tid = leg.get("id_str") or tw.get("rest_id")
            ep = None
            cr = leg.get("created_at")
            if cr:
                try:
                    ep = datetime.strptime(cr, "%a %b %d %H:%M:%S %z %Y").timestamp()
                except Exception:
                    ep = None
            activity.append({
                "kind": "post", "text": _clean(text),
                "url": f"https://x.com/{author or 'i'}/status/{tid}",
                "ts": _iso(ep) if ep else None, "ago": _ago(ep) if ep else "",
                "where": None, "author": author,
                "engagement": [
                    {"label": "likes", "value": _human(leg.get("favorite_count", 0))},
                    {"label": "reposts", "value": _human(leg.get("retweet_count", 0))}],
            })
            if len(activity) >= MAX_ACTIVITY:
                break
        if len(activity) >= MAX_ACTIVITY:
            break
    return _src("x", "ok", handle=q, display_name=f"X · “{q}”", activity=activity)


# arctic-shift: a no-auth Reddit source that is CURRENT (its index is live, unlike
# PullPush which froze in mid-2025). Reddit's own .json 403s from most IPs and the
# OAuth path needs an app, so this is the keyless fresh path. Its full-text
# `query` search is intermittently "under maintenance", but the plain recent-posts
# feed (no query) stays up, so we pull the newest posts per sub and filter for the
# keyword ourselves. That trades recall for freshness, which is what a monitor wants.
_ARCTIC = "https://arctic-shift.photon-reddit.com/api"
_ARCTIC_SUBS = ("developersIndia", "IndiaStartups", "indianstartups", "IndiaBusiness",
                "india", "StartUpIndia", "smallbusiness", "ecommerce", "shopify", "SaaS",
                "fintech", "Entrepreneur", "webdev", "personalfinanceindia", "IndianStreetBets",
                "Business", "Payments", "EcommerceMarketing", "SideProject", "IndianStockMarket",
                "juststart", "growmybusiness", "kuvera", "IndiaTech", "developersIndia")


def _arctic_recent(sub, limit=100, before=None):
    """Newest posts in a subreddit (no query param, which is the endpoint that
    stays live; arctic caps limit at 100). `before` (epoch) pages further back.
    Returns raw post dicts, newest first."""
    url = (f"{_ARCTIC}/posts/search?subreddit={requests.utils.quote(sub)}"
           f"&limit={min(limit,100)}&sort=desc")
    if before:
        url += f"&before={int(before)}"
    for _ in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=18)
            if r.status_code in (429, 500, 502, 503):
                continue
            r.raise_for_status()
            return r.json().get("data", []) or []
        except Exception:
            continue
    return []


def _arctic_sub_scan(sub, pages=3):
    """Recent posts for one sub across a few pages (100 each, `before`-paginated)."""
    posts, before = [], None
    for _ in range(pages):
        data = _arctic_recent(sub, before=before)
        if not data:
            break
        posts += data
        try:
            before = float(data[-1].get("created_utc"))
        except Exception:
            break
    return posts


def _reddit_arctic(q, cap=50, pages=2):
    """Fresh keyword mentions: scan recent posts across the watched subs IN PARALLEL
    (arctic's query search is down, so we filter client-side) and keep the ones whose
    title or body contains the query. Parallel + paged so a rare phrase still fills up
    without a minutes-long serial crawl. Newest-first; recall is bounded by how often
    the phrase actually appears recently (the official OAuth API is the way to 50)."""
    ql = (q or "").lower().strip()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(_ARCTIC_SUBS)) as ex:
        batches = list(ex.map(lambda s: _arctic_sub_scan(s, pages), _ARCTIC_SUBS))
    out, seen = [], set()
    for posts in batches:
        for d in posts:
            title = _clean(d.get("title"))
            if not title:
                continue
            hay = (title + " " + (d.get("selftext") or "")).lower()
            if ql and ql not in hay:
                continue
            pid = d.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            permalink = d.get("permalink") or ""
            out.append({
                "kind": "post", "text": title,
                "url": ("https://www.reddit.com" + permalink) if permalink
                       else f"https://www.reddit.com/r/{d.get('subreddit','')}",
                "ts": _iso(d.get("created_utc")), "ago": _ago(d.get("created_utc")),
                "where": f"r/{d.get('subreddit')}" if d.get("subreddit") else None,
                "author": d.get("author"),
                "engagement": [{"label": "score", "value": _human(d.get("score", 0))},
                               {"label": "comments", "value": _human(d.get("num_comments", 0))}],
            })
    out.sort(key=lambda a: a.get("ts") or "", reverse=True)
    return out[:cap]


# PullPush (the live Pushshift successor): a keyless global Reddit search. Unlike
# arctic-shift it needs no per-subreddit loop and does not 403 from datacenter IPs,
# so it is the primary no-auth fallback when the official OAuth app is not set.
_PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"


def _reddit_pullpush(q, cap=25):
    url = (f"{_PULLPUSH}?q={requests.utils.quote(q)}&size={cap}"
           f"&sort=desc&sort_type=created_utc")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        if not r.ok:
            return []
        data = r.json().get("data", []) or []
    except Exception:
        return []
    out, seen = [], set()
    for d in data:
        title = _clean(d.get("title"))
        pid = d.get("id") or d.get("permalink")
        if not title or pid in seen:
            continue
        seen.add(pid)
        permalink = d.get("permalink") or ""
        url_ = ("https://www.reddit.com" + permalink) if permalink.startswith("/") \
            else (permalink or f"https://www.reddit.com/r/{d.get('subreddit','')}")
        out.append({
            "kind": "post", "text": title, "url": url_,
            "ts": _iso(d.get("created_utc")), "ago": _ago(d.get("created_utc")),
            "where": f"r/{d.get('subreddit')}" if d.get("subreddit") else None,
            "author": d.get("author"),
            "engagement": [{"label": "score", "value": _human(d.get("score", 0))},
                           {"label": "comments", "value": _human(d.get("num_comments", 0))}],
        })
        if len(out) >= cap:
            break
    out.sort(key=lambda a: a.get("ts") or "", reverse=True)
    return out


_REDDIT_KW_CAP = 50   # keyword feed pulls up to this many mentions per source


def _reddit_search(q):
    token = _reddit_token()
    # official/public search: sort=new for recency, up to the keyword cap
    _, res = _reddit_fetch(
        f"/search.json?q={requests.utils.quote(q)}&sort=new&limit={_REDDIT_KW_CAP}&raw_json=1", token)
    children = (res or {}).get("data", {}).get("children", []) if res else []
    activity = []
    for ch in children:
        c = ch.get("data", {})
        activity.append({
            "kind": "post", "text": _clean(c.get("title")),
            "url": "https://www.reddit.com" + (c.get("permalink") or ""),
            "ts": _iso(c.get("created_utc")), "ago": _ago(c.get("created_utc")),
            "where": f"r/{c.get('subreddit')}" if c.get("subreddit") else None,
            "author": c.get("author"),
            "engagement": [{"label": "score", "value": _human(c.get("score", 0))},
                           {"label": "comments", "value": _human(c.get("num_comments", 0))}],
        })
        if len(activity) >= _REDDIT_KW_CAP:
            break
    if activity:
        return _src("reddit", "ok", handle=q, display_name=f"Reddit · “{q}”",
                    activity=activity)
    # Primary blocked or empty: keyless fallbacks. arctic-shift first (its index is
    # CURRENT, so results are recent), then PullPush (frozen mid-2025, stale, last resort).
    for name, fn in (("arctic-shift", _reddit_arctic), ("pullpush", _reddit_pullpush)):
        activity = fn(q)
        if activity:
            return _src("reddit", "ok", handle=q, display_name=f"Reddit · “{q}”",
                        source_note=name, activity=activity)
    return _src("reddit", "needs_connection" if not token else "error", handle=q,
                note=("Reddit search is blocked and the no-auth archives were empty. "
                      "Add REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET for the official path."))


# ── Review-site + Quora keyword adapters (thin wrappers over _reviews) ───────
# These make TrustPilot / Quora first-class Signals keyword sources so a lookup
# and the daily report can include them. The query is treated as a BRAND for the
# review sites (they are brand-keyed), and as a search phrase for Quora. All reads
# go through _reviews, which routes through the _fetch transport.

def _trustpilot_search(q):
    try:
        from _reviews import _trustpilot_reviews
        rows = _trustpilot_reviews(q)          # q as brand
    except Exception:
        rows = []
    if not rows:
        return _src("trustpilot", "not_found", handle=q,
                    display_name=f"TrustPilot · {q}",
                    note="No recent TrustPilot reviews for this brand, or brand not mapped.")
    return _src("trustpilot", "ok", handle=q, display_name=f"TrustPilot · {q}",
                activity=rows[:MAX_ACTIVITY])


def _capterra_search(q):
    try:
        from _reviews import _capterra_reviews
        rows = _capterra_reviews(q)
    except Exception:
        rows = []
    if not rows:
        return _src("capterra", "needs_connection", handle=q,
                    display_name=f"Capterra · {q}",
                    note="Capterra needs a curated numeric product id and often blocks. Gated.")
    return _src("capterra", "ok", handle=q, display_name=f"Capterra · {q}",
                activity=rows[:MAX_ACTIVITY])


def _quora_search(q):
    try:
        from _reviews import _quora_posts
        rows = _quora_posts(q)
    except Exception:
        rows = []
    if not rows:
        return _src("quora", "needs_connection", handle=q, display_name=f"Quora · {q}",
                    note=("Quora keyword search is login-walled. Add curated question "
                          "URLs to the group's quora_questions for reliable reads."))
    return _src("quora", "ok", handle=q, display_name=f"Quora · {q}",
                activity=rows[:MAX_ACTIVITY])


def _g2_search(q):
    """G2 is licensed-API only (decided). Absent until G2_API_KEY is set; never
    scraped. Honest needs_connection so the UI does not show a fake empty."""
    if not os.getenv("G2_API_KEY"):
        return _src("g2", "needs_connection", handle=q, display_name=f"G2 · {q}",
                    note="G2 needs a licensed data API key (G2_API_KEY). Not scraped.")
    # licensed-API adapter would go here when the key is provisioned
    return _src("g2", "not_found", handle=q, display_name=f"G2 · {q}",
                note="G2 API key set but no adapter wired yet.")


# ── YouTube adapter (keyless) ───────────────────────────────────────────────
# No API key: we read the same HTML a browser gets and parse the embedded
# ytInitialData JSON. A consent cookie keeps EU / datacenter IPs from bouncing
# to the consent wall; if YouTube reshapes its markup or blocks the IP, every
# path degrades to needs_connection rather than breaking the card.
YT_COOKIE = os.getenv("YT_COOKIE", "CONSENT=YES+1; SOCS=CAI; PREF=hl=en&gl=US")


def _yt_get(url):
    return _get(url, headers={"cookie": YT_COOKIE})


def _yt_json(html, marker="ytInitialData"):
    """Brace-match the JSON object assigned to `marker` in a YouTube page."""
    if not html:
        return None
    i = html.find(marker)
    if i < 0:
        return None
    i = html.find("{", i)
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[i:j + 1])
                except Exception:
                    return None
    return None


def _yt_rel_epoch(text):
    """'2 weeks ago' / 'Streamed 3 hours ago' -> approximate epoch seconds."""
    if not text:
        return None
    m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)", text, re.I)
    if not m:
        return None
    mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400,
            "week": 604800, "month": 2592000, "year": 31536000}[m.group(2).lower()]
    return time.time() - int(m.group(1)) * mult


def _yt_text(node):
    """A YouTube text node -> plain string (simpleText or joined runs)."""
    if not isinstance(node, dict):
        return ""
    if node.get("simpleText"):
        return node["simpleText"]
    return "".join(r.get("text", "") for r in (node.get("runs") or []))


def _yt_thumb(node):
    thumbs = (node or {}).get("thumbnails") or []
    if not thumbs:
        return None
    url = thumbs[-1].get("url")
    return ("https:" + url) if url and url.startswith("//") else url


def _yt_video_item(vr):
    """A videoRenderer -> a normalized activity dict, or None."""
    vid = vr.get("videoId")
    title = _yt_text(vr.get("title"))
    if not vid or not title:
        return None
    when = _yt_text(vr.get("publishedTimeText"))
    ep = _yt_rel_epoch(when)
    author = (_yt_text(vr.get("ownerText")) or _yt_text(vr.get("longBylineText"))
              or None)
    eng = []
    vm = re.search(r"([\d.,]+[KMB]?)", _yt_text(vr.get("viewCountText")))
    if vm:
        eng.append({"label": "views", "value": vm.group(1)})
    return {
        "kind": "video", "text": _clean(title),
        "url": f"https://www.youtube.com/watch?v={vid}",
        "ts": _iso(ep) if ep else None, "ago": when or (_ago(ep) if ep else ""),
        "where": None, "author": author, "engagement": eng,
    }


def _yt_lockup_item(lvm):
    """A lockupViewModel (new channel-grid video) -> activity dict, or None."""
    vid = lvm.get("contentId")
    if not vid or lvm.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
        return None
    mvm = (lvm.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = (mvm.get("title") or {}).get("content")
    if not title:
        return None
    parts = []
    rows = (((mvm.get("metadata") or {}).get("contentMetadataViewModel") or {})
            .get("metadataRows") or [])
    for row in rows:
        for p in row.get("metadataParts", []) or []:
            t = (p.get("text") or {}).get("content")
            if t:
                parts.append(t)
    when = next((p for p in parts if "ago" in p.lower()), "")
    ep = _yt_rel_epoch(when)
    eng = []
    vm = re.search(r"([\d.,]+[KMB]?)", next((p for p in parts if "view" in p.lower()), ""))
    if vm:
        eng.append({"label": "views", "value": vm.group(1)})
    return {
        "kind": "video", "text": _clean(title),
        "url": f"https://www.youtube.com/watch?v={vid}",
        "ts": _iso(ep) if ep else None, "ago": when or (_ago(ep) if ep else ""),
        "where": None, "author": None, "engagement": eng,
    }


def _yt_search_items(data, kind):
    """Yield every renderer of `kind` from a search results page."""
    sections = ((((data or {}).get("contents") or {})
                 .get("twoColumnSearchResultsRenderer") or {})
                .get("primaryContents") or {}).get("sectionListRenderer") or {}
    for sec in sections.get("contents", []) or []:
        for it in (sec.get("itemSectionRenderer") or {}).get("contents", []) or []:
            if kind in it:
                yield it[kind]


def _yt_grid_videos(data):
    """Recent uploads from a channel page's rich grid."""
    out = []
    tabs = (((data or {}).get("contents") or {})
            .get("twoColumnBrowseResultsRenderer") or {}).get("tabs") or []
    for tab in tabs:
        grid = (((tab.get("tabRenderer") or {}).get("content") or {})
                .get("richGridRenderer"))
        if not grid:
            continue
        for it in grid.get("contents", []) or []:
            content = (it.get("richItemRenderer") or {}).get("content") or {}
            vr = content.get("videoRenderer")
            item = (_yt_video_item(vr) if vr
                    else _yt_lockup_item(content["lockupViewModel"])
                    if content.get("lockupViewModel") else None)
            if item:
                out.append(item)
            if len(out) >= MAX_ACTIVITY:
                return out
    return out


def _yt_channel_meta(data, html):
    """(name, channel_url, avatar, subs) from a channel page, or all None."""
    meta = (data.get("metadata") or {}).get("channelMetadataRenderer") or {}
    name = meta.get("title")
    if not name:
        return None, None, None, None
    url = meta.get("vanityChannelUrl") or meta.get("channelUrl")
    avatar = _yt_thumb(meta.get("avatar"))
    sm = re.search(r'"([\d.,]+[KMB]?)\s+subscribers"', html or "")
    return name, url, avatar, (sm.group(1) if sm else None)


def _yt_resolve_channel(query):
    """Top channelRenderer for a search -> {name, url, avatar, subs}, or None."""
    try:
        r = _yt_get("https://www.youtube.com/results?search_query="
                    f"{requests.utils.quote(query)}&sp=EgIQAg%3D%3D")  # channels only
        data = _yt_json(r.text if r.status_code == 200 else "")
    except Exception:
        return None
    for cr in _yt_search_items(data, "channelRenderer"):
        cid = cr.get("channelId")
        name = _yt_text(cr.get("title"))
        if not cid or not name:
            continue
        sub_txt = _yt_text(cr.get("subscriberCountText"))
        sm = re.search(r"([\d.,]+[KMB]?)", sub_txt)
        return {"name": name, "url": f"https://www.youtube.com/channel/{cid}",
                "avatar": _yt_thumb(cr.get("thumbnail")),
                "subs": sm.group(1) if (sm and "subscriber" in sub_txt.lower()) else None}
    return None


def _youtube(handle):
    """Channel footprint: resolve the handle / name to a channel and list its
    recent uploads. Tries the @handle page first, then falls back to search."""
    raw = (handle or "").strip()
    if not raw:
        return _src("youtube", "not_found", handle=handle)
    h = raw.lstrip("@").rstrip("/").split("/")[-1]
    slug = h if " " not in h else None
    data, html = None, ""
    if slug:
        try:
            r = _yt_get(f"https://www.youtube.com/@{requests.utils.quote(slug)}/videos")
            html = r.text if r.status_code == 200 else ""
            data = _yt_json(html)
        except Exception as e:
            return _src("youtube", "error", handle=h,
                        note=f"YouTube did not respond ({type(e).__name__}).")
    name, ch_url, avatar, subs = (_yt_channel_meta(data, html)
                                  if data else (None, None, None, None))
    if not name:                                   # handle did not resolve -> search
        ch = _yt_resolve_channel(raw)
        if not ch:
            return _src("youtube", "not_found", handle=h,
                        profile_url=f"https://www.youtube.com/@{slug}" if slug else None)
        name, ch_url, avatar, subs = ch["name"], ch["url"], ch["avatar"], ch["subs"]
        try:
            r = _yt_get(ch["url"].rstrip("/") + "/videos")
            data = _yt_json(r.text if r.status_code == 200 else "")
        except Exception:
            data = None
    videos = _yt_grid_videos(data) if data else []
    stats = [{"label": "Subscribers", "value": subs}] if subs else []
    return _src("youtube", "ok", handle=h,
                profile_url=ch_url or (f"https://www.youtube.com/@{slug}" if slug else None),
                display_name=name, avatar=avatar, stats=stats, activity=videos)


def _youtube_search(q):
    """Live YouTube mentions: most-recent videos matching the phrase."""
    qq = (q or "").strip()
    if not qq:
        return _src("youtube", "not_found", handle=q)
    try:
        # sp=CAI%3D sorts the search by upload date (freshest first)
        r = _yt_get("https://www.youtube.com/results?search_query="
                    f"{requests.utils.quote(qq)}&sp=CAI%3D")
    except Exception as e:
        return _src("youtube", "error", handle=qq,
                    note=f"YouTube did not respond ({type(e).__name__}).")
    if r.status_code != 200:
        return _src("youtube", "needs_connection", handle=qq,
                    note=f"YouTube returned HTTP {r.status_code}.")
    data = _yt_json(r.text)
    if not data:
        return _src("youtube", "needs_connection", handle=qq,
                    note="YouTube returned a consent or block page. Retry shortly.")
    activity = []
    for vr in _yt_search_items(data, "videoRenderer"):
        item = _yt_video_item(vr)
        if item:
            activity.append(item)
        if len(activity) >= MAX_ACTIVITY:
            break
    return _src("youtube", "ok", handle=qq, display_name=f"YouTube · “{qq}”",
                activity=activity)


# ── shared orchestration helpers ────────────────────────────────────────────
def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _latest_ts(blocks):
    latest = None
    for r in blocks:
        for a in r.get("activity", []) or []:
            if a.get("ts") and (latest is None or a["ts"] > latest):
                latest = a["ts"]
    return latest


def _company_base(query):
    """stripe.com / https://stripe.com/x -> stripe; leaves plain names alone."""
    base = re.sub(r"^https?://", "", (query or "").strip(), flags=re.I).split("/")[0]
    if "." in base:
        base = re.sub(r"\.(com|io|ai|co|org|net|dev|app|xyz|so|gg|sh)$", "",
                      base, flags=re.I)
        base = base.split(".")[-1]
    return base or query


# ── CSV serialisers (bulk export) ───────────────────────────────────────────
def to_csv(payload):
    """One lookup payload -> CSV text. Shape depends on the unit."""
    import csv
    import io
    unit = payload.get("unit")
    out = io.StringIO()
    w = csv.writer(out)
    if unit == "keyword":
        w.writerow(["platform", "author", "when", "text", "url"])
        for a in payload.get("feed", []):
            w.writerow([a.get("platform"), a.get("author") or "", a.get("ago") or "",
                        a.get("text") or "", a.get("url") or ""])
    elif unit == "company":
        w.writerow(["section", "platform", "handle", "name", "headline", "url", "status"])
        for s in payload.get("sources", []):
            w.writerow(["footprint", s.get("platform"), s.get("handle") or "",
                        s.get("display_name") or "", s.get("headline") or "",
                        s.get("profile_url") or "", s.get("status")])
        for p in payload.get("people", []):
            w.writerow(["people", p.get("platform"), p.get("handle") or "",
                        p.get("display_name") or "", "", p.get("profile_url") or "", "ok"])
    else:
        w.writerow(["platform", "handle", "name", "headline", "latest_post",
                    "latest_url", "status"])
        for s in payload.get("sources", []):
            acts = s.get("activity", []) or []
            top = acts[0] if acts else {}
            w.writerow([s.get("platform"), s.get("handle") or "",
                        s.get("display_name") or "", s.get("headline") or "",
                        top.get("text") or "", top.get("url") or "", s.get("status")])
    return out.getvalue()


def to_csv_bulk(items):
    """A bulk job's items -> one flat CSV with a leading query column."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["query", "platform", "handle", "name", "headline", "text", "url", "status"])
    for it in items:
        q = it.get("query")
        if it.get("error"):
            w.writerow([q, "", "", "", "", "", "", f"error: {it['error']}"])
            continue
        p = it.get("payload") or {}
        unit = p.get("unit")
        if unit == "keyword":
            for a in p.get("feed", []):
                w.writerow([q, a.get("platform"), a.get("author") or "", "", "",
                            a.get("text") or "", a.get("url") or "", "ok"])
        elif unit == "company":
            for s in p.get("sources", []):
                w.writerow([q, s.get("platform"), s.get("handle") or "",
                            s.get("display_name") or "", s.get("headline") or "", "",
                            s.get("profile_url") or "", s.get("status")])
            for pe in p.get("people", []):
                w.writerow([q, pe.get("platform"), pe.get("handle") or "",
                            pe.get("display_name") or "", "(employee)", "",
                            pe.get("profile_url") or "", "ok"])
        else:
            for s in p.get("sources", []):
                acts = s.get("activity", []) or []
                top = acts[0] if acts else {}
                w.writerow([q, s.get("platform"), s.get("handle") or "",
                            s.get("display_name") or "", s.get("headline") or "",
                            top.get("text") or "", top.get("url") or "", s.get("status")])
    return out.getvalue()


_ADAPTERS = {"github": _github, "reddit": _reddit, "linkedin": _linkedin,
             "x": _x, "youtube": _youtube}
_COMPANY_ADAPTERS = {"github": _github_org, "linkedin": _linkedin_company,
                     "x": _x, "reddit": _reddit_sub, "youtube": _youtube}
_KEYWORD_ADAPTERS = {"github": _github_search, "x": _x_search,
                     "reddit": _reddit_search, "youtube": _youtube_search,
                     "trustpilot": _trustpilot_search, "quora": _quora_search,
                     "capterra": _capterra_search, "g2": _g2_search}


# ── SQLite cache (real-time first, short TTL) ───────────────────────────────
def _db():
    conn = sqlite3.connect(_DB, timeout=10, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS sig "
                 "(k TEXT PRIMARY KEY, ts REAL, payload TEXT)")
    return conn


def _cache_key(unit, query, sources, handles):
    parts = [unit, query.strip().lower(), ",".join(sorted(sources))]
    for src in sorted(handles):
        if handles[src]:
            parts.append(f"{src}:{handles[src].strip().lower()}")
    return "|".join(parts)


def _cache_get(key):
    try:
        conn = _db()
        row = conn.execute("SELECT ts, payload FROM sig WHERE k=?", (key,)).fetchone()
        conn.close()
        if row and (time.time() - row[0]) < CACHE_TTL:
            return json.loads(row[1])
    except Exception:
        pass
    return None


def _cache_put(key, payload):
    try:
        conn = _db()
        conn.execute("INSERT OR REPLACE INTO sig (k, ts, payload) VALUES (?,?,?)",
                     (key, time.time(), json.dumps(payload)))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── orchestrator ────────────────────────────────────────────────────────────
# One public entry point. `unit` picks the lookup shape:
#   person  -> who someone is + what they did last across their own channels.
#   company -> the org's own footprint card + the people who work there.
#   keyword -> a live mentions feed: what is being said about a topic right now.
_COMPANY_SOURCES = ("github", "linkedin", "x", "reddit", "youtube")
_KEYWORD_SOURCES = ("github", "x", "reddit", "youtube")


def _resolve_sources(requested, default, registry):
    """Resolve a lookup's source list, honestly.

    If the caller passed nothing, use the unit default. If the caller passed an
    explicit list, honour exactly the known subset and report the rest as
    unknown; do NOT silently fall back to scanning everything when an unknown
    name filters the list to empty. That old behaviour turned a typo or an
    unregistered source (e.g. 'quora' before it is wired) into a full four-source
    scan, so a caller asking for one source got a different answer with no error.
    Returns (known_sources, unknown_sources)."""
    if not requested:
        return list(default), []
    known = [s for s in requested if s in registry]
    unknown = [s for s in requested if s not in registry]
    return known, unknown


def lookup(query, sources=None, handles=None, force=False, unit="person"):
    """
    unit     : 'person' (default) | 'company' | 'keyword'.
    query    : name / handle / email (person), name or domain (company),
               or the phrase to track (keyword).
    sources  : subset of the unit's source set. Defaults to all.
    handles  : optional per-platform overrides {'reddit': 'spez', ...} (person).
    force    : skip cache, pull fresh.
    Returns (payload, status_code).
    """
    if requests is None:
        return {"error": "The 'requests' package is required for Signals."}, 500
    u = (unit or "person").strip().lower()
    if u in ("company", "org", "organization"):
        return _lookup_company(query, sources, force)
    if u in ("keyword", "keywords", "topic", "search", "mentions"):
        return _lookup_keyword(query, sources, force)
    return _lookup_person(query, sources, handles, force)


def _lookup_person(query, sources=None, handles=None, force=False):
    query = (query or "").strip()
    if not query and not (handles and any(handles.values())):
        return {"error": "Enter a name, handle, or email to look up."}, 400

    sources, unknown = _resolve_sources(sources, ALL_SOURCES, _ADAPTERS)
    handles = {k: (v or "").strip() for k, v in (handles or {}).items()}

    key = _cache_key("person", query, sources, handles)
    if not force:
        cached = _cache_get(key)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached, 200

    results = []
    for src in unknown:
        results.append(_src(src, "needs_connection", handle=query,
                            note=f"'{src}' is not a registered person source."))
    for src in sources:
        ident = handles.get(src) or query
        try:
            results.append(_ADAPTERS[src](ident))
        except Exception as e:  # belt-and-suspenders: never break the card
            results.append(_src(src, "error", handle=ident,
                                note=f"Unexpected error ({type(e).__name__})."))

    found = [r for r in results if r["status"] == "ok"]
    latest = _latest_ts(found)

    payload = {
        "query": query,
        "unit": "person",
        "generated_at": _now_iso(),
        "cached": False,
        "sources": results,
        "summary": {
            "platforms_searched": len(results),
            "platforms_found": len(found),
            "latest_activity_at": latest,
            "latest_activity_ago": _ago(
                datetime.fromisoformat(latest).timestamp()) if latest else None,
        },
    }
    _cache_put(key, payload)
    return payload, 200


def _lookup_company(query, sources=None, force=False):
    """Footprint card per source + the people who work there. People come from
    the GitHub org member list (the zero-config people source); a source failing
    never breaks the card, same contract as person lookups."""
    query = (query or "").strip()
    if not query:
        return {"error": "Enter a company name or domain to look up."}, 400
    base = _company_base(query)
    sources, _unknown_co = _resolve_sources(sources, _COMPANY_SOURCES, _COMPANY_ADAPTERS)

    key = _cache_key("company", base, sources, {})
    if not force:
        cached = _cache_get(key)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached, 200

    results = []
    for src in sources:
        try:
            results.append(_COMPANY_ADAPTERS[src](base))
        except Exception as e:
            results.append(_src(src, "error", handle=base,
                                note=f"Unexpected error ({type(e).__name__})."))

    try:
        people = _github_org_people(base)
    except Exception:
        people = []

    found = [r for r in results if r["status"] == "ok"]
    latest = _latest_ts(found)

    payload = {
        "query": query,
        "unit": "company",
        "generated_at": _now_iso(),
        "cached": False,
        "sources": results,
        "people": people,
        "summary": {
            "platforms_searched": len(results),
            "platforms_found": len(found),
            "people_found": len(people),
            "latest_activity_at": latest,
            "latest_activity_ago": _ago(
                datetime.fromisoformat(latest).timestamp()) if latest else None,
        },
    }
    _cache_put(key, payload)
    return payload, 200


def _lookup_keyword(query, sources=None, force=False):
    """Live mentions feed. Each source searches its own corpus; the ok blocks
    are merged into one feed sorted newest first. One source being quiet or
    rate-limited never blocks the rest."""
    query = (query or "").strip()
    if not query:
        return {"error": "Enter a keyword or phrase to track."}, 400
    sources, unknown = _resolve_sources(sources, _KEYWORD_SOURCES, _KEYWORD_ADAPTERS)

    key = _cache_key("keyword", query, sources, {})
    if not force:
        cached = _cache_get(key)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached, 200

    results = []
    for src in unknown:
        results.append(_src(src, "needs_connection", handle=query,
                            note=f"'{src}' is not a registered keyword source."))
    for src in sources:
        try:
            results.append(_KEYWORD_ADAPTERS[src](query))
        except Exception as e:
            results.append(_src(src, "error", handle=query,
                                note=f"Unexpected error ({type(e).__name__})."))

    feed = []
    for r in results:
        if r["status"] != "ok":
            continue
        for a in r.get("activity", []) or []:
            item = dict(a)
            item["platform"] = r["platform"]
            feed.append(item)
    feed.sort(key=lambda a: a.get("ts") or "", reverse=True)

    found = [r for r in results if r["status"] == "ok"]
    latest = feed[0]["ts"] if feed and feed[0].get("ts") else None

    payload = {
        "query": query,
        "unit": "keyword",
        "generated_at": _now_iso(),
        "cached": False,
        "sources": results,
        "feed": feed,
        "summary": {
            "platforms_searched": len(results),
            "platforms_found": len(found),
            "mentions_found": len(feed),
            "latest_activity_at": latest,
            "latest_activity_ago": _ago(
                datetime.fromisoformat(latest).timestamp()) if latest else None,
        },
    }
    _cache_put(key, payload)
    return payload, 200
