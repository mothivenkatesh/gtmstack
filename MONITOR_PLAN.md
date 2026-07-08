# MONITOR_PLAN.md — Competitive Monitor (Signals)

Detailed build plan to take the competitive monitor from a first-pass draft to
production, surfaced inside the app. No em dashes anywhere (repo rule).

This plan was produced by reading the whole stack (_signals, _report, _carlsen,
_groups, _db, _fetch, _monitor, _reviews, _sheets, index.html, launchd) and
stress-testing three independent designs (product, pipeline, risk) against the
five asks and the repo guardrails.

---

## 1. The ask (verbatim, restated)

1. **Reddit competitor scan.** Daily 9am, all threads matching PG / competitor
   keywords, last 10 days, pushed to Google Sheets, deduped, capture answer dates.
2. **Cashfree mention tracker.** Any post mentioning Cashfree in the last 2 days,
   AND the thread comments, into the sheet.
3. **Quora.** Same as Reddit.
4. **Moment marketing sentiment** on Instagram, LinkedIn, Facebook, X. Sentiment
   plus what they say about the competition.
5. **Review sites.** Same as Reddit, for G2, Capterra, TrustPilot.

---

## 2. Honest scope verdict per source (decide before building)

The guardrails (no stealth browser, no bot-detection bypass, anti-PhantomBuster,
Instagram and Facebook scraping excluded) plus real-world blocking mean not every
source is equally buildable. This is the honest ranking, so we do not sell a
silent-zero as a quiet day.

| Source | Verdict | Path |
|---|---|---|
| Reddit posts | **Feasible** | OAuth app (creds in .env) primary with per-subreddit `restrict_sr=1`; arctic-shift as archive fallback |
| Reddit comments | **Feasible** | arctic-shift comment search only (no official comment-search API); explicit `degraded` status on outage |
| TrustPilot | **Feasible with cascade** | Public `__NEXT_DATA__` JSON via `_fetch` `impersonate=chrome`. Most reliable review source. Official Business API is the upgrade |
| X | **Feasible** | Existing cookie path (`SearchTimeline` POST + query-id self-heal), already wired |
| LinkedIn | **Feasible under king-safety only** | Own-session keyword read, routed through Carlsen (last, sequential, resign on challenge), 6h cache. Engager scraping stays excluded |
| Capterra | **Feasible with cascade, gated** | `__NEXT_DATA__` parse behind Cloudflare; curl_cffi passes sometimes from residential IP; Wayback archive as degrade. Ship only after a live smoke passes |
| Quora | **Feasible for known question URLs** | Server-rendered question pages carry real answer dates. `/search?q=` is JS/login-walled; discovery needs a paid search API (Brave/Bing) or a curated URL list |
| G2 | **Licensed data API (DECIDED)** | User decision: procure G2's official data API for fresh, compliant reviews. No scraping. Until the key lands, G2 is absent (not archive-fallback), stated honestly in the UI |
| Instagram | **DESCOPED (DECIDED)** | User decision: formally dropped from the monitor. Not compliantly scrapeable; Meta Graph own-page mentions do not deliver competitor sentiment |
| Facebook | **DESCOPED (DECIDED)** | User decision: formally dropped, same reasoning as Instagram |

**Bottom line for asks 4 and 5 (decisions locked):** X + LinkedIn carry the
moment-marketing ask on the compliant channels. **Instagram and Facebook are
formally descoped** and will be stated as such in the UI panel copy, not left as a
silent gap. Among review sites, TrustPilot is reliable, Capterra is best-effort,
and **G2 comes only from a licensed data API** (procurement gated); G2 is absent
until that key is set, and the panel says so rather than showing a fake empty.

---

## 3. Current state: what exists and what is actually broken

The first pass shipped three files (`_monitor.py`, `_reviews.py`, `_sheets.py`),
chained from `daily_report.py`, on a 9am launchd trigger. A live dry-run returned
**0 mentions across all 5 tracks in 142s**. That is not just arctic-shift being
down. There are confirmed correctness bugs:

**P0 correctness bugs (fix first, they mask everything else):**
- **Track 5 (social) is dead code.** `signals_lookup` returns a `(payload,
  status_code)` tuple, not a dict; the code calls `.get('sources')` on the tuple,
  and `payload['sources']` is a list of blocks, not a dict. Both fail, swallowed
  by a bare `except`. Also: no LinkedIn keyword adapter exists in
  `_KEYWORD_ADAPTERS`, so `sources=['linkedin']` silently filters out. The
  moment-marketing ask is currently unmet at the code level.
- **Date parser drops every dated review.** `_parse_relative_time` cannot parse
  ISO dates, so even a successful G2/Capterra/TrustPilot JSON-LD fetch discards
  all reviews. Fix: try `datetime.fromisoformat` first, then relative-string.
- **Quora fabricates dates.** The HTML fallback stamps `_now()` on every post,
  which corrupts the "capture answer dates" requirement. Delete the fabrication;
  return only rows with a real parsed date.
- **`verify=False` SSL fallback in `_reviews._get`** is a MITM exposure. Delete it.
- **Capterra product ids are guessed**, so it 404s. Fix the numeric-id map with
  fixtures, or drop Capterra until ids are curated.
- **Unknown-source silent fallback.** `_signals.py:2087` (and :1984, :2033):
  passing an unregistered source name filters to `[]` then falls back to scanning
  ALL default sources, not zero. Tighten so an unknown source is an explicit error.

**P0 transport / ops:**
- `_reviews._get` uses plain `requests` despite a docstring claiming it uses
  `_fetch.get`. No curl_cffi fingerprint, no backoff, no breaker. G2/Capterra sit
  behind Cloudflare and 403 plain requests.
- **403 is invisible to the breaker.** `_fetch` treats 403 as non-retryable, does
  NOT trip the breaker, and does NOT fall to archive. A Cloudflare wall looks like
  a clean empty. Add `fail_status={403}` so review-site blocks register.
- launchd runtime copy is stale, `gspread`+`curl_cffi` are not in the launchd
  venv, and no sheet is configured. Nothing actually runs.

**P0 resilience:**
- arctic-shift is the sole Reddit backend and it was 503 during testing. Use the
  proven `_signals` Reddit OAuth adapter (creds already in .env) as primary, with
  arctic-shift as the archive fallback.

**Architecture debt (the first pass built a parallel universe):**
- `_monitor.py` duplicates `_signals._arctic_posts`, has its own `_mention` shape,
  its own sentiment lexicon (a worse copy of `_report._enrich`), and its own
  hardcoded keyword lists disconnected from `_groups.DEFAULT_GROUPS`.
- No persistence except Google Sheets. No DB table, no local snapshot, nothing the
  UI can read. Dedup memory lives only in the sheet, so a sheets outage loses it.
- Sheets dedup is URL-hash only, so same-thread comments (which share a thread URL)
  collapse into one row. Dedup must be kind-aware (comment id / review id / post
  id), not URL alone.

---

## 4. Target architecture (merged recommendation)

**Fold the monitor into the existing groups + signals + carlsen + report pipeline
and delete every parallel copy.** One config model, one scan engine, one
enrichment path, one transport. The monitor adds exactly three things the report
pipeline does not have: per-mention persistence, comment-volume capture, and an
idempotent Sheets export.

```
_groups (config)                 monitor groups = report groups + monitor fields
   |                             (window_days, subreddits[], review_brands[],
   v                              include_comments, sinks[])
_carlsen (order + king safety)   new source tiers: trustpilot 4, capterra 3,
   |                             quora 3, g2 2; LinkedIn never in a parallel pool
   v
_signals keyword adapters        quora / trustpilot / reddit_comments register in
   |                             _KEYWORD_ADAPTERS as thin wrappers over _reviews;
   |                             capterra / g2 gated on live smoke. All inherit
   |                             _fetch transport + SQLite cache (key + days/limit)
   v
api/_enrich.py (shared)          extract _report._enrich; batched LLM sentiment +
   |                             company, heuristic fallback. Cap by count
   |                             (MONITOR_ENRICH_MAX), not by rank
   v
monitor sink layer               upsert into monitor_mentions (system of record),
   |                             then delta-export to Google Sheets
   +---> monitor_mentions (Postgres via _db.py, _store/ JSON fallback)
   +---> reports table (run summary: per-track health, fetch.status(),
   |                    sheets_result, runtime_version)
   +---> Google Sheets (delta export sink, NOT the system of record)
```

Key decisions locked by the design review:
- **System of record = a new `monitor_mentions` table**, not the reports blob. The
  answer-dates requirement, kind-aware dedup, and idempotent Sheets deltas are
  impossible from a report payload. Run summaries reuse the existing reports table.
- **Google Sheets demotes to a delta-export sink.** Require `GTMSTACK_SHEET_URL`
  and fail loudly. Never auto-create + share-with-anyone (the first pass does this;
  find and lock any sheet it already created). `value_input_option=RAW`
  (formula-injection fix), APIError retry, capture the tab `gid` for UI deep links.
- **Dedup key is kind-aware** and the primary key is `(group_id, dedup_key)` so the
  same URL matched by two groups lands in both tabs. `first_seen` / `last_seen`
  satisfy "capture answer dates" and "thread updated".
- **Enrichment reuses `_report`'s LLM path** (ANTHROPIC_API_KEY is already set), so
  the sheet's sentiment column upgrades from keyword-matching to model-tagged at
  zero new infra cost. Record `enrich_mode` (model vs lexicon) per row.
- **Scheduling stays local launchd** (residential IP + cookies live on the Mac),
  hardened with a 13:00 catch-up interval and a single-flight run lock. A read-only
  Vercel-cron watchdog emails when the last run is older than 26h (the only alarm
  that works when the Mac is off).
- **UI = a Monitor panel inside the existing ReportsTool**, not a new tool. Keep the
  `reports` id and `Reports` label for now (rename is a user decision). Show a
  per-source health strip (ok / quiet / blocked / error) so a silent zero is never
  rendered as a quiet day.

---

## 5. Phased build plan

### Phase 0 — Repair and truth (1 to 2 days)
Goal: a real 9am run lands deduped Reddit posts + Cashfree posts/comments in the
store and the Sheet. No new surface yet, just make it honest.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | Fix Track 5: unpack `(payload, status)`, read `payload['feed']`; remove the bare except | api/_monitor.py | low |
| 2 | Date parse: `fromisoformat` first, then relative; delete Quora `_now()` fabrication | api/_reviews.py | low |
| 3 | Delete `verify=False` SSL fallback | api/_reviews.py | low |
| 4 | Rewire `_reviews._get` and `_monitor._arctic_*` through `_fetch.get(impersonate='chrome')` | api/_reviews.py, api/_monitor.py | low |
| 5 | Add `fail_status={403}` to `_fetch` so Cloudflare blocks trip the breaker + fall to archive; test in tests/test_fetch.py | api/_fetch.py | med |
| 6 | Reddit posts = OAuth primary with per-subreddit `restrict_sr=1` (proven rule), arctic as archive fallback; comment permalinks carry `/comment/<id>` | api/_monitor.py (interim) | low |
| 7 | Fix Capterra numeric product-id map + fixture tests | api/_reviews.py | low |
| 8 | Tighten unknown-source fallback at _signals.py:2087 / :1984 / :2033 | api/_signals.py | med |
| 9 | Sheets: `value_input_option=RAW`, require `GTMSTACK_SHEET_URL`, APIError retry; find + lock any first-pass auto-created public sheet | api/_sheets.py | low |
| 10 | Ops: `pip install gspread curl_cffi` into ~/.gtmstack/venv; re-run install.sh with a version + env manifest stamp | launchd/install.sh | low |

Exit test: a manual `python daily_report.py --monitor` lands real deduped rows.

### Phase 1 — System of record and observability
Goal: the store, not the sheet, is truth; a failed run is loud.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `monitor_mentions` table: PK `(group_id, dedup_key)`, kind-aware key, `first_seen`/`last_seen`, upsert-returning-inserted-vs-updated; `_store/` JSON fallback mirroring the reports pattern | api/_db.py | med |
| 2 | Single-flight run lock (lockfile or Postgres advisory lock) around the run so 9am + 13:00 catch-up + run-now cannot overlap | api/_monitor.py, api/_db.py | med |
| 3 | Extract `_report._enrich` into shared `api/_enrich.py`; apply to inserted delta, capped by `MONITOR_ENRICH_MAX`; record `enrich_mode` | api/_enrich.py (new), api/_report.py, api/_monitor.py | med |
| 4 | Group schema: `_normalize` gains `window_days`, `subreddits[]`, `review_brands[]`, `include_comments`, `sinks[]`; add `cashfree_mentions` builtin (window 2, include_comments); delete `_monitor.py` hardcoded constants | api/_groups.py | low |
| 5 | Thread `days`/`limit` into `lookup()` and into the SQLite cache key (a 2-day and a 10-day scan of the same keyword must not collide in the 30-min TTL) | api/_signals.py | med |
| 6 | UTC/IST timestamp contract: store `post_ts` UTC ISO-8601; compute `scan_date` + window boundaries in IST; anchor relative-date parsing to run start | api/_monitor.py, api/_reviews.py | med |
| 7 | `MONITOR_BUDGET_S` with per-track deadlines + politeness gaps; parallelize within tracks (keyword-level futures), never LinkedIn in a parallel pool | api/_monitor.py | med |
| 8 | Sheets becomes delta export: push only rows inserted this run; `MONITOR_SHEET_SAFETY=1` keeps a capped 500-id column-A read for a two-week burn-in, then delete | api/_sheets.py, api/_monitor.py | low |
| 9 | Run summary into the reports table (per-track status, `fetch.status()` snapshot, `sheets_result`, `runtime_version`) | api/_report.py, api/_db.py | low |
| 10 | Resend silent-zero alert (a track that historically returns rows yields zero); 13:00 launchd catch-up; hosted Vercel-cron staleness watchdog | api/_email.py, launchd/, api/ (cron) | med |
| 11 | Idempotency test: run twice, assert zero duplicate inserts + zero duplicate sheet rows | tests/ | low |

### Phase 2 — Source breadth and UI surface
Goal: the working sources become first-class Signals sources and show up in-app.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | Register `trustpilot`, `quora`, `reddit_comments` in `_KEYWORD_ADAPTERS` + `_KEYWORD_SOURCES` + `sources_status()`; `capterra` gated on a passing live smoke; `g2` registered only when a licensed-API key is set (a `_g2_api` adapter, not a scraper) | api/_signals.py | med |
| 2 | Carlsen tiers: trustpilot 4, capterra 3, quora 3, g2 2 in SOURCE_SAFETY + SOURCE_HOSTS | api/_carlsen.py | low |
| 3 | Quora curated question-URL mode (server-rendered pages have real answer dates); honest `needs_connection` until a paid discovery key exists | api/_reviews.py, api/_groups.py | low |
| 4 | `GET/POST /api/monitor` (Flask + Vercel handler cloned from report.py; POST CRON_SECRET-gated, local-only) | api/monitor.py (new), app.py | low |
| 5 | Monitor panel inside ReportsTool: health strip (blocked distinct from quiet), staleness banner, sentiment KPIs + model/lexicon badge, comment/review kinds with parent-thread context, per-tab sheet deep links (gid), run-now (local) / disabled-with-tooltip (hosted), fix stale "8am" copy to 9am, IG/FB descope stated in panel copy | index.html | med |
| 6 | Register only verified sources in SIG_META / SIG_ORDER / UNIT_META.keyword.sources / ACT_ICON (add `review` kind) | index.html | low |

### Phase 3 — Config and moment-marketing hardening
| # | Change | File | Risk |
|---|---|---|---|
| 1 | `GET/POST /api/groups` (CRON_SECRET-gated writes) + in-app group editor panel (read-only on hosted); hand-editing groups.json documented as the interim path | api/groups.py (new), app.py, index.html | med |
| 2 | Competitor-negative velocity spike detection (vs trailing 7-run average) + Resend alert. This is what turns ask 4 from "sentiment rows" into "moment marketing" | api/_monitor.py, api/_email.py | med |
| 3 | Sheet tab rotation: YYYY-MM suffix at a 4000-row threshold; drop the burn-in safety read | api/_sheets.py | low |
| 4 | `monitor_mentions` retention policy (delete or cold-archive rows with `last_seen` older than 180 days; Neon free tier has a storage ceiling) | api/_db.py | low |
| 5 | Document every new env var in .env.example + README; stamp/hash the copied .env in install.sh so env drift is detected, not just code drift | .env.example, README.md, launchd/install.sh | low |
| 6 | Complete fixture / injection / dedup / watchdog tests | tests/ | low |

### Phase 4 — Gated decisions (after ~2 weeks of telemetry)
Two source decisions are already locked (not open):
- **G2 = licensed data API (DECIDED).** Phase 4 work here is procurement plus a
  `_g2_api` adapter keyed on the licensed endpoint, not a scraper. G2 is absent
  from the monitor until the key is set.
- **Instagram / Facebook = descoped (DECIDED).** No track. Stated in panel copy.

Remaining open calls, each after telemetry:
- **Quora discovery:** paid Brave/Bing search key vs stay on curated URLs.
- **Hosted scanning fallback** for keyless tracks (Vercel cron) vs accept missed
  days when the Mac is off.
- **Reports to Monitor rename.**
- **Per-source keep/descope** on a below-30% soak success rate.

---

## 6. Data model

**`monitor_mentions`** (system of record):

| Column | Notes |
|---|---|
| group_id | part of PK |
| dedup_key | part of PK; kind-aware: `post:<id>` / `comment:<id>` / `review:<id>` / `answer:<id>`, never URL alone |
| kind | post / comment / review / answer |
| platform | reddit / quora / trustpilot / capterra / g2 / x / linkedin |
| brand, keyword | which brand/keyword matched |
| text, url, author | |
| post_ts | UTC ISO-8601 (the "answer date") |
| rating | review sites only |
| sentiment, company, enrich_mode | from shared `_enrich`; enrich_mode = model / lexicon |
| first_seen, last_seen | run timestamps; satisfy answer-date + thread-updated |
| run_date | IST scan date |

**Google Sheet** (delta export): one tab per group (write the group to tab
mapping down; do not silently reorganize the team-facing sheet). Header adds
`first_seen`, `run_date`. Capture `ws.id` (gid) at push time for UI deep links.

**Run summary** = a normal reports-table row with per-track health, `fetch.status()`
snapshot, `sheets_result`, `runtime_version` embedded in the payload, so ReportsTool
serves it unchanged.

---

## 7. New env vars (document all in .env.example + README)

| Var | Purpose |
|---|---|
| GOOGLE_SA_JSON or GOOGLE_SA_KEY | Service-account auth for Sheets |
| GTMSTACK_SHEET_URL | **Required**; fail loudly if unset (no auto-create + public-share) |
| MONITOR_BUDGET_S | Wall-clock budget for the whole monitor run |
| MONITOR_ENRICH_MAX | Cap on LLM-enriched rows per run (default ~60) |
| MONITOR_SHEET_SAFETY | Two-week burn-in flag for the capped column-A read, then remove |
| BRAVE_SEARCH_KEY or BING_SEARCH_KEY | Quora discovery (Phase 4 gated) |
| G2_API_KEY | Licensed G2 data API (decided). G2 source stays absent until this is set |
| MONITOR_ALERT_EMAIL | Recipient for silent-zero + staleness + velocity alerts |
| CRON_SECRET | Already exists; now also gates POST /api/monitor and /api/groups |

Note: install.sh copies .env into ~/.gtmstack/app, so a new secret needs a
re-install. The version stamp must cover .env drift, not just code drift.

---

## 8. Test strategy (repo uses stdlib unittest in tests/)

- `test_fetch.py`: extend with a `fail_status={403}` case (breaker trips, archive
  serves).
- `test_reviews.py` (new): saved HTML fixtures for TrustPilot `__NEXT_DATA__`,
  Capterra, G2 JSON-LD; assert date parse + row shape. Fixtures mean the scrapers
  are tested without hitting the live, blockable sites.
- `test_monitor.py` (new): idempotency (run twice, zero dup inserts + zero dup
  sheet rows), kind-aware dedup (two comments in one thread stay two rows),
  cross-group dedup (same URL in two groups lands in both tabs), window boundary
  math in IST, single-flight lock.
- `test_carlsen.py`: extend with the new source tiers; assert LinkedIn is never
  scheduled inside a parallel pool.

---

## 9. What changes vs the first pass, in one line

The first pass built a parallel scraper-plus-sheet system that returned zero and
had no memory. This plan deletes the parallel copy, routes every source through
the existing resilient transport + cache + Carlsen king-safety, makes a Postgres
table the system of record (so dedup and answer-dates survive a sheets outage),
reuses the model-based enrichment already paid for, and refuses to render a
silent block as a quiet day. Instagram and Facebook are formally descoped;
X + LinkedIn carry the moment-marketing ask on the compliant channels.
