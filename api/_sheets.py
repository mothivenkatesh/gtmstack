"""
GTMstack - Google Sheets push with URL-hash dedup.

Pushes mention rows to a Google Sheet. Dedup is done by hashing each row's URL
(or text+platform when no URL) and comparing against the IDs already in the
sheet's first column before writing, so running the job twice does not create
duplicates.

Auth: service account JSON. Set GOOGLE_SA_JSON to the path of the downloaded
service account key file, or paste the JSON content into GOOGLE_SA_KEY.

Without credentials this module degrades cleanly: configured() returns False,
push() returns {"skipped": True} and logs a warning.

No em dashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

_GSPREAD_OK = False
try:
    import gspread
    from gspread.exceptions import APIError
    _GSPREAD_OK = True
except ImportError:
    pass


def configured():
    return _GSPREAD_OK and bool(
        os.getenv("GOOGLE_SA_JSON") or os.getenv("GOOGLE_SA_KEY")
    )


def _client():
    """Return an authenticated gspread client."""
    if not _GSPREAD_OK:
        raise RuntimeError("gspread not installed: pip install gspread")
    key_path = os.getenv("GOOGLE_SA_JSON")
    key_raw  = os.getenv("GOOGLE_SA_KEY")
    if key_path and os.path.exists(key_path):
        return gspread.service_account(filename=key_path)
    if key_raw:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(key_raw)
            tmp = fh.name
        client = gspread.service_account(filename=tmp)
        os.unlink(tmp)
        return client
    raise RuntimeError(
        "Set GOOGLE_SA_JSON (path to service-account key file) or "
        "GOOGLE_SA_KEY (the JSON content) to enable Sheets push."
    )


def _row_id(mention):
    """Dedup id for the sheet. Prefers the kind-aware dedup_key computed by
    _mentions (so a comment and its parent post are distinct rows); falls back to
    a URL/text hash for callers that did not stamp one."""
    k = mention.get("dedup_key")
    if k:
        return k
    url = (mention.get("url") or "").strip()
    basis = url or f"{mention.get('where','')}{mention.get('text','')[:120]}"
    kind = (mention.get("kind") or "post").lower()
    return f"{kind}:" + hashlib.sha1(basis.encode()).hexdigest()[:16]


def _to_row(mention, run_date):
    """Map a mention dict to a flat sheet row. Text is prefixed with a single
    quote when it would otherwise be read as a formula, a belt-and-suspenders on
    top of value_input_option=RAW, so a review starting with = or + cannot inject."""
    rating = mention.get("rating")
    text = (mention.get("text") or "")[:500]
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    snap = mention.get("snapshot_ts") or ""
    return [
        _row_id(mention),                           # A: dedup id (kind-aware)
        run_date,                                   # B: scan date (YYYY-MM-DD)
        mention.get("where") or "",                 # C: platform
        mention.get("brand") or mention.get("keyword") or "",  # D: brand / keyword
        mention.get("kind") or "",                  # E: kind (post/comment/review/answer)
        text,                                       # F: text
        mention.get("url") or "",                   # G: URL
        mention.get("ts") or "",                    # H: post timestamp (ISO, the answer date)
        mention.get("ago") or "",                   # I: human age
        mention.get("author") or "",                # J: author
        str(rating) if rating is not None else "",  # K: rating
        mention.get("sentiment") or "",             # L: sentiment
        mention.get("company") or "",               # M: author company
        mention.get("enrich_mode") or "",           # N: model | lexicon
        ("as-of " + snap) if snap else "",          # O: archive snapshot note
    ]


_HEADER = [
    "id", "scan_date", "platform", "brand_keyword", "kind",
    "text", "url", "post_date", "age", "author",
    "rating", "sentiment", "company", "enrich_mode", "archive",
]


def _ensure_header(ws):
    """Write the header row if the sheet is empty."""
    try:
        first = ws.cell(1, 1).value
    except Exception:
        first = None
    if not first:
        ws.update("A1", [_HEADER])


def _existing_ids(ws):
    """Set of dedup IDs already in column A (skip header)."""
    try:
        vals = ws.col_values(1)  # includes header "id"
        return set(v for v in vals[1:] if v)
    except Exception:
        return set()


def _with_retry(fn, tries=3, base=1.5):
    """Run a gspread call with backoff on transient APIError (429/5xx)."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:       # gspread.exceptions.APIError and friends
            last = exc
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code and code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(base * (2 ** i))
    if last:
        raise last


def push(mentions, sheet_url=None, tab="Mentions"):
    """
    Push a list of mention dicts (already the delta to insert) to a Google Sheet.

    The mentions passed here are the NEW rows for this run (the monitor upserts to
    the store first and only sends inserts), so this is an append, not a full
    reconcile. A capped column-A safety read (MONITOR_SHEET_SAFETY=1) guards
    against a torn previous run for a two-week burn-in, then can be turned off.

    sheet_url -- full Sheets URL (falls back to GTMSTACK_SHEET_URL). REQUIRED:
                 we never auto-create + public-share a sheet (that leaked data in
                 the first pass). Fails loudly when unset.
    tab       -- worksheet tab (created if missing).

    Returns {pushed, skipped_dup, sheet_url, tab, gid} or {error|skipped}.
    """
    if not configured():
        print("[sheets] not configured (set GOOGLE_SA_JSON + share the sheet "
              "with the service account email) -- skipping push", flush=True)
        return {"skipped": True, "reason": "not_configured"}

    url = sheet_url or os.getenv("GTMSTACK_SHEET_URL") or ""
    if not url:
        print("[sheets] GTMSTACK_SHEET_URL is not set. Create a sheet, share it "
              "with the service-account email, and set GTMSTACK_SHEET_URL. Refusing "
              "to auto-create a public sheet.", flush=True)
        return {"error": "GTMSTACK_SHEET_URL not set", "pushed": 0}

    safety = os.getenv("MONITOR_SHEET_SAFETY", "1") == "1"
    rotate_at = int(os.getenv("MONITOR_SHEET_ROTATE_ROWS", "4000"))

    try:
        gc = _client()
        ss = _with_retry(lambda: gc.open_by_url(url))

        ws = _get_or_rotate_tab(ss, tab, rotate_at)
        _ensure_header(ws)

        existing = _existing_ids(ws) if safety else set()
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        new_rows, dupes, seen = [], 0, set()
        for m in mentions:
            rid = _row_id(m)
            if rid in existing or rid in seen:      # torn-run + intra-batch guard
                dupes += 1
                continue
            seen.add(rid)
            new_rows.append(_to_row(m, run_date))

        if new_rows:
            _with_retry(lambda: ws.append_rows(new_rows, value_input_option="RAW"))

        return {
            "pushed":      len(new_rows),
            "skipped_dup": dupes,
            "sheet_url":   ss.url,
            "tab":         ws.title,
            "gid":         ws.id,       # for per-tab deep links in the UI
        }

    except Exception as exc:
        print(f"[sheets] push failed: {exc}", flush=True)
        return {"error": str(exc), "pushed": 0}


def _get_or_rotate_tab(ss, tab, rotate_at):
    """Return the worksheet for `tab`, creating it if missing. When the current
    tab is past rotate_at rows, roll to a YYYY-MM suffixed tab so no single tab
    approaches the cell ceiling and fast tabs (cashfree_mentions) stay snappy."""
    base = tab
    try:
        ws = ss.worksheet(base)
        # Gate on POPULATED rows, not ws.row_count (grid capacity, always 5000 from
        # add_worksheet), else every tab rotates on the second run and orphans the
        # base tab. Every written row has a non-empty col A (the dedup id).
        try:
            populated = len(ws.col_values(1))
        except Exception:
            populated = 0
        if rotate_at and populated >= rotate_at:
            ym = datetime.now(timezone.utc).strftime("%Y-%m")
            base = f"{tab} {ym}"
            try:
                ws = ss.worksheet(base)
            except gspread.WorksheetNotFound:
                ws = ss.add_worksheet(title=base, rows=5000, cols=len(_HEADER))
        return ws
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=base, rows=5000, cols=len(_HEADER))
