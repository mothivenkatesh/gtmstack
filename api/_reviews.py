"""
GTMstack - review site + Quora scrapers.

Public scrape only (no login, no API key) so every adapter degrades cleanly when
a site changes its structure. All reads go through _fetch.get (the shared
resilient transport: TLS fingerprint, per-host backoff, circuit breaker, BYO
proxy) with fail_status={403} so a Cloudflare wall trips the breaker and falls to
a Wayback archive snapshot instead of reading as a clean empty. Results return
the same normalised shape the Signals engine uses so the monitor can merge them
with Reddit/LinkedIn/X mentions.

Sources and honest feasibility (see MONITOR_PLAN.md):
  TrustPilot  __NEXT_DATA__ JSON, most reliable
  Capterra    __NEXT_DATA__ behind Cloudflare, best-effort + Wayback degrade
  G2          licensed data API only (decided); scraper kept for archive top-up
  Quora       server-rendered question pages carry real answer dates; /search is
              login-walled, so discovery needs curated question URLs or a paid key

All are scoped to the last N days (default 10) by filtering the parsed timestamp.
Instagram and Facebook are formally descoped (not compliantly scrapeable).

No em dashes.
"""
from __future__ import annotations

import re
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

try:
    from _fetch import get as _fetch_get
except ImportError:
    _fetch_get = None
try:
    import _archive
except ImportError:
    _archive = None

import requests as _req

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def _get(url, headers=None, timeout=20, use_archive=True):
    """GET through the resilient _fetch cascade. Returns (status_code, text,
    snapshot_ts) where snapshot_ts is set only when the row came from a Wayback
    archive snapshot (so the caller can label it 'as-of' and never treat it as
    fresh). Falls back to plain requests when _fetch is unavailable. Never raises.

    fail_status={403} is what makes a Cloudflare block honest: without it the 403
    resets the breaker and looks like a clean empty page."""
    hdr = headers or _HEADERS
    if _fetch_get is not None:
        archive = _archive.closure(url) if (use_archive and _archive) else None
        try:
            r = _fetch_get(url, headers=hdr, timeout=timeout,
                           impersonate="chrome", fail_status={403}, archive=archive)
            return (getattr(r, "status_code", 0), getattr(r, "text", "") or "",
                    getattr(r, "snapshot_ts", None))
        except Exception:
            return 0, "", None
    # transport unavailable: plain requests, no verify=False (that was a MITM hole)
    try:
        r = _req.get(url, headers=hdr, timeout=timeout)
        return r.status_code, r.text, None
    except Exception:
        return 0, "", None

# Brand -> site slugs/identifiers. Add more brands here as needed.
_G2_SLUGS = {
    "cashfree":  "cashfree",
    "razorpay":  "razorpay",
    "payu":      "payu-india",
    "ccavenue":  "ccavenue",
    "easebuzz":  "easebuzz",
    "instamojo": "instamojo",
    "billdesk":  "billdesk",
    "juspay":    "juspay",
}

_CAPTERRA_SLUGS = {
    "cashfree":  ("cashfree", "cashfree-payments"),
    "razorpay":  ("razorpay", "razorpay"),
    "payu":      ("payu", "payu"),
    "ccavenue":  ("ccavenue", "ccavenue"),
    "easebuzz":  ("easebuzz", "easebuzz"),
    "instamojo": ("instamojo", "instamojo"),
}

_TRUSTPILOT_DOMAINS = {
    "cashfree":  "cashfree.com",
    "razorpay":  "razorpay.com",
    "payu":      "payu.in",
    "ccavenue":  "ccavenue.com",
    "easebuzz":  "easebuzz.io",
    "instamojo": "instamojo.com",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _age_days(ts_str):
    """Days since an ISO timestamp. Returns None on parse failure."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_now() - dt).days
    except Exception:
        return None


def _within(ts_str, days):
    age = _age_days(ts_str)
    return age is not None and age <= days


def _ago(ts_str):
    age = _age_days(ts_str)
    if age is None:
        return ""
    if age == 0:
        return "today"
    if age == 1:
        return "1 day ago"
    return f"{age} days ago"


def _parse_relative_time(text):
    """Turn strings like '2 days ago', 'a week ago', 'March 2024' into ISO UTC.
    Returns None when unrecognisable."""
    t = (text or "").lower().strip()
    now = _now()

    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {
            "second": timedelta(seconds=n),
            "minute": timedelta(minutes=n),
            "hour":   timedelta(hours=n),
            "day":    timedelta(days=n),
            "week":   timedelta(weeks=n),
            "month":  timedelta(days=n * 30),
            "year":   timedelta(days=n * 365),
        }.get(unit, timedelta(days=n))
        return (now - delta).isoformat()

    if re.search(r"\ba\s+week\b", t):
        return (now - timedelta(weeks=1)).isoformat()
    if re.search(r"\ba\s+month\b", t):
        return (now - timedelta(days=30)).isoformat()
    if re.search(r"\ba\s+year\b", t):
        return (now - timedelta(days=365)).isoformat()

    # "January 2024", "Jan 2024", "Jan 15 2024"
    for fmt in ("%B %Y", "%b %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    return None


def _parse_date(raw):
    """Parse a date field to ISO UTC, trying ISO-8601 FIRST then relative/worded
    forms. The review-site JSON-LD carries ISO dates ('2024-03-15T...'), which the
    relative parser cannot read, so calling _parse_relative_time alone silently
    dropped every dated review. Returns None on total failure (the caller then
    skips the row rather than fabricating a date)."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        pass
    # bare date like 2024-03-15
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        pass
    return _parse_relative_time(s)


def _clean(s, limit=300):
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _post(text, url, ts, platform, brand, rating=None, author=None,
          snapshot_ts=None):
    """Normalised mention dict matching the shape used by _signals.py.
    snapshot_ts (a Wayback stamp) is set only when the row came from an archive
    snapshot, so the UI can label it 'as-of <date>' and never treat it as fresh."""
    return {
        "kind":   "review",
        "text":   _clean(text),
        "url":    url or "",
        "ts":     ts or "",
        "ago":    _ago(ts),
        "where":  platform,
        "author": author or "",
        "brand":  brand,
        "rating": rating,
        "engagement": [],
        "from_archive": bool(snapshot_ts),
        "snapshot_ts": snapshot_ts,
    }


# ---------------------------------------------------------------------------
# G2
# ---------------------------------------------------------------------------

def _g2_reviews(brand, days=10):
    """G2 scrape. NOTE (decided): G2's production path is the licensed data API
    (see _g2_api), because compliant scraping is blocked by Cloudflare. This
    scraper is kept only as a best-effort archive top-up; expect it to 403 live
    and serve a stale Wayback snapshot (labeled) or nothing."""
    slug = _G2_SLUGS.get(brand.lower())
    if not slug:
        return []
    url = f"https://www.g2.com/products/{slug}/reviews"
    code, html, snap = _get(url, use_archive=False)
    if code != 200 or not html:
        return []

    out = []
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(blob)
            reviews = []
            if isinstance(data, list):
                reviews = [d for d in data if d.get("@type") in ("Review", "UserReview")]
            elif data.get("@type") == "Product":
                reviews = data.get("review", [])
            for rv in reviews:
                ts = _parse_date(rv.get("datePublished") or rv.get("dateCreated") or "")
                if not _within(ts, days):
                    continue
                body = rv.get("reviewBody") or rv.get("description") or ""
                rating = None
                rr = rv.get("reviewRating", {})
                if rr:
                    rating = rr.get("ratingValue")
                author = (rv.get("author") or {}).get("name") or ""
                out.append(_post(body, url, ts, "g2", brand, rating, author, snap))
        except Exception:
            pass
    if out:
        return out

    # HTML microdata fallback
    blocks = re.findall(
        r'<div[^>]+itemprop="review"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html, re.S)
    for block in blocks[:20]:
        date_m = re.search(r'datetime="([^"]+)"', block)
        ts = _parse_date(date_m.group(1)) if date_m else None
        if not ts:
            rel_m = re.search(r'class="[^"]*date[^"]*"[^>]*>([^<]+)<', block)
            ts = _parse_date(rel_m.group(1).strip()) if rel_m else None
        if not _within(ts, days):
            continue
        body_m = re.search(r'itemprop="reviewBody"[^>]*>(.*?)</[a-z]+>', block, re.S)
        body = re.sub(r"<[^>]+>", " ", body_m.group(1)) if body_m else ""
        rating_m = re.search(r'itemprop="ratingValue"[^>]*content="([^"]+)"', block)
        rating = rating_m.group(1) if rating_m else None
        author_m = re.search(r'itemprop="name"[^>]*>([^<]+)<', block)
        author = author_m.group(1).strip() if author_m else ""
        out.append(_post(body, url, ts, "g2", brand, rating, author, snap))
    return out


# ---------------------------------------------------------------------------
# Capterra
# ---------------------------------------------------------------------------

def _capterra_reviews(brand, days=10):
    """Capterra scrape. Gated: the /p/<id>/<slug>/ URL needs the real NUMERIC
    product id (the map below is slug-only and will 404 until curated), and
    Gartner fronts Capterra with Cloudflare. Returns [] cleanly on a bad id or a
    block; Wayback serves a stale snapshot when available."""
    pair = _CAPTERRA_SLUGS.get(brand.lower())
    if not pair:
        return []
    pid, slug = pair
    if not str(pid).isdigit():
        return []          # placeholder id, not a real numeric product id yet
    url = f"https://www.capterra.com/p/{pid}/{slug}/reviews/"
    code, html, snap = _get(url, use_archive=False)
    if code != 200 or not html:
        return []

    out = []
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(blob)
            reviews = []
            if isinstance(data, dict) and data.get("@type") == "Product":
                reviews = data.get("review", [])
            for rv in reviews:
                ts = _parse_date(rv.get("datePublished") or "")
                if not _within(ts, days):
                    continue
                body = rv.get("reviewBody") or ""
                rating = (rv.get("reviewRating") or {}).get("ratingValue")
                author = (rv.get("author") or {}).get("name") or ""
                out.append(_post(body, url, ts, "capterra", brand, rating, author, snap))
        except Exception:
            pass
    if out:
        return out

    nd_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if nd_m:
        try:
            nd = json.loads(nd_m.group(1))
            reviews_raw = []
            def _dig(obj, depth=0):
                if depth > 8 or not isinstance(obj, (dict, list)):
                    return
                if isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict) and ("reviewBody" in item or "review_body" in item):
                            reviews_raw.append(item)
                        else:
                            _dig(item, depth + 1)
                else:
                    for v in obj.values():
                        _dig(v, depth + 1)
            _dig(nd)
            for rv in reviews_raw[:20]:
                ts_raw = rv.get("publishedDate") or rv.get("datePublished") or rv.get("date") or ""
                ts = _parse_date(ts_raw)
                if not _within(ts, days):
                    continue
                body = rv.get("reviewBody") or rv.get("review_body") or rv.get("body") or ""
                rating = rv.get("overallRating") or rv.get("rating")
                author = rv.get("reviewerName") or rv.get("author") or ""
                out.append(_post(body, url, ts, "capterra", brand, rating, author, snap))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# TrustPilot
# ---------------------------------------------------------------------------

def _trustpilot_reviews(brand, days=10):
    domain = _TRUSTPILOT_DOMAINS.get(brand.lower())
    if not domain:
        return []
    url = f"https://www.trustpilot.com/review/{domain}"
    code, html, snap = _get(url, use_archive=False)  # windowed scan: stale snapshots miss the window
    if code != 200 or not html:
        return []

    out = []
    # TrustPilot embeds __NEXT_DATA__ reliably
    nd_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if nd_m:
        try:
            nd = json.loads(nd_m.group(1))
            reviews = (nd.get("props", {})
                         .get("pageProps", {})
                         .get("reviews", []))
            if not reviews:
                biz = (nd.get("props", {})
                          .get("pageProps", {})
                          .get("businessUnit", {}))
                reviews = biz.get("reviews", [])
            for rv in reviews[:25]:
                ts = _parse_date(rv.get("dates", {}).get("publishedDate")
                                 or rv.get("publishedDate") or "")
                if not _within(ts, days):
                    continue
                text = rv.get("text") or rv.get("title") or ""
                rating = rv.get("rating") or rv.get("stars")
                consumer = rv.get("consumer") or {}
                author = consumer.get("displayName") or consumer.get("name") or ""
                rv_url = f"https://www.trustpilot.com/reviews/{rv.get('id', '')}"
                out.append(_post(text, rv_url, ts, "trustpilot", brand, rating, author, snap))
        except Exception:
            pass
    if out:
        return out

    # Fallback: JSON-LD
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(blob)
            for rv in (data.get("review") or []):
                ts = _parse_date(rv.get("datePublished") or "")
                if not _within(ts, days):
                    continue
                body = rv.get("reviewBody") or ""
                rating = (rv.get("reviewRating") or {}).get("ratingValue")
                author = (rv.get("author") or {}).get("name") or ""
                out.append(_post(body, url, ts, "trustpilot", brand, rating, author, snap))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Quora
# ---------------------------------------------------------------------------

def _quora_posts(query, days=10):
    """Quora search by query. NOTE: /search?q= is JS/login-walled for non-browser
    clients, so this usually returns nothing live; the reliable path is a curated
    list of question URLs (see _quora_question), whose server-rendered pages carry
    real answer dates. This function NEVER fabricates a date: a row with no parsed
    date is dropped, so the 'capture answer dates' requirement stays honest."""
    url = f"https://www.quora.com/search?q={quote_plus(query)}&time=week"
    code, html, snap = _get(url, use_archive=False)
    if code != 200 or not html:
        return []

    out = []
    state_m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>', html, re.S)
    if state_m:
        try:
            state = json.loads(state_m.group(1))
            entities = state.get("entities", {})
            for kind in ("questions", "answers"):
                for eid, obj in (entities.get(kind) or {}).items():
                    text = (obj.get("questionText") or obj.get("content") or
                            obj.get("contentHTML") or "")
                    text = re.sub(r"<[^>]+>", " ", text)
                    ts = _parse_date(obj.get("creationTime") or
                                     obj.get("lastUpdatedTime") or "")
                    if not _within(ts, days):     # no real date -> drop, never fake
                        continue
                    q_url = obj.get("url") or url
                    if q_url and not q_url.startswith("http"):
                        q_url = "https://www.quora.com" + q_url
                    out.append(_post(text, q_url, ts, "quora", "", None,
                                     (obj.get("author") or {}).get("names", [""])[0]))
        except Exception:
            pass
    return out[:20]


def _quora_question(url, days=10):
    """Read a single Quora QUESTION page (server-rendered, so answer dates are
    real). This is the reliable Quora path: feed it curated question URLs from the
    group config. Extracts answers with their dateModified/dateCreated. Never
    fabricates a date."""
    if not url or "quora.com" not in url:
        return []
    code, html, snap = _get(url, use_archive=True)
    if code != 200 or not html:
        return []

    out = []
    q_title = ""
    tm = re.search(r'<title>([^<]+)</title>', html)
    if tm:
        q_title = re.sub(r"\s*-\s*Quora\s*$", "", tm.group(1)).strip()

    # Quora question pages carry schema.org Question/Answer JSON-LD
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(blob)
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                main = node.get("mainEntity") or node
                answers = main.get("suggestedAnswer") or []
                if main.get("acceptedAnswer"):
                    answers = [main["acceptedAnswer"]] + list(answers)
                for ans in answers:
                    ts = _parse_date(ans.get("dateModified") or ans.get("dateCreated") or "")
                    if not _within(ts, days):
                        continue
                    body = ans.get("text") or ""
                    author = ((ans.get("author") or {}).get("name")) or ""
                    upvotes = ans.get("upvoteCount")
                    row = _post(body or q_title, url, ts, "quora", "", None, author, snap)
                    if upvotes is not None:
                        row["engagement"] = [{"label": "upvotes", "value": str(upvotes)}]
                    out.append(row)
        except Exception:
            pass
    return out[:20]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_sites_scan(brands, days=10, deadline=None):
    """
    Scan G2 + Capterra + TrustPilot for a list of brand names.
    Returns a list of normalised mention dicts, sorted newest-first.

    deadline (a time.monotonic() value) lets a time-boxed caller stop between
    fetches: blocked review sites answer their Cloudflare challenge slowly (~7s),
    so without this the scan can overrun the monitor budget by minutes.
    """
    import time as _t
    out = []
    for brand in brands:
        if deadline and _t.monotonic() > deadline:
            break
        for fn in (_trustpilot_reviews, _capterra_reviews, _g2_reviews):
            if deadline and _t.monotonic() > deadline:
                break
            try:
                out.extend(fn(brand, days=days))
            except Exception:
                pass
    out.sort(key=lambda p: p.get("ts") or "", reverse=True)
    return out


def quora_scan(keywords, days=10, question_urls=None):
    """
    Read Quora for each keyword (search, usually login-walled) and each curated
    QUESTION url (server-rendered, reliable). Returns normalised mention dicts,
    newest first. question_urls is the dependable path; keyword search is a
    best-effort top-up.
    """
    out, seen = [], set()
    for url in (question_urls or []):
        for p in _quora_question(url, days=days):
            key = p.get("url", "") + "|" + p.get("text", "")[:80]
            if key not in seen:
                seen.add(key)
                out.append(p)
    for kw in (keywords or []):
        for p in _quora_posts(kw, days=days):
            key = (p.get("url") or "") + "|" + p.get("text", "")[:80]
            if key not in seen:
                seen.add(key)
                p["keyword"] = kw
                out.append(p)
    out.sort(key=lambda p: p.get("ts") or "", reverse=True)
    return out
