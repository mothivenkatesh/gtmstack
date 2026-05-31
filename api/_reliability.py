"""
GTMstack — the reliability primitive the content agents share.

The product thesis (positioning.md, agent-specs.md section B) is that an agent is
only trustworthy when its outputs carry three things: a confidence the caller can
gate on, provenance that traces every insight to its source, and an auditable
reason. The pipeline agents (1-11) get this from a data layer GTMstack does not
have yet; the content agents (12 Content Performance, 13 Profile Teardown, 14
Trend & Top-Voice) can get it from the evidence they already read.

Two functions do the work:
  confidence(posts) -> how much to trust an analysis drawn from this evidence,
                       as a 0-1 score + band + a plain-English basis.
  ground(items, posts) -> validate each insight's citations against the real
                       posts, attach short evidence snippets, and flag any
                       insight the model did not ground. This is the
                       "every insight traces to underlying posts" guardrail,
                       enforced in code rather than trusted from the model.

Honest by construction: a thin or unengaged corpus yields a low band, and an
uncited claim is marked ungrounded rather than passed off as evidence-backed.
"""
from __future__ import annotations

_SNIPPET = 80          # chars of a cited post shown as evidence
_VOL_FULL = 12         # posts at which the volume component saturates


def confidence(posts, floor=3):
    """Trust score for an analysis drawn from `posts`.

    Two honest components: volume (more posts = steadier patterns, saturating
    at _VOL_FULL) and engagement coverage (patterns tied to posts that carry
    real engagement are performance-grounded, not just frequent). Below `floor`
    posts there is not enough to trust, so the band is forced low.

    Returns {score: 0-1, band: high|medium|low, basis: str, thin: bool}."""
    n = len(posts or [])
    with_eng = sum(1 for p in (posts or []) if p.get("engagement"))
    cov = (with_eng / n) if n else 0.0
    vol = min(n / float(_VOL_FULL), 1.0)
    score = round(0.6 * vol + 0.4 * cov, 2)
    thin = n < floor
    if thin:
        band = "low"
    else:
        band = "high" if score >= 0.66 else ("medium" if score >= 0.4 else "low")
    basis = f"{n} posts, {with_eng} with engagement data"
    return {"score": score, "band": band, "basis": basis, "thin": thin}


def ground(items, posts):
    """Validate each insight's citations against the real corpus.

    `items` is what a model returned: [{text, cites:[1-based post numbers]}].
    For each, keep only citations that point at a real post, attach a short
    snippet of each cited post as evidence, and mark `grounded` False when the
    model cited nothing. Returns
    [{text, cites:[int], evidence:[{n, platform, snippet}], grounded: bool}]."""
    n = len(posts or [])
    out = []
    for it in items or []:
        if isinstance(it, str):
            it = {"text": it, "cites": []}
        elif not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        cites, evidence = [], []
        for c in (it.get("cites") or []):
            try:
                idx = int(c)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= n and idx not in cites:
                p = posts[idx - 1]
                cites.append(idx)
                evidence.append({
                    "n": idx,
                    "platform": p.get("platform"),
                    "snippet": " ".join((p.get("text") or "").split())[:_SNIPPET],
                })
        out.append({"text": text, "cites": cites,
                    "evidence": evidence, "grounded": bool(cites)})
    return out


def audit_line(conf, items_lists):
    """One human-readable reason string for the audit trail: the confidence
    basis plus how many insights are evidence-grounded. `items_lists` is an
    iterable of grounded-item lists (hooks, formats, themes, ...)."""
    flat = [it for lst in items_lists for it in (lst or [])]
    total = len(flat)
    cited = sum(1 for it in flat if it.get("grounded"))
    grounded = f"{cited} of {total} insights cite their source posts" if total \
        else "no insights to ground"
    return f"Confidence {conf.get('band')}: {conf.get('basis')}. {grounded}."
