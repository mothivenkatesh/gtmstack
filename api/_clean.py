"""
GTMstack — Clean Data engine (deliverability layer).

Hand it a messy CSV / paste of contacts; get back agent-ready rows. Every
address is run through mailguard (the same 9-layer validator published on PyPI):
syntax, MX, disposable, role-based, free-provider, and typo correction. The list
is de-duplicated and each row carries a verdict an agent can branch on
(deliverable / risky / undeliverable).

SMTP probes are OFF by default: port 25 is blocked on most serverless hosts, and
the MX + heuristic layers already separate deliverable from junk without ever
touching the recipient's mailbox. Set check_smtp=True locally if you want the
RCPT probe.

Shared by the Flask app (app.py) and the Vercel handler (clean.py). Same
contract both ways: clean(text|emails) -> (payload, status).
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone

try:
    from mailguard import validate_bulk_sync
except Exception:  # pragma: no cover
    validate_bulk_sync = None

# A pragmatic address grabber: pulls every email-shaped token out of whatever
# you paste (CSV cell, TSV, one-per-line, prose). Column detection is
# deliberately skipped — scanning the raw text is what makes it format-proof.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAX_EMAILS = int(os.getenv("CLEAN_MAX_EMAILS", "1000"))
CONCURRENCY = int(os.getenv("CLEAN_CONCURRENCY", "100"))
TIMEOUT = float(os.getenv("CLEAN_TIMEOUT", "8"))

# The columns surfaced to agents, in order. One row per address, branch on
# `valid` (boolean) or `verdict` (deliverable | risky | undeliverable).
FIELDS = ["email", "valid", "verdict", "score", "reason", "normalized",
          "domain", "mx_ok", "disposable", "role_based", "free_provider",
          "typo_suggestion"]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def extract_emails(text):
    """Every email-shaped token in the text, order preserved (with dupes)."""
    return EMAIL_RE.findall(text or "")


def _row(r):
    """A mailguard ValidationResult -> a flat, agent-ready dict."""
    return {
        "email": r.email,
        "valid": bool(r.is_valid),
        "verdict": r.verdict or ("valid" if r.is_valid else "invalid"),
        "score": r.score,
        "reason": r.reason or "",
        "normalized": r.normalized or r.email,
        "domain": r.domain or "",
        "mx_ok": bool(r.mx_ok),
        "disposable": bool(r.disposable),
        "role_based": bool(r.role_based),
        "free_provider": bool(r.free_provider),
        "typo_suggestion": r.typo_suggestion or "",
    }


def clean(text="", emails=None, check_smtp=False, check_catchall=False):
    """
    text        : raw CSV / TSV / pasted contacts (emails are scanned out).
    emails      : an explicit list, used instead of scanning `text`.
    check_smtp  : run the SMTP RCPT probe (off by default; needs port 25).
    Returns (payload, status_code). Never raises on bad addresses.
    """
    if validate_bulk_sync is None:
        return {"error": "mailguard is not installed on the server."}, 500

    raw = list(emails) if emails is not None else extract_emails(text)
    seen, uniq, dupes = set(), [], 0
    for e in raw:
        k = (e or "").strip().lower()
        if not k:
            continue
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        uniq.append(e.strip())
    if not uniq:
        return {"error": "No email addresses found in the input."}, 400

    truncated = len(uniq) > MAX_EMAILS
    batch = uniq[:MAX_EMAILS]
    results = validate_bulk_sync(
        batch, check_smtp=check_smtp, check_catchall=check_catchall,
        concurrency=CONCURRENCY, timeout=TIMEOUT)
    rows = [_row(r) for r in results]

    by_verdict = {}
    for r in rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    # `valid` spans the deliverable AND risky verdicts (anything with live MX
    # that isn't broken/disposable). by_verdict carries the strict 3-way split.
    valid = sum(1 for r in rows if r["valid"])

    payload = {
        "generated_at": _now_iso(),
        "fields": FIELDS,
        "rows": rows,
        "summary": {
            "submitted": len(raw),
            "unique": len(uniq),
            "duplicates_removed": dupes,
            "validated": len(rows),
            "valid": valid,
            "invalid": len(rows) - valid,
            "by_verdict": by_verdict,
            "smtp_checked": bool(check_smtp),
            "truncated": truncated,
            "max_emails": MAX_EMAILS,
        },
    }
    return payload, 200


# ── serialisers (download for agents) ───────────────────────────────────────
def to_csv(payload, only_clean=False):
    """Validated rows -> CSV text. only_clean keeps just the deliverable ones."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(FIELDS)
    for r in payload.get("rows", []):
        if only_clean and not r.get("valid"):
            continue
        w.writerow([r.get(f, "") for f in FIELDS])
    return out.getvalue()


def to_json(payload, only_clean=False):
    """Validated rows -> JSON text (the agent-ready array)."""
    import json
    rows = payload.get("rows", [])
    if only_clean:
        rows = [r for r in rows if r.get("valid")]
    return json.dumps(rows, indent=2)
