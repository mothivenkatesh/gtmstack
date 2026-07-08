"""
GTMstack - Wayback Machine archive fallback.

A compliant last-resort read for sources that block live scraping (G2 and
Capterra sit behind Cloudflare). archive.org re-serves publicly crawled content,
so fetching a snapshot violates no source ToS; it is the fallback the _fetch
transport's archive= hook was built for.

Honest limits: coverage is snapshot-frequency-bound. Mid-size Indian PG brand
pages on G2 / Capterra are crawled sparsely, so a snapshot can be weeks stale.
Callers must label archive rows with the snapshot date and never treat archive
as the freshness source. archive.today is deliberately NOT used: it has no stable
API and itself fronts with a CAPTCHA. Wayback's availability API is the usable one.

No em dashes.
"""
from __future__ import annotations

import requests

_AVAIL = "https://archive.org/wayback/available"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class _Resp:
    """Minimal response-like object so archive returns match _fetch.get returns:
    the caller reads .status_code / .text / .from_archive / .snapshot_ts."""
    __slots__ = ("status_code", "text", "from_archive", "snapshot_ts", "url")

    def __init__(self, status_code, text, snapshot_ts=None, url=None):
        self.status_code = status_code
        self.text = text
        self.from_archive = True
        self.snapshot_ts = snapshot_ts       # '20240315123000' Wayback stamp
        self.url = url

    def json(self):
        import json
        return json.loads(self.text)


def latest_snapshot(url, timeout=15):
    """Return (snapshot_url, timestamp) for the newest Wayback capture of `url`,
    or (None, None) when there is no snapshot. Never raises."""
    try:
        r = requests.get(_AVAIL, params={"url": url},
                         headers={"user-agent": UA}, timeout=timeout)
        snap = (r.json() or {}).get("archived_snapshots", {}).get("closest", {})
        if snap.get("available") and snap.get("url"):
            return snap["url"], snap.get("timestamp")
    except Exception:
        pass
    return None, None


def wayback_response(url, timeout=15):
    """Fetch the latest Wayback snapshot of `url` and return a _Resp. When no
    snapshot exists (or the fetch fails), returns a synthetic 404 _Resp so the
    caller sees an honest miss, not a live 200. Never raises."""
    snap_url, ts = latest_snapshot(url, timeout=timeout)
    if not snap_url:
        return _Resp(404, "", snapshot_ts=None, url=url)
    try:
        r = requests.get(snap_url, headers={"user-agent": UA}, timeout=timeout)
        return _Resp(getattr(r, "status_code", 0), r.text, snapshot_ts=ts, url=snap_url)
    except Exception:
        return _Resp(0, "", snapshot_ts=ts, url=snap_url)


def closure(url, timeout=15):
    """A zero-arg callable for _fetch.get(archive=...). Binds `url` so the
    transport can serve the Wayback snapshot when the live host is blocked."""
    def _fallback():
        return wayback_response(url, timeout=timeout)
    return _fallback
