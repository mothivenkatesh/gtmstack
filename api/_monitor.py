"""
GTMstack - competitive monitor (the 9am daily job).

Groups-driven. It scans every group with monitor=True (see _groups.py), one track
per source the group enables, enriches with shared sentiment + company tagging
(_enrich), upserts into the mentions store (_mentions, Postgres or local JSON),
and exports only the NEWLY INSERTED delta to Google Sheets (_sheets). The store is
the system of record; Sheets is a view. A single-flight lock stops the 9am run,
the 13:00 catch-up, and a manual run-now from overlapping.

Tracks per group (gated on group.sources):
  reddit      per-subreddit restricted search (OAuth primary, arctic fallback);
              posts always, thread COMMENTS too when include_comments is set.
  quora       curated question URLs (reliable, real answer dates) + keyword search.
  reviews     G2 / Capterra / TrustPilot for the group's review_brands.
  x           keyword mentions via the connected session (Signals keyword unit).
  linkedin    honest needs_connection: LinkedIn keyword search is not implemented
              (only own-session person/company reads exist), so competitor keyword
              sentiment on LinkedIn is not available. Stated, not faked.

Instagram and Facebook are formally descoped (not compliantly scrapeable). G2's
production path is a licensed data API (see MONITOR_PLAN.md); the scraper here is
best-effort archive top-up only.

All reads go through the _fetch resilient transport. No em dashes.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# ---- graceful imports (monitor is importable standalone; daily_report sets path)
try:
    from _reviews import review_sites_scan, quora_scan
except ImportError:
    def review_sites_scan(*a, **kw): return []
    def quora_scan(*a, **kw): return []

try:
    from _sheets import push as sheets_push, configured as sheets_configured
except ImportError:
    def sheets_push(*a, **kw): return {"skipped": True}
    def sheets_configured(): return False

try:
    from _signals import lookup as signals_lookup
    import _signals
except ImportError:
    _signals = None
    def signals_lookup(*a, **kw): return {}, 500

try:
    import _enrich
except ImportError:
    _enrich = None

try:
    import _mentions
except ImportError:
    _mentions = None

try:
    from _groups import monitor_groups
except ImportError:
    def monitor_groups(): return []

try:
    import _db
except ImportError:
    _db = None

import requests as _req
_RA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

BUDGET_S = float(os.getenv("MONITOR_BUDGET_S", "240"))
ENRICH_MAX = int(os.getenv("MONITOR_ENRICH_MAX", "60"))
POLITENESS_S = float(os.getenv("MONITOR_POLITENESS_S", "0.4"))
MAX_SUBS_PER_KW = int(os.getenv("MONITOR_MAX_SUBS", "8"))


# ---------------------------------------------------------------------------
# time helpers (UTC storage, IST window boundaries)
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))


def _from_utc(ts):
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return None


def _days_ago(ts):
    dt = _from_utc(ts)
    if not dt:
        return 999
    return (datetime.now(timezone.utc) - dt).days


def _iso(ts):
    dt = _from_utc(ts)
    return dt.isoformat() if dt else ""


def _ago_str(ts):
    d = _days_ago(ts)
    if d <= 0:
        return "today"
    if d == 1:
        return "1 day ago"
    return f"{d} days ago"


def _mention(kind, text, url, ts, where, author, keyword, brand="", rating=None,
             source_id=None):
    """Normalised mention. ts may be an epoch (reddit) or ISO string (reviews)."""
    ts_iso = _iso(ts) if isinstance(ts, (int, float)) else (ts or "")
    ago = _ago_str(ts) if isinstance(ts, (int, float)) else ""
    return {
        "kind": kind, "text": (text or "")[:1000], "url": url or "",
        "ts": ts_iso, "ago": ago, "where": where or "", "author": author or "",
        "keyword": keyword, "brand": brand, "rating": rating,
        "id": source_id, "engagement": [], "sentiment": "", "company": "",
    }


# ---------------------------------------------------------------------------
# Reddit: OAuth per-subreddit restricted search (primary) + arctic fallback
# ---------------------------------------------------------------------------

_ARCTIC = "https://arctic-shift.photon-reddit.com/api"


def _arctic_get(url):
    try:
        r = _req.get(url, headers={"User-Agent": _RA}, timeout=20)
        if r.ok:
            return r.json().get("data", []) or []
    except Exception:
        pass
    return []


def _arctic_posts(sub, q, limit=25):
    return _arctic_get(f"{_ARCTIC}/posts/search?subreddit={_req.utils.quote(sub)}"
                       f"&query={_req.utils.quote(q)}&limit={limit}&sort=desc")


def _arctic_comments(sub, q, limit=20):
    return _arctic_get(f"{_ARCTIC}/comments/search?subreddit={_req.utils.quote(sub)}"
                       f"&query={_req.utils.quote(q)}&limit={limit}&sort=desc")


def _oauth_sub_search(sub, q, token, limit=25):
    """Per-subreddit restricted search via the official API. restrict_sr=1 keeps
    it to this sub (global Reddit search is garbage for niche India PG topics).
    Returns None (so the caller falls to arctic) when there is no OAuth token: the
    public Reddit endpoint 403s from datacenter/flagged IPs and each 403 costs a
    full retry cascade, so we do not even try it without a token."""
    if _signals is None or not token:
        return None
    path = (f"/r/{sub}/search.json?q={_req.utils.quote(q)}&restrict_sr=1"
            f"&sort=new&limit={limit}&raw_json=1&t=month")
    try:
        code, data = _signals._reddit_fetch(path, token)
    except Exception:
        return None
    if not data:
        return None
    return [ch.get("data", {}) for ch in data.get("data", {}).get("children", [])]


def _reddit_track(group, deadline):
    """Posts (and comments when include_comments) for a group, per-subreddit
    restricted, OAuth-first with arctic fallback, filtered to window_days."""
    days = group.get("window_days", 10)
    subs = (group.get("subreddits") or [])[:MAX_SUBS_PER_KW]
    keywords = group.get("keywords") or []
    token = _signals._reddit_token() if _signals else None
    out, seen = [], set()
    status = "quiet"

    for kw in keywords:
        if time.monotonic() > deadline:
            break
        for sub in subs:
            if time.monotonic() > deadline:
                break
            posts = _oauth_sub_search(sub, kw, token)
            if posts is None:
                posts = _arctic_posts(sub, kw)      # keyless fallback
            for d in posts or []:
                if _days_ago(d.get("created_utc")) > days:
                    continue
                pid = d.get("id") or ""
                if not pid or ("post", pid) in seen:
                    continue
                seen.add(("post", pid))
                status = "ok"
                url = "https://www.reddit.com" + (d.get("permalink") or "")
                out.append(_mention(
                    "post", d.get("title") or d.get("selftext"), url,
                    d.get("created_utc"), f"r/{d.get('subreddit', sub)}",
                    d.get("author"), kw, brand=_brand_hit(kw, group), source_id=pid))
            if group.get("include_comments"):
                for d in _arctic_comments(sub, kw):
                    if _days_ago(d.get("created_utc")) > days:
                        continue
                    cid = d.get("id") or ""
                    if not cid or ("comment", cid) in seen:
                        continue
                    seen.add(("comment", cid))
                    status = "ok"
                    link_id = (d.get("link_id") or "").replace("t3_", "")
                    url = (f"https://www.reddit.com/r/{d.get('subreddit', sub)}"
                           f"/comments/{link_id}/_/{cid}") if link_id else ""
                    out.append(_mention(
                        "comment", d.get("body"), url, d.get("created_utc"),
                        f"r/{d.get('subreddit', sub)}", d.get("author"), kw,
                        brand=_brand_hit(kw, group), source_id=cid))
            time.sleep(POLITENESS_S)
    return out, status


def _brand_hit(text, group):
    t = (text or "").lower()
    for b in (group.get("primary") or []) + (group.get("competitors") or []):
        if b.lower() in t:
            return b
    return ""


# ---------------------------------------------------------------------------
# Quora
# ---------------------------------------------------------------------------

def _quora_track(group):
    days = group.get("window_days", 10)
    qs = group.get("quora_questions") or []
    rows = quora_scan(group.get("keywords") or [], days=days, question_urls=qs)
    for r in rows:                       # normalise into the monitor shape
        r.setdefault("kind", "answer")
        r["where"] = "quora"
        r.setdefault("id", None)
    return rows, ("ok" if rows else "quiet")


# ---------------------------------------------------------------------------
# Review sites
# ---------------------------------------------------------------------------

def _reviews_track(group, deadline=None):
    days = group.get("window_days", 10)
    brands = group.get("review_brands") or []
    if not brands:
        return [], "quiet"
    rows = review_sites_scan(brands, days=days, deadline=deadline)
    for r in rows:
        r["where"] = r.get("where") or "review"
        r.setdefault("id", None)
    return rows, ("ok" if rows else "blocked")   # empty reviews usually = blocked


# ---------------------------------------------------------------------------
# Social (X keyword; LinkedIn keyword is not implemented -> honest gap)
# ---------------------------------------------------------------------------

def _social_track(group):
    out, status = [], "quiet"
    kws = group.get("keywords") or []
    want_x = "x" in (group.get("sources") or [])
    if not want_x:
        return out, "quiet"
    for kw in kws[:6]:
        try:
            payload, code = signals_lookup(kw, sources=["x"], unit="keyword")
        except Exception:
            continue
        if code != 200 or not isinstance(payload, dict):
            continue
        for item in payload.get("feed") or []:      # keyword unit returns a feed
            out.append(_mention(
                item.get("kind", "post"), item.get("text"), item.get("url"),
                item.get("ts"), item.get("platform") or "x", item.get("author"),
                kw, brand=_brand_hit(item.get("text"), group),
                source_id=(item.get("url") or "")[-40:]))
            if item.get("engagement"):
                out[-1]["engagement"] = item["engagement"]
        if out:
            status = "ok"
    return out, status


# ---------------------------------------------------------------------------
# One group
# ---------------------------------------------------------------------------

def _run_group(group, deadline):
    gid = group["id"]
    srcs = set(group.get("sources") or [])
    tracks, track_status = {}, {}

    # concurrent, budget-bounded reads; each track degrades independently
    jobs = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        if "reddit" in srcs:
            jobs["reddit"] = pool.submit(_reddit_track, group, deadline)
        if "quora" in srcs:
            jobs["quora"] = pool.submit(_quora_track, group)
        if srcs & {"g2", "capterra", "trustpilot"} or group.get("review_brands"):
            jobs["reviews"] = pool.submit(_reviews_track, group, deadline)
        if "x" in srcs:
            jobs["social"] = pool.submit(_social_track, group)
        from concurrent.futures import TimeoutError as _FTimeout
        for name, fut in jobs.items():
            try:
                rows, st = fut.result(timeout=max(5, deadline - time.monotonic()))
            except _FTimeout:
                rows, st = [], "timeout"
                print(f"[monitor] {gid}/{name} hit the time budget", flush=True)
            except Exception as exc:
                rows, st = [], "error"
                print(f"[monitor] {gid}/{name} failed: {type(exc).__name__}: {exc}",
                      flush=True)
            tracks[name] = rows
            track_status[name] = st

    if "linkedin" in srcs:                # honest: keyword search not implemented
        track_status["linkedin"] = "needs_connection"

    # merge, enrich, persist, export
    mentions = [m for rows in tracks.values() for m in rows]
    run_date = datetime.now(IST).strftime("%Y-%m-%d")
    if _enrich:
        _enrich.enrich_mentions(mentions, cap=ENRICH_MAX)

    inserted, updated = ([], 0)
    if _mentions:
        inserted, updated = _mentions.upsert(gid, mentions, run_date=run_date)

    sheets_result = {}
    if "sheets" in (group.get("sinks") or []) and sheets_configured():
        delta = inserted if _mentions else mentions
        if delta:
            sheets_result = sheets_push(delta, tab=group.get("name") or gid)

    spikes = _velocity_check(group)      # moment-marketing: competitor heat spike

    return {
        "group_id": gid, "group_name": group.get("name"),
        "tracks": {k: len(v) for k, v in tracks.items()},
        "track_status": track_status,
        "found": len(mentions), "inserted": len(inserted), "updated": updated,
        "sheets": sheets_result,
        "spikes": spikes,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _marker_path():
    from pathlib import Path
    base = Path(os.path.expanduser("~/.gtmstack"))
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base / "monitor_last_run"


def _already_ran_today():
    """True if a monitor run already completed today (IST). Lets the 13:00
    catch-up skip when the 9am run succeeded, and only fire when it was missed."""
    try:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        return _marker_path().read_text().strip() == today
    except Exception:
        return False


def _mark_run_done():
    try:
        _marker_path().write_text(datetime.now(IST).strftime("%Y-%m-%d"))
    except Exception:
        pass


def run_monitor(push_to_sheets=True, only=None, catchup=False):
    """Scan every monitor group. Single-flight locked. Returns a run summary.
    catchup=True skips entirely when today's run already completed (the 13:00
    launchd catch-up uses this so it only fires when the 9am run was missed)."""
    if catchup and _already_ran_today():
        print("[monitor] catch-up: today's run already done, skipping", flush=True)
        return {"skipped": "already_ran", "total": 0, "elapsed_s": 0}
    if _mentions and not _mentions.acquire_lock("monitor"):
        print("[monitor] another run holds the lock; skipping", flush=True)
        return {"skipped": "locked", "total": 0, "elapsed_s": 0}

    t0 = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    try:
        groups = [g for g in monitor_groups() if not only or g["id"] == only]
        deadline = time.monotonic() + BUDGET_S
        results = []
        for g in groups:
            print(f"[monitor] scanning {g['id']}", flush=True)
            try:
                res = _run_group(g, deadline)
            except Exception as exc:
                res = {"group_id": g["id"], "error": str(exc)}
                print(f"[monitor] {g['id']} crashed: {exc}", flush=True)
            results.append(res)
            print(f"[monitor] {g['id']}: found {res.get('found', 0)}, "
                  f"new {res.get('inserted', 0)}, statuses {res.get('track_status')}",
                  flush=True)

        # fetch-transport health snapshot for observability
        fstat = {}
        try:
            from _fetch import status as fetch_status
            fstat = fetch_status()
        except Exception:
            pass

        summary = {
            "kind": "monitor_run",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "total": sum(r.get("found", 0) for r in results),
            "inserted": sum(r.get("inserted", 0) for r in results),
            "groups": results,
            "fetch_status": fstat,
            "sheets_configured": sheets_configured(),
        }
        _persist_summary(summary)
        _maybe_alert(summary)
        _mark_run_done()
        try:                              # retention: drop rows older than the window
            if _mentions:
                _mentions.prune(int(os.getenv("MONITOR_RETENTION_DAYS", "180")))
        except Exception:
            pass
        print(f"[monitor] done in {summary['elapsed_s']}s: {summary['total']} found, "
              f"{summary['inserted']} new", flush=True)
        return summary
    finally:
        if _mentions:
            _mentions.release_lock("monitor")


def latest_run():
    """The most recent monitor run summary, or None. Read from the reports table
    (persisted under group_id 'monitor'); local dev without a DB has no run
    history, so this returns None and the UI shows the mentions store instead."""
    if _db and _db.configured():
        try:
            row = _db.latest_report("monitor")
            if row and isinstance(row, dict):
                return row.get("monitor_run") or row
        except Exception:
            pass
    return None


def overview(mentions_per_group=100):
    """Everything the Monitor UI panel needs in one call: the monitor groups,
    the last run summary, and recent mentions per group from the store."""
    groups = monitor_groups()
    men = {}
    if _mentions:
        for g in groups:
            try:
                men[g["id"]] = _mentions.recent(g["id"], limit=mentions_per_group)
            except Exception:
                men[g["id"]] = []
    return {
        "groups": [{k: g.get(k) for k in
                    ("id", "name", "window_days", "sources", "review_brands",
                     "include_comments", "keywords", "primary", "competitors",
                     "quora_questions", "subreddits")} for g in groups],
        "last_run": latest_run(),
        "mentions": men,
        "sheet_url": os.getenv("GTMSTACK_SHEET_URL", ""),
        "sheets_configured": sheets_configured(),
    }


def staleness_hours():
    """Hours since the last successful run, or None when there is no run history.
    The Vercel watchdog reads this to alarm when the Mac has been off too long."""
    lr = latest_run()
    if not lr or not lr.get("finished_at"):
        return None
    try:
        fin = datetime.fromisoformat(lr["finished_at"].replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - fin).total_seconds() / 3600, 1)
    except Exception:
        return None


def _velocity_check(group):
    """Moment-marketing signal: is negative chatter about a COMPETITOR spiking
    right now versus its recent baseline? Reads the mentions store, counts
    negative competitor mentions in the last 24h, and compares to the average
    daily count over the prior 7 days. Returns a spike descriptor or None.

    This is what turns ask 4 from 'sentiment rows' into moment marketing: a live
    alert when a rival is taking heat, so the team can react the same day."""
    if not _mentions:
        return None
    comps = [c.lower() for c in (group.get("competitors") or [])]
    if not comps:
        return None
    try:
        rows = _mentions.recent(group["id"], limit=1000)
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    by_brand = {}
    for r in rows:
        if (r.get("sentiment") != "negative"):
            continue
        brand = (r.get("brand") or "").lower()
        if brand not in comps:
            continue
        ts = r.get("post_ts") or r.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        age_h = (now - dt).total_seconds() / 3600
        b = by_brand.setdefault(brand, {"last24": 0, "prior7d": 0})
        if age_h <= 24:
            b["last24"] += 1
        elif age_h <= 24 * 8:
            b["prior7d"] += 1
    spikes = []
    for brand, c in by_brand.items():
        baseline = c["prior7d"] / 7.0
        if c["last24"] >= 3 and c["last24"] >= max(2.0 * baseline, 3):
            spikes.append({"brand": brand, "last24": c["last24"],
                           "daily_baseline": round(baseline, 1)})
    return spikes or None


def _persist_summary(summary):
    """Store the run summary as a reports-table row so the history survives and
    the Reports/Monitor UI can read it. Best-effort; local dev without a DB just
    skips it (the mentions store already has the data)."""
    if not (_db and _db.configured()):
        return
    try:
        _db.save_report("monitor", "Competitive Monitor",
                        {"monitor_run": summary})
    except Exception:
        pass


def _maybe_alert(summary):
    """Loud on a silent zero: if a source that historically returns rows yields
    nothing this run, email the owner. Best-effort; no-op without _email/creds."""
    try:
        blocked, spikes = [], []
        for g in summary.get("groups", []):
            for src, st in (g.get("track_status") or {}).items():
                if st in ("blocked", "error"):
                    blocked.append(f"{g['group_id']}/{src}={st}")
            for sp in (g.get("spikes") or []):
                spikes.append(f"{sp['brand']}: {sp['last24']} negative in 24h "
                              f"(baseline {sp['daily_baseline']}/day)")
        recipient = os.getenv("MONITOR_ALERT_EMAIL")
        if not recipient:
            return
        if summary.get("total", 0) == 0 or blocked or spikes:
            import _email
            subj = ("[GTMstack] competitor heat spike" if spikes
                    else "[GTMstack] competitive monitor: attention")
            body = (f"Run at {summary.get('finished_at')}\n"
                    f"Total found: {summary.get('total')}\n"
                    f"New: {summary.get('inserted')}\n"
                    + (f"\nMOMENT MARKETING - competitor heat spikes:\n  "
                       + "\n  ".join(spikes) + "\n" if spikes else "")
                    + f"\nBlocked/errored tracks: {', '.join(blocked) or 'none'}\n")
            _email.send(recipient, subj, body)
    except Exception:
        pass
