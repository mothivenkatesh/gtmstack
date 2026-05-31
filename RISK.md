# RISK.md

> Premortem on the work shipped this session: the resilient transport, the
> provider-agnostic LLM layer, and the three content agents. Produced by the
> `/premortem` skill (lean-engineering-skills). Note: there is no `SPEC.md` for
> this code (it was built without `/spec`), so this is a reverse-applied
> premortem on existing, already-shipped code. Rule Zero: the project is not a
> git repository, so there is no history to read, which is itself Finding C1.

## System Under Review

The content-axis plays (agents 12 Content Performance, 13 Profile Teardown, 14
Trend & Top-Voice) and the shared infra they run on: `_fetch.py` (HTTP transport
with per-host backoff, BYO proxy, circuit breaker), `_llm.py` (one `chat()` over
Anthropic or any OpenAI-compatible endpoint, heuristic fallback when no model),
`_reliability.py` + `_util.py` (confidence + citation grounding). Engines are
invoked through `_plays.py`, served by Flask locally and Vercel serverless. The
system reads untrusted scraped content (GitHub, X, YouTube, Reddit) and feeds it
to an LLM, then returns grounded analysis.

## The Failure Story (90 days out)

A user points `GTMFORCE_LLM_BASE_URL` at their model and `GTMFORCE_MODEL` at a
DeepSeek reasoning model. It works in testing. Three weeks later a play quietly
starts returning "built-in model" results for every run. Root cause: the
reasoning model's `<think>` block plus the JSON now exceeds `max_tokens`, so the
JSON is truncated, `json.loads` raises, and `analyze()` hits
`except Exception: result = None` and silently degrades to the heuristic. No log,
no metric, no surfaced reason. The user assumes "the live model broke" and cannot
tell that apart from "no key configured." Time to alert: never (a user noticed).
Time to root cause: an hour of reading code, because nothing recorded *why* it
fell back. This is the textbook silent-swallow failure (Category 2).

## Critical Findings (fix before shipping to anyone but yourself)

| Mode | Likelihood | Impact | Fix |
|---|---|---|---|
| C1: Not under version control | Certain (true now) | No rollback, no history, no incident forensics. Everything this session is unversioned. | `git init`, commit, add a remote. ~10 min. |
| C2: Silent LLM-fallback swallow | High with reasoning models | Live-model failures look identical to no-key; invisible quality drop | In each `analyze()`, log the exception and attach a `fallback_reason` to the result so "why built-in model?" is answerable |
| C3: No observability on the model path | Certain | Cannot answer "how many runs fell back / failed in the last hour" (Dan Luu near-disaster category) | One JSONL trace line per LLM call (engine, model, ok, fallback_reason, latency_ms) + a `/health` route |

## Significant Findings (fix before scaling / real multi-user)

| Mode | Likelihood | Impact | Fix |
|---|---|---|---|
| S1: Anthropic call has no explicit timeout | Medium | A slow Anthropic API hangs the play far past the OpenAI-path's bounded timeout | Pass a `timeout` to `Anthropic().messages.create` (mirror `GTMFORCE_LLM_TIMEOUT`) |
| S2: No circuit breaker on the LLM host | Medium | If the model endpoint is down, every play eats the full timeout then falls back; no fast-fail | Route the LLM POST through `_fetch` (it already has the breaker) or add a model-host breaker |
| S3: `_store` snapshot write is not atomic | Medium under concurrency | Two content_performance runs for the same handle race the JSON read-modify-write → lost or corrupt snapshots | Write to a temp file + `os.replace`, or a per-handle lock; the breaker pattern already shows the lock idiom |
| S4: No startup validation of model config | Medium | `GTMFORCE_MODEL` not matching the deployed model fails at runtime, not startup, and degrades silently (ties to C2) | On first use, validate reachability or surface the first error loudly instead of swallowing |
| S5: Play output shape changed (string list → object) | Low now, high if an agent already calls it | An external caller of the old `creator_teardown` shape breaks with no version flag | Version the play response, or document the shape as unstable pre-1.0 |

## Acceptable (document and monitor)

| Mode | Why acceptable | Monitoring |
|---|---|---|
| Sequential Signals fan-out | Correctness fine; only latency (~20s) | The ~20s run time is the signal; parallelize when it annoys |
| Fixed 60s breaker cooldown, no jitter | Single instance today; thundering herd is a multi-instance problem | Add `+ random(0, cooldown*0.1)` when running >1 instance |
| Heuristic fallback is shallow | By design, honest, labeled "built-in model" | Confidence band + audit line already expose it |

## Reversibility Assessment

- **Type 1 (irreversible / high cost to undo):** not being in git (no safety net for any change); the RunPod API key already pasted into chat (compromised, rotate); the play output-shape change *if* an external agent already consumes the old shape.
- **Type 2 (reversible):** the three new engines/plays (additive, isolated behind their own play ids); `_fetch` (wraps `_get`, revertible to a direct call); the provider switch (env-var gated, unset to fall back to Anthropic/heuristic).

## Observability Gap

- **Visible today:** per-source status (ok / needs_connection / error) in the Signals step; HTTP status codes; the confidence band + audit line per result.
- **Must add before deploy:** (1) a log + `fallback_reason` whenever the live model fails (C2); (2) a JSONL trace per LLM call (C3); (3) a `/health` route; (4) latency capture per model call.

## Go / No-Go

- **Local / personal, single-tenant, read-only (current reality): GO as-is.** Failures degrade safely to heuristic results, not crashes or data loss. The risk is invisible quality drop, not an outage.
- **Shippable to other users: SHIP WITH FIXES.** Block on C1 (git) and C2 (stop the silent swallow), then C3 (a trace + health) before real traffic. S1-S4 before more than a handful of users.
- **Minimum safe version (≈30 min):** `git init` + commit; add a one-line warning log and a `fallback_reason` field in `analyze()` so the silent path becomes audible. Everything else is "before scaling."

## Feeds into

`/ops-ready` (DEPLOY.md) — uses these failure modes and the observability gap to build the deploy checklist.
