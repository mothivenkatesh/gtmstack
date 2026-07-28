"""
Delivery - the last mile that turns a demo into a product.

Everything upstream of this was already working: Listener reads real posts,
classifies them, and writes them to the graph with provenance. But `send_message`
was a dry run, nothing was scheduled, and no outcome was ever recorded. That
combination means the app only ever did work while a human watched it, which is
a toolkit. Nobody pays monthly for a toolkit they have to operate.

This module closes it:
  deliver()     push a batch to Slack and email, exactly once per signal
  mark()        record what a human did with an alert (the Outcome node)
  value()       the sentence that justifies the invoice

Design rules:
  - IDEMPOTENT. A signal is delivered once, ever. The delivery record lives on
    the signal node, so a re-run or a retry cannot double-send. Nothing destroys
    trust in an unattended agent faster than duplicate alerts at 3am.
  - GATED. No webhook or key configured means it reports "not configured" and
    changes nothing. It never pretends to have sent.
  - NEVER RAISES. A failed webhook must not fail the run that produced good data.

No em dashes.
"""
from __future__ import annotations

import json
import os
import time

import _graph as G
import _observe as O

try:
    import requests
except ImportError:                                              # pragma: no cover
    requests = None

# What a human did with an alert. This is the vocabulary the whole outcome graph
# is built from, so it stays small and unambiguous.
ACTIONED = "actioned"      # they replied, reached out, or followed up
IGNORED = "ignored"        # they saw it and chose not to act
CONVERTED = "converted"    # it became a real conversation or opportunity
OUTCOMES = (ACTIONED, IGNORED, CONVERTED)


def configured():
    """What delivery is actually wired. Reported honestly so the UI can say
    'connect Slack' instead of silently doing nothing."""
    import _email
    slack = bool(os.getenv("SLACK_WEBHOOK_URL"))
    email = bool(_email.configured() and os.getenv("ALERT_EMAIL"))
    wa = bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_ID")
              and os.getenv("WHATSAPP_TO"))
    return {"slack": slack, "email": email, "whatsapp": wa,
            "any": bool(slack or email or wa)}


def _whatsapp_text(items, query):
    """WhatsApp has no blocks and a hard length limit, so this is the terse cut:
    the intent, the quote, and the link. Anything longer gets truncated by the
    client and reads worse than a short message."""
    head = (f"*{len(items)} new signal{'s' if len(items) != 1 else ''}"
            + (f" for {query}*" if query else "*"))
    lines = [head, ""]
    for s in items[:8]:
        d = s["data"]
        lines += [f"*{_LABEL.get(d.get('intent_type'), 'Signal')}* "
                  f"({d.get('sentiment')})",
                  (d.get("text") or "").replace("\n", " ")[:140],
                  (s.get("source") or d.get("url") or ""), ""]
    if len(items) > 8:
        lines.append(f"...and {len(items) - 8} more")
    return "\n".join(lines)


def _send_whatsapp(text):
    """WhatsApp Cloud API (Meta). The channel the India-first positioning names,
    so it is a first-class destination rather than an afterthought.

    Note the 24-hour rule: outside a customer-initiated window Meta only allows
    approved template messages. These alerts go to the TEAM's own number, which
    is a session the team opens, so free-form text is correct here. Customer-
    facing sends will need a template."""
    tok = os.getenv("WHATSAPP_TOKEN")
    pid = os.getenv("WHATSAPP_PHONE_ID")
    to = os.getenv("WHATSAPP_TO")
    if not (tok and pid and to and requests):
        return False, "whatsapp not configured"
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{pid}/messages",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to,
                  "type": "text", "text": {"preview_url": True, "body": text[:4000]}},
            timeout=20)
        if r.status_code < 300:
            return True, "whatsapp sent"
        return False, f"whatsapp {r.status_code}: {r.text[:80]}"
    except Exception as e:                                       # noqa: BLE001
        return False, f"whatsapp error: {str(e)[:90]}"


# ── formatting ──────────────────────────────────────────────────────────────
# The fields are the ones the original request asked for: platform, link,
# author, timestamp, matched keyword, sentiment.

_EMOJI = {"category_intent": ":mag:", "competitor_comparison": ":vs:",
          "complaint": ":warning:", "brand_mention": ":speech_balloon:"}
_LABEL = {"category_intent": "Choosing a vendor",
          "competitor_comparison": "Comparing options",
          "complaint": "Unhappy in public", "brand_mention": "Mentioned you"}


def _slack_blocks(items, query):
    lines = []
    for s in items:
        d = s["data"]
        why = _LABEL.get(d.get("intent_type"), "Worth a look")
        who = d.get("author") or "someone"
        where = d.get("where") or d.get("platform") or ""
        when = d.get("ago") or ""
        text = (d.get("text") or "").replace("\n", " ")[:180]
        lines.append(
            f"{_EMOJI.get(d.get('intent_type'), ':speech_balloon:')} *{why}* "
            f"({d.get('sentiment')})\n"
            f"> {text}\n"
            f"_{who} in {where} {when}_  <{s.get('source') or d.get('url')}|open>")
    head = (f"*{len(items)} new signal{'s' if len(items) != 1 else ''}* "
            f"for `{query}`" if query else f"*{len(items)} new signals*")
    return head + "\n\n" + "\n\n".join(lines)


def _email_body(items, query):
    out = [f"{len(items)} new signals" + (f" for {query}" if query else ""), ""]
    for s in items:
        d = s["data"]
        out += [f"[{_LABEL.get(d.get('intent_type'), 'Signal')}] "
                f"{d.get('sentiment')} - {d.get('platform')}",
                (d.get("text") or "")[:220],
                f"{d.get('author') or 'unknown'} · {d.get('where') or ''} · "
                f"{d.get('ago') or d.get('posted_at') or ''}",
                s.get("source") or d.get("url") or "", ""]
    out += ["", "Reply to any of these and mark it actioned in GTMstack so it "
                "learns which alerts were worth sending."]
    return "\n".join(out)


# ── delivery ────────────────────────────────────────────────────────────────

def _post_slack(text):
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not (url and requests):
        return False, "slack not configured"
    try:
        r = requests.post(url, json={"text": text}, timeout=15)
        return (r.status_code < 300), f"slack {r.status_code}"
    except Exception as e:                                       # noqa: BLE001
        return False, f"slack error: {str(e)[:90]}"


def _send_email(subject, body):
    import _email
    to = os.getenv("ALERT_EMAIL")
    if not (to and _email.configured()):
        return False, "email not configured"
    try:
        _email.send(to, subject, body)
        return True, f"email to {to}"
    except Exception as e:                                       # noqa: BLE001
        return False, f"email error: {str(e)[:90]}"


def pending(intents=("category_intent", "competitor_comparison"), limit=25):
    """Signals worth an alert that have never been delivered.

    The `delivered_at` stamp on the node IS the idempotency key, which is why a
    re-run cannot double-send even if the scheduler fires twice."""
    out = []
    for s in G.query("signal", limit=400):
        d = s["data"]
        if d.get("delivered_at"):
            continue
        if intents and d.get("intent_type") not in intents:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def deliver(items=None, query=None, intents=("category_intent", "competitor_comparison")):
    """Send undelivered signals, once. Returns what happened, always."""
    items = pending(intents) if items is None else items
    cfg = configured()
    if not items:
        return {"sent": 0, "channels": [], "note": "nothing new to send", **cfg}
    if not cfg["any"]:
        return {"sent": 0, "channels": [], "ready": len(items), **cfg,
                "note": f"{len(items)} alerts ready. Connect Slack, email, or "
                        f"WhatsApp to have them delivered."}

    channels, ok_any = [], False
    if cfg["slack"]:
        ok, note = _post_slack(_slack_blocks(items, query))
        channels.append(note); ok_any = ok_any or ok
    if cfg["email"]:
        subj = f"[GTMstack] {len(items)} new signal{'s' if len(items) != 1 else ''}"
        ok, note = _send_email(subj, _email_body(items, query))
        channels.append(note); ok_any = ok_any or ok
    if cfg["whatsapp"]:
        ok, note = _send_whatsapp(_whatsapp_text(items, query))
        channels.append(note); ok_any = ok_any or ok

    # Only stamp when something actually left the building. Stamping on a failed
    # send would silently lose the alert forever, which is worse than a duplicate.
    if ok_any:
        now = time.time()
        for s in items:
            d = dict(s["data"]); d["delivered_at"] = now
            G.upsert("signal", d, key=s.get("key"), agent="listener")
    O.log(O.STEP, agent="listener", ok=ok_any,
          summary=f"delivered {len(items) if ok_any else 0} alerts",
          channels=channels)
    return {"sent": len(items) if ok_any else 0, "channels": channels, **cfg}


# ── outcomes: the reason anyone pays ────────────────────────────────────────

def mark(signal_id, outcome, note=None):
    """Record what a human did with an alert.

    This is the node the entire value story rests on. Without it the product can
    say "we found things"; with it, it can say "we found things and N of them
    became conversations", which is the difference between a $49 tool and a
    priced-on-outcome product. It is also the label that teaches the classifier
    which alerts were worth sending."""
    if outcome not in OUTCOMES:
        return {"ok": False, "error": f"outcome must be one of {OUTCOMES}"}
    sig = G.get(signal_id)
    if not sig:
        return {"ok": False, "error": "unknown signal"}

    oid = G.upsert("outcome", {
        "signal_id": signal_id, "outcome": outcome, "note": note,
        "intent_type": sig["data"].get("intent_type"),
        "platform": sig["data"].get("platform"),
        "marked_at": time.time(),
    }, key=f"outcome:{signal_id}", agent="human", source=sig.get("source"))
    G.link(signal_id, "resulted_in", oid)

    d = dict(sig["data"]); d["actioned"] = outcome != IGNORED; d["outcome"] = outcome
    G.upsert("signal", d, key=sig.get("key"), agent="human")
    O.log(O.APPROVAL, agent="human", ok=True,
          summary=f"signal marked {outcome}", outcome=outcome)
    return {"ok": True, "outcome": oid}


def value(window_s=30 * 86400):
    """The sentence that justifies the invoice.

    Deliberately blunt: found, delivered, actioned, converted. If these numbers
    are not moving, the product is not working, and no amount of interface hides
    that."""
    since = time.time() - window_s
    sigs = [s for s in G.query("signal", limit=2000)
            if (s.get("created_at") or 0) >= since]
    outs = [o for o in G.query("outcome", limit=2000)
            if (o["data"].get("marked_at") or 0) >= since]

    buying = [s for s in sigs
              if s["data"].get("intent_type") in ("category_intent",
                                                  "competitor_comparison")]
    delivered = [s for s in sigs if s["data"].get("delivered_at")]
    by = {o: sum(1 for x in outs if x["data"].get("outcome") == o) for o in OUTCOMES}
    acted = by[ACTIONED] + by[CONVERTED]

    # Precision that MATTERS: of what we bothered a human with, how much did they
    # act on. This is the number that predicts churn, not offline F1.
    useful = round(100.0 * acted / len(delivered), 1) if delivered else None
    return {
        "window_days": round(window_s / 86400.0),
        "found": len(sigs), "buying_intent": len(buying),
        "delivered": len(delivered), "actioned": by[ACTIONED],
        "converted": by[CONVERTED], "ignored": by[IGNORED],
        "useful_alert_rate": useful,
        "sentence": _sentence(len(buying), acted, by[CONVERTED]),
    }


def _sentence(buying, acted, converted):
    if not buying:
        return "No buying signals yet. Give it a keyword and a day."
    if not acted:
        return (f"Found {buying} people publicly choosing a vendor. "
                f"None marked as actioned yet, so we cannot tell you what it was worth.")
    if converted:
        return (f"Found {buying} people publicly choosing a vendor. "
                f"You acted on {acted}, and {converted} became conversations.")
    return (f"Found {buying} people publicly choosing a vendor, and you acted on {acted}.")
