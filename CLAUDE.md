# CLAUDE.md — GTMstack

Operating manual for this repo. Read before editing. No em dashes in code, copy, or this doc.

## Deploy / repo

- Accounts (passwordless magic-link) shipped and LIVE. Flow: `api/_accounts.py` (controller) + `api/auth.py` (Vercel route) + Flask routes in `app.py`, fronted by a Frappe-styled sign-in modal + user chip + Your-runs + welcome in `index.html`. Sessions are stateless HMAC (`api/_auth.py`), so sign-in needs only `APP_SECRET` (already set on Vercel). `DATABASE_URL` (Neon) adds the users + runs tables (`api/_db.py`); `RESEND_API_KEY` delivers links (`api/_email.py`). Local dev uses `GTMSTACK_DEV=1` to return the link on-screen (never in production). To fully activate the hosted sign-in the user must add `RESEND_API_KEY` (deliver links) and optionally `DATABASE_URL` (history); without them sign-in renders and the endpoints work but a link cannot be delivered. Tests: `tests/test_auth.py` (12).
- GitHub: `github.com/mothivenkatesh/gtmstack` (PRIVATE), remote `origin`, branch `main`. Local folder is still `yt-transcript-app`.
- Secrets never leave the machine: `.env` (RunPod LLM key, cookie paths) is gitignored; LinkedIn cookies live OUTSIDE the repo at `~/.gtmstack/li_cookies.json`. `.gitignore` also blocks `*cookies*.json`, `*.session.json`, `.gtmstack/`, `*.db`, `api/_store/`, `__pycache__/`.
- Vercel: LIVE at **https://gtmstack-ashen.vercel.app** (project `gtmstack` under account `venkataachalu-gmailcoms-projects`, linked to the GitHub repo so a push auto-deploys). Deployed via `vercel --prod` from the project dir. Always deploy from the project dir, never `~` (Vercel will refuse a home-dir deploy; the `--yes` flag does not override that guard).
- Vercel deploy gotchas hit and fixed (keep these): (1) each `api/*.py` handler now does `sys.path.insert(0, dirname(__file__))` before `from _X import` — Vercel's launcher does NOT put the handler's dir on sys.path, so sibling `_*.py` imports raised `ModuleNotFoundError` (every function 500'd) until this was added; `vercel.json` also sets `includeFiles: "api/_*.py"` per function to guarantee bundling. (2) `framework` pinned to `null` in vercel.json so Vercel does not apply a Flask preset (the api/ files are BaseHTTPRequestHandler functions, not a WSGI app). (3) `mailguard>=0.3.0` commented out of requirements.txt — only 0.1.0 is on PyPI, so the pin was unsatisfiable; NoBounce degrades to "mailguard not installed" on the deploy (guarded import). (4) `.vercelignore` keeps `.env`, cookies, internal docs (CLAUDE.md/RISK.md) and app.py off the public deploy.
- Serverless caveats (by design): LinkedIn followers do NOT resolve (no local Chrome profile, datacenter IP checkpoints), some Signals sources degrade from datacenter IPs, NoBounce needs mailguard 0.3.0 on PyPI, and LLM-deep modes need env vars set in Vercel project settings (rotate the RunPod key first). GitHub Signals, YouTube Transcript, Synthetic Persona, the heuristic engines, and the SPA all work live. Verified post-deploy: /api/signals /api/persona /api/plays all 200; /api/clean 501 (POST-only, expected); /.env /CLAUDE.md /RISK.md /app.py all 404.

## What this is

GTMstack is a multi-tool app shell: the GTMstack for AI-native companies and agents. A left dark sidebar navigates between tools. Each tool is a self-contained workspace, and every tool is built to be callable by an API or an AI agent, not only clicked by a human. Think "Cursor for GTM."

Home plus four tools (NAV order: home, persona, extract, signals, clean). Home is the default landing tab, not a tool:

| Tool | id | Status | One-liner |
|---|---|---|---|
| Home | home | live | GTM use-case templates that open a tool prefilled and already run |
| Synthetic Persona | persona | live | See how developers react to your copy |
| YouTube Transcript | extract | live | Pull clean text out of any YouTube video |
| Signals | signals | live (single-tenant) | The data intelligence layer for AI agents |
| NoBounce | clean | live | Validate and de-dupe an email list into agent-ready rows |
| Competitor Intel | competitor | live | Share of voice + positioning vs your competitors (reuses the `competitor_intel` play) |
| Connectors | connectors | placeholder | CRM / sequencer / messaging integrations, all Phase-2 stubs (no OAuth wired) |

**Home (templates):** a gallery of `HOME_TEMPLATES` cards, each mapped only to a live capability (no roadmap cards). A card calls `launch(toolId, payload)` in `App`, which stamps a `seed` (`{tool, payload, n:Date.now()}`) and switches tabs. Every tool takes a `seed` prop and applies it via `useEffect([seed])` guarded on `seed.tool`: Persona via `preview({text,type})`, Extract via `run({url})`, Clean via `run({text})`, Signals via a dedicated `seedLookup` that fetches with explicit params (never waits on async state). The `n` timestamp makes a repeat click re-fire. This is the "pre-fill + run live" model: one click shows real output. The four data plays mirror Clay/Crustdata work (find the people / map the account / catch the signal / clean the list); Persona and Extract are native research plays. Audience Corpus (a roadmap-only dummy view) was removed.

## Signals (current focus)

**Definition:** Signals is the data intelligence layer for AI agents. Give it a name, handle, or email and it returns, in real time, who that person is and what they did most recently across GitHub, Reddit, LinkedIn, X, and YouTube. A human can look someone up from the UI; an agent can call the same endpoint. The same surface also maps a company (its footprint plus the people who work there) and tracks a keyword (a live, time-sorted mentions feed). Two sources are zero-config and live out of the box: GitHub (public REST API) and YouTube (public pages, no key). The session-gated sources (LinkedIn, X) and the OAuth one (Reddit) degrade to a clean needs_connection card when no creds are present; none of them is removed.

**Confirmed scope, do not silently change:**
- Lookup units = Person (default), Company (footprint plus the people who work there), and Keyword (a live, merged mentions feed).
- Delivery = the UI plus an agent-callable API. Single lookups run inline; bulk lists and webhook deliveries run as async jobs (`/api/jobs`) you can poll, webhook, or export to CSV/JSON.
- Posture = Sellable product (external users will query it). This raises the bar: multi-tenant, credential pools, legal review before any external launch.

**Wedge:** freshness plus dev-native channels. Not "download 50k rows like Crustdata or moltsets," but "what did THIS person post today, right now." Bulk and export exist as delivery conveniences (a capped batch of fresh reads), not as a stale nightly dump. One source being quiet never blocks the rest.

### Lean canvas (condensed)

| Block | Notes |
|---|---|
| Problem | Bulk-export enrichment is stale and company-centric. Agents need fresh, per-person context across the channels devs actually use. |
| Solution | Real-time per-source adapters (Reddit, LinkedIn, X) into one normalized footprint card. Cached briefly, force-refreshable. |
| UVP | Real-time person intelligence your agents can call. Fresh, not a nightly dump. |
| Unfair advantage | Dev-native channel coverage + live read + an agent-callable surface. The hard part is the credential/proxy infra, which is also the moat. |
| Segments | AI-native GTM teams and the agents they build; founders doing manual prospect research. |
| Channels | GTMstack shell now; an MCP server + API later. |
| Revenue | Usage-priced lookups or seats (Phase 2). |
| Cost | Residential proxies + warmed account pool + infra are the real COGS. |
| Key metrics | Fresh-lookup success rate per source, latency, cache hit rate. |
| Riskiest assumption | That we can keep LinkedIn/X reads alive at scale without bans. This is the Phase-2 gate, not solved yet. |

## NoBounce (Clean Data engine, id `clean`)

**Definition:** Clean Data is the deliverability layer. Paste or upload a messy contact list (CSV, TSV, or one-per-line; addresses are scanned out of any column by regex, so format does not matter) and it returns one agent-ready row per address: `valid` (boolean), `verdict` (deliverable | risky | undeliverable), score, normalized form, domain, mx_ok, and the disposable / role_based / free_provider / typo flags. The list is de-duplicated case-insensitively first. A human cleans a list from the UI; an agent POSTs the same endpoint and branches on `valid` or `verdict`.

**Engine:** powered by `mailguard` (the same 9-layer validator published on PyPI), called via `validate_bulk_sync`. It never raises on a bad address. **SMTP probes are OFF by default** (port 25 is blocked on serverless, and the MX + heuristic layers separate deliverable from junk without ever touching a recipient's mailbox); `check_smtp=True` turns on the RCPT probe locally. First call has a ~20s mailguard cold-start (loads the disposable list, warms DNS); warm calls are fast.

**Two partitions, do not conflate (this caused a real double-count bug):**
- `valid` (is_valid) is a 2-way split: true spans the deliverable AND risky verdicts; false is undeliverable. `summary.valid` counts it; `summary.invalid` is the rest.
- `verdict` is the strict 3-way split in `summary.by_verdict`: deliverable / risky / undeliverable. These sum to `summary.unique`.
- The UI KPI cards show the 3 verdict buckets (mutually exclusive) plus duplicates_removed. The "Sendable" toggle and the `only=clean` download both mean `valid` (deliverable + risky, i.e. everything except undeliverable). Never label the `valid` count "Deliverable" — that is the misnomer that double-counted risky rows.

**Caps:** `CLEAN_MAX_EMAILS` (default 1000) truncates; `summary.truncated` flags it.

## Architecture

Dual deploy, one core:
- Local dev: Flask (`app.py`) serves `index.html` and the `/api/*` routes.
- Production: Vercel serverless functions in `api/*.py` (BaseHTTPRequestHandler).
- Shared logic: `api/_*.py` modules are imported by both, so behavior is identical.

Frontend: modular native ES modules under `js/` (no build step; Preact 10 + htm via esm.sh). `index.html` holds ONLY the CSS + `<script type="module" src="/js/app.js">`. Each tool is a self-contained module exporting its components AND a `manifest` (`{id, icon, name, desc, component}`), the standard interface every tool exposes; `js/app.js` builds `TOOLS`/`NAV` from the imported manifests, so adding a tool = one module + one entry in `MODULES`. Module map: `js/core.js` (preact/htm runtime re-exports, `API_BASE`, `ICONS`/`Icon`, shared `Picker`/`DateRange`, misc helpers) ← imported by everything; tools `js/{home,persona,extract,signals,clean,competitor,tables,reports,connectors}.js` (reports.js is surfaced as **Routines**: a Claude-Code-style list of the scheduled agents — daily briefs 08:00 IST, competitive monitor 09:00 IST, monitor catch-up 13:00 IST, Vercel staleness watchdog — each with schedule, last-run status dot, Run now where runnable, and a detail view; `RoutinesTool` is the shell, `BriefsPanel`/`MonitorPanel` are the per-routine outputs; the tool id stays `reports` and the engines/endpoints are unchanged); `js/plays.js` (PlayRunner + per-play result renderers; imports `PersonaResult` from persona.js — tools never import plays.js except home/competitor, keeping the graph acyclic); `js/auth.js` (magic-link modal, runs, welcome); `js/app.js` (shell + registry + mount). HomeTool receives the registry as a `tools` PROP (do not import app.js from a tool — that is a cycle). Tools stay mounted and toggle via `display:none` to preserve per-tool state. `API_BASE` is `http://localhost:5000` when opened from `file:`, else same-origin.

| Path | Role |
|---|---|
| index.html | Whole UI (shell + 5 tools), Preact + htm |
| app.py | Flask dev server + route wrappers |
| api/_signals.py | Signals engine (adapters, cache, orchestrator) |
| api/signals.py | Vercel handler for /api/signals |
| api/_jobs.py | Async job store (queue, bulk fan-out, webhook, CSV/JSON export) |
| api/jobs.py | Vercel handler for /api/jobs |
| api/_clean.py | NoBounce engine (mailguard validation, dedupe, CSV/JSON serialisers). Display name is NoBounce; the tool id stays `clean` |
| api/clean.py | Vercel handler for /api/clean |
| api/_core.py, api/_personas.py | Transcript + persona cores |
| api/transcript.py, api/persona.py | Vercel handlers |
| api/_plays.py | Plays engine: chains tool cores into one inline multi-step run |
| api/plays.py | Vercel handler for /api/plays |
| api/_teardown.py | Creator-teardown engine (Signals posts -> pattern extraction); called by the `creator_teardown` play, no standalone route |
| api/_llm.py | One provider-agnostic `chat()` shared by the persona + teardown engines: OpenAI-compatible endpoint (RunPod/OpenRouter/local) if `GTMSTACK_LLM_BASE_URL` set, else Anthropic, else `NoModel` (caller runs its heuristic). Strips `<think>` blocks |
| api/_reliability.py | The trust primitive the content agents share: `confidence(posts)` (score+band+basis from volume + engagement coverage) and `ground(items, posts)` (validate per-insight citations, attach evidence snippets, flag ungrounded). Enforces the "every insight traces to a post" guardrail in code |
| api/_util.py | Tiny shared helpers: `eng_num` / `eng_str` / `eng_total` (engagement-count parsing), used by the three content engines |
| api/_trends.py | Trend & Top-Voice engine (agent 14): Signals keyword feed -> velocity rank (engagement/hr, shown) -> top voices -> grounded LLM/heuristic synthesis. Called by the `trend_discovery` play |
| api/_content_perf.py | Content Performance engine (agent 12): your own posts -> grounded format winners + themes + best-time windows, plus a local `_store/` snapshot for a cross-run engagement trend (degrades to no-history on serverless). Called by the `content_performance` play |
| api/_fetch.py | Resilient transport: the uninterrupted-scrape cascade every adapter shares through `_signals._get`. Layer 3 curl_cffi fingerprint, 4 per-host backoff (honours Retry-After), 5 BYO proxy rotation (`GTMSTACK_PROXIES`), 6 `archive` fallback hook, 7 circuit breaker + `status()`. Pure Python, no model calls. Compliant-only: no stealth browser, no bot-detection bypass |
| api/_compete.py | Competitor Intelligence engine: scans your brand + competitors in PARALLEL (stdlib threads) across the Signals keyword feed, returns share of voice, a market-positioning quadrant (volume x engagement), channel breakdown, top voices, and influencer overlap. Built from public posts, not scraped engager lists (IG/LinkedIn-engager excluded). Drives the `competitor_intel` play, surfaced as the standalone "Competitor Intel" sidebar tool |
| tests/test_fetch.py | 17 stdlib-unittest tests for `_fetch` (positive + negative: retries, Retry-After, breaker trip + fast-fail, archive fallback, proxy rotation/cooldown). Transport patched, sleep neutralised, runs in ms. `python tests/test_fetch.py` |

### Signals engine model
- One adapter per source: `_github`, `_reddit`, `_linkedin`, `_x`, `_youtube`. Each returns a normalized block via `_src(platform, status, ...)`.
- A source failing never breaks the card. Status is one of `ok | needs_connection | not_found | error`; the UI renders an empty-state per status.
- Real-time first, with a SQLite cache (30-min TTL; `force` bypasses). The `cached` flag is surfaced in the UI.
- `lookup(query, sources, handles, force, unit)` is the orchestrator. It dispatches by `unit`: person -> footprint card, company -> footprint plus a GitHub-org people roster, keyword -> a merged, time-sorted mentions feed. `sources_status()` reports per-source readiness.
- Async jobs (`api/_jobs.py`): a SQLite-backed store runs single or bulk lookups off the request. Under Flask a small thread pool drains the queue; on serverless `SIGNALS_SYNC_JOBS=1` forces inline processing, since a background thread cannot outlive the response. A webhook URL gets the finished result POSTed to it; results export to CSV or JSON.

### Plays (composite, agent-callable)
A play chains existing tool cores into ONE run an agent can call and branch on. `api/_plays.py` holds a `PLAYS` registry (`{id: {meta, run}}`); each `run(input)` calls engines in sequence and returns a `steps[]` array, so a caller reads the final result or inspects any stage. It runs INLINE (the response already carries every step), shared by Flask and the Vercel handler like the other tools. Each play also carries an `input` schema (`[{key, label, required, default, options}]`); the UI `PlayRunner` renders its form from that schema and renders each step's output by `tool` (`extract` -> transcript preview, `persona` -> PersonaResult, `signals` -> SignalsEvidence, `teardown` -> TeardownResult). Adding a play is one registry entry plus one `PLAY_CARD`; a new output shape needs a small renderer.

Content axis ships two plays today, because only that axis composes cleanly (the four tools are otherwise terminal):
- `video_messaging` (transcript -> dev-persona reactions).
- `creator_teardown` (Signals person posts -> a model names the hooks, formats, themes, cadence, and the one move to steal). The teardown engine reuses the persona LLM client path (`Anthropic()` on `ANTHROPIC_API_KEY`, model `GTMSTACK_MODEL`, JSON out) and degrades to a transparent heuristic when no key is set, so the step always completes.

The contact-axis plays (prospect, enrich, validate, route to CRM/Slack) each need a connector none of the tools provide, which is the Phase-2 trigger: stand up Activepieces (MIT core: workflow engine + REST + webhooks + pieces, self-hosted, not on Vercel) as the orchestration backend and expose its runs through the same `/api/plays` shape. Embedding, white-label, and SSO in Activepieces are enterprise-licensed, so treat them as a paid dependency, not part of the MIT path.

### Endpoints
- `GET /api/signals` returns `{sources: {github, reddit, linkedin, x, youtube}}` readiness.
- `POST /api/signals` body `{query, sources?, handles?, force?, unit?}` returns the footprint (person/company) or feed (keyword). `unit` defaults to `person`.
- `POST /api/jobs` body `{kind?, unit?, query|queries, sources?, handles?, webhook?}` submits an async job. Returns 200 plus a finished job when inline, else 202 plus a queued job to poll. `kind:"bulk"` with `queries` (an array, or a newline/comma string) fans out a list.
- `GET /api/jobs` lists recent jobs. `?id=X` returns one job. `?id=X&format=csv|json` exports the finished result as a download.
- `POST /api/clean` body `{text?, emails?, check_smtp?}` validates + de-dupes a contact list and returns agent-ready rows. `?format=csv|json` (with optional `?only=clean`) returns the result as a download instead.
- `GET /api/plays` lists the composite plays (metadata only). `POST /api/plays` body `{play, input}` runs one inline and returns `{play, ok, steps:[{tool, label, status, summary, output, error}]}`. A failing step lands as `status:"error"` in the array and the call still returns 200; an unknown play id is a 404.

## Run it
```
python app.py            # http://localhost:5000
```
Env vars (all optional, they act as feature flags). `app.py` loads a gitignored `.env` at the project root on startup (no dependency), so creds persist across restarts instead of being re-exported by hand:

| Var | Effect |
|---|---|
| GITHUB_TOKEN | Free read-only token; lifts GitHub from 60 to 5,000 reads/hour. GitHub works with no token at all. |
| LINKEDIN_PROFILE_DIR | Decrypt li_at + JSESSIONID from a local Chrome profile (auto-connect LinkedIn) |
| LI_AT + LI_JSESSIONID | Supply LinkedIn cookies directly |
| LINKEDIN_COOKIES | Path to a cookies JSON file |
| X_PROFILE_DIR | Decrypt auth_token + ct0 from a local Chrome profile so X reads the real timeline via the authenticated GraphQL API (else public syndication, usually 429 from servers) |
| REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET | Light up Reddit via the official OAuth app (free) |
| WEBSHARE_PROXY_USER/PASS or YT_PROXY | Residential proxy for translation + scraping |
| SIGNALS_SYNC_JOBS | Run jobs inline instead of on a worker thread. Set to 1 on serverless (api/jobs.py does this). |
| SIGNALS_WORKERS | Job worker-thread pool size under Flask (default 4) |
| SIGNALS_MAX_BULK | Cap on queries per bulk job (default 50) |
| SIGNALS_JOBS_DB | Path to the jobs SQLite file (default: a temp dir) |
| SIGNALS_X_QID_TTL | Seconds to cache discovered X GraphQL query ids (default 21600 = 6h) |
| YT_COOKIE | Override the YouTube consent cookie (default bypasses the EU consent wall; YouTube needs no key) |
| CLEAN_MAX_EMAILS | Cap on addresses validated per Clean Data call (default 1000) |
| CLEAN_CONCURRENCY | mailguard concurrency for Clean Data (default 100) |
| CLEAN_TIMEOUT | Per-address validation timeout in seconds (default 8) |

## Source nuances (hard-won)
- GitHub: public REST API, reads live from any IP with zero credentials (60 req/hour). A free read-only `GITHUB_TOKEN` lifts that to 5,000/hour. `/users/{h}` for the profile, `/users/{h}/events/public` for recent activity. The one source that works out of the box, which is why it leads the default fan-out.
- Reddit: unauthenticated `.json` endpoints 403 from datacenter/flagged IPs. The clean path is the official OAuth app-only flow (register a free "script" app, 100 req/min). Engine tries OAuth, falls back to public, degrades to needs_connection.
- LinkedIn: Voyager internal API. Legacy `profileView` returns 410. Modern recipe = dash `memberIdentity` (identity) + public HTML regex for the `fsd_profile` URN + `profileUpdatesV2` (posts). Cookies can be read by decrypting a local Chrome profile (DPAPI + AES-GCM; Chrome 130+ prepends a 32-byte SHA256 domain hash to the plaintext, strip it).
- X: two paths. With a connected session (`X_PROFILE_DIR` -> a logged-in Chromium profile) it reads the real timeline via the authenticated GraphQL API (`UserByScreenName` then `UserTweets`); the web Bearer is a fixed public constant, the per-session secret is the `auth_token` + `ct0` cookie pair. Query ids rotate per X deploy, so the adapter tries a short candidate list and keeps the first that resolves, and self-heals by reading the live operation->queryId map from X's `main.<hash>.js` (cached 6h). Profile reads (`UserByScreenName`, `UserTweets`) are GET; search (`SearchTimeline`, which powers company and keyword units) must be POST with `{variables, features, queryId}` in the body, else it 404s. Without a session it falls back to the public syndication endpoint, which datacenter IPs usually get 429'd on, so it degrades cleanly.
- YouTube: keyless, reads YouTube's own public pages and parses the embedded `ytInitialData` JSON (a brace-matched extractor). No API key, no quota. A consent cookie (`CONSENT=YES+1; SOCS=CAI; PREF=hl=en&gl=US`, overridable via `YT_COOKIE`) bypasses the EU consent wall. Person/company resolve `@handle/videos` first, fall back to a channel search; keyword hits `results?search_query=` sorted by date. The grid uses TWO renderer shapes and the adapter handles both: the legacy `videoRenderer` and the newer `lockupViewModel` (videoId in `contentId`, title in `metadata.lockupMetadataViewModel.title.content`, views/age nested under `contentMetadataViewModel.metadataRows[]`). Relative times ("2 weeks ago") are parsed to an approximate epoch so the keyword feed can sort newest-first. Like GitHub, it works from any IP with zero credentials, so it joins GitHub in the default fan-out.

## Guardrails

**Security**
- Cookies, li_at, JSESSIONID are secrets. Never commit, never print in full.
- Use a burner LinkedIn account for any aggressive testing. Single-cookie access is fragile and LinkedIn soft-challenges under load. Do not hammer it during dev.

**Legal and Phase-2 gates (clear before any external launch)**
- Multi-tenant isolation + auth + per-user rate budgets.
- Warmed burner-account pool + residential proxy rotation. Single cookie or single IP gets banned at scale. This is the real moat and the real cost.
- PII handling + lawful-basis review (GDPR, India DPDP), ToS / CFAA posture, subject opt-out + deletion path.

**Design**
- Frappe Design System tokens (light surface + dark `--menu-bar` sidebar). Body font is Circular Std (proprietary, self-hosted from `/fonts` as woff2, weights Book/Medium/Bold; a 600 request maps to Bold), code font is IBM Plex Mono (Google Fonts). Circular Std is a licensed Lineto font: self-hosting on the public Vercel deploy redistributes it, which needs a Lineto webfont license.
- Icons are LINE style on a 3-tier size scale (user decision, Jul 2026; supersedes the earlier solid-icon rule): 24px page-level (topbar tool icon), 20px nav/toolbar (app sidebar), 16px dense inline (grid headers, menus, chips, buttons). Source: Material Symbols SHARP ligatures at wght 300, GRAD 200, opsz 24, FILL 0 (the `.msi` class). The `Icon` component SNAPS the legacy size prop to the nearest tier (>=22 to 24, >=15 to 20, else 16), so call sites keep their relative hierarchy without pixel-exact sizes. Brand logos (github/linkedin/reddit/x/youtube) and the chess knight have no Material equivalent, so they stay Phosphor-via-Iconify in the line (regular) weight, also at 24px. One central ICONS map drives `Icon`: an id containing ':' renders through iconify-icon, anything else as a Material ligature. Validate any new ligature name against the Material Symbols codepoints file before adding it (an invalid name renders as raw text). htm passes unquoted attribute values as STRINGS; never do arithmetic on a prop without coercing first (a "15"+2 concat once blew every icon up to 152px).
- Floating app-frame (desktop >900px): the sidebar and `.main` are `position:fixed` rounded panels inset by `--gap` on the `--app-canvas`; `body{overflow:hidden}` so the WINDOW does not scroll, `.main{overflow:auto}` is the scroll container and the `.topbar` sticks to the panel top. Consequence: never `window.scrollTo` to move content (scroll `.main` or use `scrollIntoView`); a full-height tool must size to `calc(100vh - var(--gap)*2 - 56px)` (see `.tbl-shell`), not `100vh - 56px`. Below 900px the frame is dropped (media query resets to static flow + body scroll).
- Grouped controls: reuse the shared `Picker` (labelled button + click-away popover; `children` is a render fn given a `close` callback) and `DateRange` (presets Any time / 24h / 7d / 30d / 90d + custom from/to; value is `{preset}` or `{preset:'custom',from,to}`; filter with `inDateRange(ts, value)`). Signals sources, Reports/Monitor group, and any new multi-choice control should be a `Picker`, not a chip row. Tables date-column filters use a `{from,to}` object (see `filterActive`/`filterLabel` and `TYPE_META.date.matches`). Do not hand-roll a new dropdown.
- No em dashes in UI copy. Lead with the answer. Plain language so a non-technical founder gets it.
- Text-overflow safety on cards (`overflow-wrap: anywhere`, `min-width: 0` on flex/grid children). Check WCAG contrast.

## Build plan, this change (Signals rename + reposition + solid icons)

Goal: rename "Live Signals" to Signals, reframe it as the data intelligence layer for AI agents, and switch the whole app to solid icons.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | Add Iconify web component script | index.html head | CDN async first-paint flash, acceptable and cached after |
| 2 | Replace ICONS map with validated Phosphor ids; rewrite `Icon` to render `<iconify-icon>` | index.html | Preact custom-element rendering + color inheritance, verify in preview |
| 3 | Rename tool: TOOLS.signals name to "Signals" + new desc; `LiveSignals` to `SignalsTool`; mount; section comment | index.html | low |
| 4 | Reposition hero copy + pills to agent-data-layer framing, keep the simple search box | index.html | low |
| 5 | SIG_META uses brand logos (reddit/linkedin/x); add `reddit` key to icon map | index.html | low |
| 6 | "Live Signals" to "Signals" in backend docstrings | api/_signals.py, api/signals.py | none |

Icon set is pre-validated against the Iconify Phosphor API. `radar` maps to `ph:broadcast-fill` (Phosphor has no `radar-fill`).

Out of scope now (roadmap): MCP server surface, proxy pool + warmed account pool, more sources, usage pricing. Registering a Reddit OAuth app lights up Reddit live whenever creds are added.

Verification: load the preview, confirm icons render solid including brand logos, Signals renders with the new copy, a lookup still returns cards, no console errors.

## Build plan, this change (Person/Company/Keyword units + async delivery)

Goal: add Company and Keyword lookup units alongside Person, and add agent-callable delivery (API snippet, webhook, bulk, CSV/JSON export).

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `lookup` dispatches by `unit`; add `_lookup_company` (footprint + GitHub-org people roster) and `_lookup_keyword` (merged, time-sorted feed); cache key is prefixed by unit | api/_signals.py | medium, keep per-source degrade intact |
| 2 | X search via POST `SearchTimeline` + self-healing query-id discovery from `main.<hash>.js` | api/_signals.py | medium, query ids rotate |
| 3 | Async job store: SQLite queue, single + bulk fan-out, webhook on done, CSV/JSON export | api/_jobs.py (new) | medium, serverless needs SIGNALS_SYNC_JOBS=1 |
| 4 | Route wrappers + Vercel handler | app.py, api/jobs.py (new), api/signals.py | low |
| 5 | UI: unit selector, per-unit source chips, people roster, merged feed, bulk textarea, delivery panel (live curl snippet + webhook + export), job polling + status strip | index.html | medium, verify in preview |

Verified in preview: all three units render real data; company shows a 12-person roster that pivots to a person lookup; bulk submits an async job, polls to done, and exports a real CSV through `/api/jobs`; the curl snippet switches endpoint by delivery method; no console errors.

## Build plan, this change (YouTube source + Clean Data tool + rename)

Goal: add YouTube as a keyless Signals source, add a fifth tool (Clean Data) that turns a messy email list into agent-ready rows, rename Content Extractor to YouTube Transcript, and remove redundant shell chrome. Driven by six explicit asks; decisions: YouTube now / Google later (deferred until a Search API key exists), mailguard shipped as its own Clean Data tool (not folded into a profile), LinkedIn kept connect-gated (not removed).

| # | Change | File | Risk |
|---|---|---|---|
| 1 | YouTube adapters (`_youtube`, `_youtube_search`, ytInitialData + lockupViewModel parsers) into person/company/keyword registries; `sources_status()` reports youtube ready | api/_signals.py | medium, YouTube's grid renderer shape rotates |
| 2 | Wire YouTube into the Signals UI: SIG_META/SIG_ORDER, source chip, parseQuery URL branch, hero/placeholder/footer copy | index.html | low |
| 3 | Clean Data engine: extract_emails regex, dedupe, mailguard validate_bulk_sync, summary (valid/invalid + by_verdict), CSV/JSON serialisers | api/_clean.py (new) | low |
| 4 | Routes: Flask `/api/clean` + Vercel `api/clean.py`; vercel.json maxDuration; requirements add mailguard | app.py, api/clean.py (new), vercel.json, requirements.txt | low |
| 5 | Clean Data UI tool: upload/paste, verdict KPI cards, Sendable toggle, search, CSV/JSON download, agent curl panel | index.html | low |

Verified in preview: Clean Data runs the sample to Deliverable 1 / Risky 2 / Undeliverable 2 / Duplicates removed 1 (verdict buckets sum to the 5 unique), the Sendable toggle filters to the 3 valid rows, per-row pills (typo / disposable / role / verdict) are accurate, downloads build client-side, no console errors. A YouTube profile lookup renders the full card live (Marques Brownlee, @mkbhd, 21M subscribers, 8 fresh videos tagged Video). Fixed during verification: the KPI "Deliverable" card was reading `summary.valid` (3) while "Risky" read the verdict bucket (2), double-counting the risky rows (3+2+2=7); now every count is verdict-pure and the backend field is honestly named `valid`.

## Build plan, this change (Home templates + remove Audience Corpus)

Goal: add a Home landing tab (first in NAV) that is a gallery of GTM use-case templates, and remove the Audience Corpus roadmap view (dummy content, no working feature). Decisions: template action = "pre-fill + run live" (a card opens the matching tool with a real example already loaded AND executed); Audience Corpus = removed entirely.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `seed` + `launch(toolId,payload)` lifted into `App`; default tab now `home`; every tool takes a `seed` prop and applies it via `useEffect([seed])`. Persona `preview` refactored to accept `{text,type}`; Signals gained `seedLookup` (explicit-params fetch). | index.html | low |
| 2 | `HomeTool` + `HOME_TEMPLATES` (6 cards: 3 Signals units, Clean, Persona, Extract), grounded in Clay/Crustdata plays, mapped only to live tools | index.html | low |
| 3 | Registry: add `home` to ICONS (`house`) + TOOLS + NAV-first; remove `corpus` from TOOLS/NAV and the `database`/`trending`/`wand` icons | index.html | low |
| 4 | Remove `CorpusTool`, `PIPELINE`, `CHANNELS`, the corpus mount, the corpus CSS block, and the now-dead `.pill-violet` token; add `.home-*` CSS | index.html | low |

Verified in preview (DOM probes): Home is the default tab and renders 6 cards in a clean grid (no overflow, every card has its icon + arrow); NAV is home-first with no Audience Corpus; no `.pipe/.pstep/.chan/.pill-violet` remnants. All four "pre-fill + run live" paths fire on one click: Messaging→Persona (sample prefilled, overall 89, 5 cards), List hygiene→Clean (Deliverable 1 / Risky 2 / Undeliverable 2 / Sendable 3), Prospecting→Signals (unit Person, query `rauchg`, all 4 sources on, GitHub card live with 8 activities), Research→Extract (sample URL seeded, 5,489 words / 786 segments). No console errors.

## Build plan, this change (Plays runner)

Goal: add the composite-play layer (one agent-callable run that chains tool cores) plus a Home "Multi-step plays" card and a runner, shipping the single play that composes cleanly today (`video_messaging`: transcript to persona). Activepieces orchestration is deferred to Phase 2, since no live chain needs a connector yet.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `PLAYS` registry + `_run_video_messaging` (fetch_transcript to persona preview); `list_plays`/`run_play` never 500 (bad step is an error step, unknown id is 404) | api/_plays.py | low |
| 2 | Vercel handler + Flask routes for `GET`/`POST /api/plays`; `vercel.json` maxDuration 60 | api/plays.py, app.py, vercel.json | low |
| 3 | Extracted `PersonaResult(d)` shared render; the Persona tool now calls it (was inline) so the play reuses the exact gauge + cards | index.html | low |
| 4 | `PLAY_CARDS` + `PlayRunner` (auto-runs the sample on open, step rail, transcript preview, nested persona result); `HomeTool` gains a "Multi-step plays" section; added `arrowLeft`/`play` icons + play CSS | index.html | low |

Verified: backend imports clean, GET returns the one play, unknown id 404s. POST runs end to end live (transcript 5,489 words / 27:48 / English, then persona overall 84 / Launch-ready / 5 reactions). In preview: Home shows the plays section + card (7 cards total); clicking opens the runner, auto-runs, and renders step 1 (dot 1, "Pull transcript" summary, transcript preview) and step 2 (dot 2, persona gauge 84 + 5 reaction cards) joined by the rail; no console errors, no horizontal overflow.

## Build plan, this change (Creator teardown play)

Goal: add the second content-axis play, `creator_teardown` (a handle -> recent posts -> a model names the copyable patterns), and generalise the runner so it is schema-driven rather than hardcoded to the video play. This is the GTMstack form of Basis agent 13; the contact-axis Basis runs (agents 1-11) stay blocked on connectors (Phase 2).

| # | Change | File | Risk |
|---|---|---|---|
| 1 | New `_teardown.py`: `collect_posts` (flatten Signals `sources[].activity[].text`), `analyze` (one model call -> hooks/formats/themes/cadence/steal, heuristic fallback, never raises), `teardown` (standalone composite). Reuses the persona LLM path. | api/_teardown.py | low |
| 2 | Register `creator_teardown` in `PLAYS`: `_run_creator_teardown` = `signals(person)` then `analyze`, as two visible steps; step-1 summary reports the real per-platform post distribution, not which sources merely resolved. | api/_plays.py | low |
| 3 | Generalise `PlayRunner` to be schema-driven (renders inputs from `card.inputs`, dispatches step output by `tool`); add `SignalsEvidence` + `TeardownResult` renderers, the `creator_teardown` `PLAY_CARD`, and evidence/teardown CSS. | index.html | low |

Verified: GET lists both plays. POST `creator_teardown` (handle `levelsio`) runs end to end, ok=true, 2 steps: "8 posts: 8 youtube" then "1 patterns from 8 posts (built-in model)". In preview: Home shows both play cards; clicking Creator teardown opens the runner with `levelsio` prefilled, auto-runs, and renders the 2-step rail (both ok), the evidence block (platform chips with X/GitHub/YouTube connected and Reddit/LinkedIn flagged not-connected, 6 posts), and the teardown (engine badge, summary, "Formats they lean on" facet); empty facets (hooks/themes/steal) correctly omitted under the heuristic engine. No console errors, no horizontal overflow. Note: this env has `X_PROFILE_DIR`/`LINKEDIN_PROFILE_DIR` but no `ANTHROPIC_API_KEY`, so the teardown ran the heuristic; the live-AI path mirrors the proven persona `_llm_preview` and fires when a key is present. Local lesson: Python here is `python3.11.exe`, so `taskkill //IM python.exe` does not kill the dev server (caused a stale-bind false result); kill by `python3.11.exe` or PID.

## Build plan, this change (Play output visibility)

Goal: fix "could not see the output of multi step plays." Two causes, both real. (1) At a normal laptop viewport (720px), the header plus input card push the result stack below the fold (stack top ~423px), so after a run the user is parked on the form with the analysis off screen. (2) With no `ANTHROPIC_API_KEY` the teardown step 2 ran a near-empty heuristic (only "Post mix: N video", steal blank), so even when scrolled into view there was no payoff. The output always rendered (DOM-verified, in-viewport on a tall window); the issue was viewport plus a hollow no-key fallback, not a render bug.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `PlayRunner` scrolls the result stack into view when a result lands, guarded to fire only when its tail is below the fold. Instant (via `requestAnimationFrame`), not smooth: late-loading iconify icons shift layout and cancel a smooth scroll, leaving the page on the form. Added `resRef` + `ref` on `.stack`. | index.html | low |
| 2 | Enrich `_heuristic_teardown` so the no-key path is never empty: surface the single most-engaged post as the `steal` (the docstring already promised this; the code never did it). Added `_eng_num` (parse "42K"/"1.2M") and `_top_post`. | api/_teardown.py | low |

Verified at vh 720: open Creator teardown, auto-run completes, page auto-scrolls (scrollY 423, stack pinned to top), step 2 now visible (top 632) instead of buried at 1055; `steal` renders a concrete line ("Study your strongest post first, a youtube video (42K views): ...; copy its opening and structure, not its words"). No console errors. The full live teardown (hooks/themes/cadence) still needs `ANTHROPIC_API_KEY` in `.env`; the heuristic now degrades to something useful instead of blank.

## Build plan, this change (Bring-your-own model via OpenAI-compatible endpoint)

Goal: let the persona + teardown engines call any OpenAI-compatible model (RunPod Serverless vLLM, OpenRouter, DeepSeek, a local server), not just Anthropic, so a cheap self-hosted reasoning model can power the plays. Driver: $10 of RunPod credit + "connect a cheap Chinese reasoning model". Both engines made the same single completion call against the Anthropic SDK; this factors that out.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | New `_llm.py`: one `chat(system, user, max_tokens)` with a provider switch by env, most specific first. `GTMSTACK_LLM_BASE_URL` -> OpenAI-compatible (one `requests` POST to `{base}/chat/completions`, bearer `GTMSTACK_LLM_KEY`); else `ANTHROPIC_API_KEY` -> Anthropic; else raise `NoModel`. `configured()` for the gate. `_strip_think()` drops `<think>...</think>` so reasoning models' CoT does not pollute the JSON the caller extracts. Reasoning headroom: OpenAI path floors max_tokens at 3000 (override `GTMSTACK_MAX_TOKENS`). No new dep (reuses `requests`). | api/_llm.py | low |
| 2 | `_teardown.py` + `_personas.py`: swap the inline `Anthropic().messages.create` for `from _llm import chat`; gate the LLM attempt on `_llm.configured()` instead of `bool(ANTHROPIC_API_KEY)`. Dropped now-unused `import os` from both. JSON parse and heuristic fallback unchanged. | api/_teardown.py, api/_personas.py | low |
| 3 | `.env` commented template (no secrets) for the RunPod path: `GTMSTACK_LLM_BASE_URL` = `https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1`, `GTMSTACK_LLM_KEY`, `GTMSTACK_MODEL` (must match the deployed `MODEL_NAME`). requirements note: BYO path needs no extra dep. | .env, requirements.txt | none |

Verified (script, then live): imports resolve; no env -> `configured()` False, `chat()` raises `NoModel`, both engines run the heuristic; `GTMSTACK_LLM_BASE_URL` set -> provider `openai`, default model `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B`, `GTMSTACK_MODEL` overrides; `ANTHROPIC_API_KEY` set -> provider `anthropic`; `_strip_think("<think>noise {a[b]}</think>\n{...}")` returns just the JSON; an unreachable endpoint (127.0.0.1:9) degrades to the heuristic, no 500. Live after restart: POST `creator_teardown` (levelsio) still 200, 2 steps, engine `model`. The actual RunPod call is untested here (no endpoint deployed yet); routing, fallback, and think-stripping are. Provider precedence: OpenAI-compatible beats Anthropic when both are set.

## Build plan, this change (Reliable content agents 12 / 13 / 14)

Goal: build the three content-axis agents from the Basis product note (agent-specs.md) as *reliable* agents, where reliable means the three trust primitives in agent-specs section B: a confidence the caller can gate on, provenance (every insight traces to a source post), and an auditable reason. Only the content axis (12 Content Performance, 13 Profile Teardown, 14 Trend & Top-Voice) is buildable now; the pipeline agents 1-11 stay connector-blocked (Phase 2). Caveat held honestly: GTMstack's LinkedIn read is a personal-session cookie, which agent-specs section 14 bars for production, so these agents are reliable on X / GitHub / Reddit / YouTube; LinkedIn-at-scale is the unresolved compliance bit.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | Shared trust scaffold: `confidence(posts)`, `ground(items, posts)` (validate citations, attach evidence, flag ungrounded; coerces string items), `audit_line()`. Engagement parsing centralised in `_util.py` (3 consumers). | api/_reliability.py, api/_util.py | low |
| 2 | Agent 13 hardened: the teardown's hooks/formats/themes now come back as `{text, cites[]}`, grounded to source posts; output carries `confidence` + `audit`; thin evidence is flagged, not fabricated. Heuristic grounds the most-engaged post with a real citation. | api/_teardown.py | low |
| 3 | Agent 14 new: `trend_discovery` play. Signals keyword feed -> velocity rank (engagement/hr, shown) -> top voices (aggregated, why shown) -> grounded synthesis (topics heating, where to engage). | api/_trends.py, api/_plays.py | low |
| 4 | Agent 12 new: `content_performance` play. Own posts -> grounded format winners + themes + best-time windows (metric shown) + a local `_store/` snapshot for a cross-run engagement trend (best-effort IO, degrades to no-history). | api/_content_perf.py, api/_plays.py | low |
| 5 | UI: shared `confPill` / `groundedFacet` / `citesRow` renderers (per-insight citation chips + unverified marker + confidence pill + thin-evidence banner); `TrendResult` + `ContentPerfResult`; three new play cards; `trends` / `contentperf` step dispatch; reliability CSS (reused violet/gray tokens). | index.html | low |

Verified live (no model key, so heuristic engine throughout): GET lists 4 plays. `creator_teardown` -> confidence pill + audit + "unverified" on the ungrounded format, 0 citations only because that run's posts carried no engagement (honest). `trend_discovery` ("mcp servers") -> 24 mentions, velocity shown (842/hr ...), 6 top voices (NetworkChuck 1.5M), 4/4 insights cited, high confidence. `content_performance` (levelsio) -> grounded format winner + "do more of this", honest cross-run trend note, empty themes/best-time sections correctly omitted. No console errors, no horizontal overflow on any. Reliability is enforced in code (`ground` drops invalid/whole-corpus citations, `confidence` forces low band below the post floor), not trusted from the model. Local-dev lesson stands: kill the dev server by `python3.11.exe` image or PID, never `python.exe`.

## Build plan, this change (Resilient transport: uninterrupted-scrape cascade)

Goal: make scraping super-strong and uninterrupted across every source, deterministic and LLM-free in a hosted runtime. User picked the compliant-robust scope: no stealth browser, no bot-detection bypass, proxies bring-your-own. The layers live in one shared transport so a single blocked source or rate-limit never takes a run down. Layers 1-2 (official API, auth session) stay in each adapter (it owns the URL + cookies); layers 3-7 are centralised. Anchored on the product's own compliance line (anti-PhantomBuster, permissioned LinkedIn, no Google SERP scraping).

| # | Change | File | Risk |
|---|---|---|---|
| 1 | New `_fetch.py`: `get()` cascade = curl_cffi fingerprint (3) + per-host politeness gap & exponential backoff honouring Retry-After (4) + BYO proxy rotation with per-proxy cooldown (5) + optional `archive` fallback hook (6) + per-host circuit breaker with `status()` (7). Pure Python, no model calls. Tunables env-overridable; defaults add zero latency to a healthy run. | api/_fetch.py | low |
| 2 | Rewired `_signals._get` (the shared GET chokepoint for GitHub / YouTube / Reddit) to delegate to `_fetch.get`, preserving signature + return type, so every GET adapter inherits the cascade with no per-adapter change. `_browser_session` (X) now shares the BYO proxy pool via `_fetch.session_proxy()`. | api/_signals.py | low |
| 3 | `.env` commented BYO-proxy + resilience tunables (`GTMSTACK_PROXIES`, `FETCH_*`). No secrets. | .env | none |

Verified: unit (`_vf.py`, deleted after) — proxy list parses + rotates, breaker trips after 4 hard failures and then fails fast with `Blocked` (no network attempt), `status()` reports `{fails:4, open:True, open_for:60}`, `archive` fallback returns its value when the breaker is open. Integration after restart: `trend_discovery` ("llm agents") still 200, 24 mentions across github/x/youtube through the new transport, reddit honestly `needs_connection`. Layers 1-2 preserved (adapters unchanged), so official-API and auth-session reads behave as before. Compliance held: no stealth/evasion shipped; the evasion-heavy path was declined per the user's pick and the product's own anti-PhantomBuster guardrail. Rollout not yet done: per-source `archive` fallbacks (Reddit Arctic-Shift, Wayback) and the X GraphQL POST adopting the governor/breaker are the next increment; `_fetch` already exposes the `archive` hook and `session_proxy` for them.

## Build plan, this change (Competitor Intelligence + Connectors + value-prop UI pass)

Goal: ship the Competitor Intelligence tool (the user's Qoruz-style reference, but on the compliant dev/B2B channels), promote it to its own sidebar tool, add a Connectors tab, and reframe the app's copy from features to value props. The fork was resolved when the user named payments brands (Cashfree vs Razorpay / PayU / PhonePe / Easebuzz): B2B, on X / GitHub / YouTube / Reddit, so buildable. IG and LinkedIn-engager scraping stay declined (excluded platform + account-ban / anti-PhantomBuster line, held twice this session).

| # | Change | File | Risk |
|---|---|---|---|
| 1 | New `_compete.py` + `competitor_intel` play: parallel brand scans (stdlib `ThreadPoolExecutor`, per-brand failure degrades to empty), then share of voice (reach %, posts, impact = eng/post vs field avg), a market-positioning quadrant (median split of volume x engagement -> Leader / Aggressive / Punching above / Starter), channel breakdown, top voices, and influencer overlap (authors across >=2 brands). | api/_compete.py, api/_plays.py | low |
| 2 | UI: `CompeteResult` renderer (SoV bars + a plain-SVG 2x2 positioning plot + shared-voices list, no chart lib). Competitor Intelligence promoted to a standalone **sidebar tool** (`TOOLS.competitor` + NAV), reusing `PlayRunner` (back button made optional via `onBack &&`); removed from the home plays grid. New **Connectors** tab (`TOOLS.connectors` + `ConnectorsTool`): 8 integration cards (Salesforce, HubSpot, Smartlead, Instantly, WhatsApp API, Slack, Google Calendar, Enrichment), all **disabled Phase-2 placeholders** (no OAuth: the unbuilt connector layer + credential discipline). | index.html | low |
| 3 | Value-prop copy + font pass: tool headlines reframed feature -> outcome (e.g. "Clean an email list" -> "Never let a bad address burn your sending domain"); body font Geist -> **Poppins** (Geist Mono kept for code); renames "Persona Preview" -> "Synthetic Persona", "Clean Data" -> "NoBounce"; sample persona copy upgraded to a real landing page; accordion/expand icon bug fixed (`open?'check':'plus'` showed a tick -> `open?'minus':'plus'`, added `minus` to the icon map; 4 expand controls). | index.html | low |
| 4 | Automated tests: `tests/test_fetch.py` (17 stdlib-unittest cases for the transport, positive + negative). Plus `/premortem` artifact `RISK.md` from the lean-engineering pass (3 critical findings: not in git, silent LLM-fallback swallow, no observability). | tests/, RISK.md | none |

Verified live (heuristic engine; `_compete` needs no model): `competitor_intel` (Cashfree vs Razorpay/PayU/PhonePe) -> 200, Cashfree #1 of 4 on reach (impact ~3x), quadrants assigned, "The Inventar" surfaced as a shared voice across 3 brands; parallel scan held, no cache contention. UI at 1280px: sidebar has 7 items, Competitor Intel renders the dashboard standalone (no back button), Connectors shows 8 disabled cards, Poppins applied app-wide, value-prop headlines fit, expand controls show plus/minus not a tick, no console errors. Honest scope unchanged: this is a CURRENT snapshot (no 18-month trend store), built from public posts not engager lists; the reference's channel/category-table, full influencer table, and time-series are the next panels. Lean-engineering lesson reinforced: reload the preview before claiming a UI change is verified (a stale-UI probe bit me mid-pass).

## Build plan, this change (Competitor Intel: Frappe-UI declutter + LinkedIn followers)

Goal: the user flagged the Competitor Intelligence result as cluttered and asked for a Frappe-UI layout plus a LinkedIn followers number per brand.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | LinkedIn audience read, real parse: `_linkedin_company` was parsing the wrong shape — Voyager returns LinkedIn's **normalized** format (`data.*elements` -> primary company URN; entities in `included[]`; `followerCount` in a SEPARATE `FollowingInfo` entity referenced by the company's `*followingInfo` URN). Old code read a top-level `elements[0]`, so it found neither followers NOR staff. Rewrote to resolve by URN with a `universalName` match fallback. Added a `_LI_SLUG` override map + display-name slugify (`PayU`->`payu`). New `linkedin_firmographics(name)` helper -> `{followers, followers_h, staff, staff_h, status, note}`, never raises, **cached 6h** (followers move slowly; repeat runs are free and don't re-hit LinkedIn). Compliant **company-page** read via the user's own session, NOT the barred mention/engager scrape. | api/_signals.py | low |
| 2 | `_li_jar()` now prefers a full exported `LINKEDIN_COOKIES` json jar (every cookie, freshest) over the local Chromium profile (which had drifted to a checkpointed session) over the minimal env pair. `_compete.analyze` fetches LinkedIn **sequentially, not in a ThreadPool** — a burst of simultaneous Voyager calls from one personal session is the bot pattern LinkedIn rate-limits and can challenge the real account; sequential + 6h cache is the gentle path. | api/_compete.py, api/_signals.py, .env | med |
| 3 | `CompeteResult` rewritten into Frappe-style bordered cards (`.ci-card` / `.ci-wrap`): Share of voice is now a clean **table** (rank, brand+logo, reach bar+%, posts, **LinkedIn** column) instead of dense bar rows; Market positioning + Shared voices share a 2-col grid (`.ci-grid2`) to cut vertical length; quadrant labels for top/edge dots flip below + anchor start/end so brand names no longer collide with the corner labels. LinkedIn cell shows followers -> `~N staff` fallback -> `—`, with a foot hint only when no brand resolves. Fixed a latent bug: the SoV bar track referenced undefined `--ink-gray-1` (now `--surface-gray-3`). | index.html | low |

Session wiring (out of repo): the user pasted a fresh LinkedIn cookie jar in chat (flagged as a secret to rotate). It's stored at `C:/Users/mothi/.gtmstack/li_cookies.json` (OUTSIDE the repo, so it can't be committed or deployed), pointed to by `LINKEDIN_COOKIES` in the gitignored `.env`. The cookie is never echoed, never in a tracked file.

Verified live (1280px, server restarted to load new code + .env): five Frappe cards render, 2-col grid, zero horizontal overflow, brand logos resolve, Cashfree highlighted as "you". LinkedIn column now shows **real follower counts** — Cashfree 296.7K (922 staff), Razorpay 1.2M (4.1K staff), PayU 340.8K (3.4K staff); PhonePe degrades to `—` because its `universalName` isn't a guessable slug (`phonepe`/`phonepe-pvt-ltd`/`phonepe-india` all 404; needs a search-based resolver, backlogged). Sequential read = 2.0s cold, 0.38s cached. The fresh full jar cleared the checkpoint the profile-dir cookies had drifted into. Quadrant caveat unchanged: the feed caps at 24 posts/brand, so the post-volume x-axis is degenerate (all brands at max volume) — it ranks on engagement only; two low-engagement dots (Razorpay/PhonePe) can still overlap their labels. A higher cap or recency window is the real fix (backlogged).

## Build plan, this change (Daily keyword-group report + Carlsen scan strategy)

Goal: a daily Signals brief per keyword group (e.g. "Payment Gateway"), scanned
with a chess-style strategy, enriched with sentiment + the author's company,
delivered to a new in-app Reports tab, scheduled at 08:00 IST on the Mac via
launchd. User decisions: local launchd trigger (uses the real Chrome session for
X / LinkedIn), in-app Reports tab as the surface.

| # | Change | File | Risk |
|---|---|---|---|
| 1 | Carlsen scan strategy: opening book (safe sources first), move ordering by source-safety x keyword-priority, prophylaxis (skip tripped-breaker hosts), king safety (LinkedIn last, sequential, resign on challenge), a wall-clock budget, and a post evaluation (freshness x reach x relevance). Pure logic, unit-tested. | api/_carlsen.py, tests/test_carlsen.py (11) | low |
| 2 | Keyword groups: 4 built-ins (payment_gateway, cashfree_brand, razorpay_watch, payments_infra) plus an optional api/_store/groups.json or DB override. | api/_groups.py | low |
| 3 | Report engine: runs the Carlsen plan over _signals.lookup(unit=keyword), dedupes, ranks, enriches the top posts (sentiment + author company via _llm, heuristic fallback), computes share-of-voice, reuses _trends.analyze for the grounded synthesis, and stores the result (Postgres when DATABASE_URL is set, else a local JSON snapshot). | api/_report.py | medium |
| 4 | reports table + save/list/get/latest helpers, degrading to a no-op like the rest of _db. | api/_db.py | low |
| 5 | Routes: GET/POST /api/report (Vercel handler + Flask), POST gated by CRON_SECRET when set. | api/report.py, app.py, vercel.json | low |
| 6 | Reports tab: group selector, KPI cards (mentions + sentiment split), synthesis, share-of-voice table, top mentions (sentiment pill + company + profile link), and a collapsible Carlsen scan log. Frappe tokens, solid icons. | index.html | low |
| 7 | launchd: daily_report.py CLI + install/uninstall. macOS blocks a launchd read of ~/Documents (TCC), so the installer copies the runtime to ~/.gtmstack/app and runs there (no Full Disk Access prompt). Runs 08:00 IST; re-run install.sh after code changes. | daily_report.py, launchd/ | medium |

New env (see .env.example): DATABASE_URL (REQUIRED for the hosted Reports tab, since serverless cannot read the Mac's local snapshot), REPORT_BUDGET_S, CRON_SECRET, plus the existing source + LLM keys.

Constraints held: no Playwright (reads go through the _fetch curl_cffi cascade); LinkedIn stays the protected king (last, sequential, resign-on-challenge) per the burner-account guardrail; secrets stay out of the repo; no em dashes.

Verified: 11 Carlsen unit tests pass. Engine run live with no creds (github + youtube): payment_gateway 142 mentions, share-of-voice + ranked + enriched posts + stored snapshot. launchd test-fire clean (exit 0): all 4 groups from ~/.gtmstack/app, no TCC error. /api/report curl-verified (groups, latest report). index.html node --check OK. Not yet verified live: X / LinkedIn / Reddit need creds; the hosted tab needs DATABASE_URL.

## Build plan, this change (Competitive monitor: production-grade + surfaced)

Goal: take the first-pass competitive monitor (Reddit/Quora/review-site scan to
Google Sheets) to production and surface it in-app. User decisions locked:
Instagram + Facebook formally descoped (not compliantly scrapeable); G2 is
licensed-data-API only (no scraping). Built in 4 phases from MONITOR_PLAN.md.

| # | Change | File | Risk |
|---|---|---|---|
| 0a | Fixed 4 correctness bugs: Track 5 tuple unpack (`payload['feed']`), ISO-first date parse (`_parse_date`, was dropping every dated review), deleted Quora date fabrication (no real date -> row dropped, never `now()`), deleted the `verify=False` SSL fallback (MITM hole) | api/_reviews.py, api/_monitor.py | low |
| 0b | `_fetch.get(fail_status={403})`: a Cloudflare 403 is now a HARD fail (trips breaker, falls to archive) instead of resetting the breaker and reading as a clean empty. New `api/_archive.py` = Wayback closure for the `archive=` hook. Review adapters route through `_fetch` with `fail_status={403}` (windowed scans skip archive: stale snapshots never fall inside a last-N-days window) | api/_fetch.py, api/_archive.py, api/_reviews.py | med |
| 0c | Tightened the silent unknown-source fallback (`_resolve_sources`): an unregistered keyword source is now a visible `needs_connection` block, not a silent full-source scan | api/_signals.py | med |
| 1a | `monitor_mentions` table (PK `(group_id, dedup_key)`, kind-aware key so a post + its comments + a review of one URL stay distinct, `first_seen`/`last_seen` for the answer-dates + thread-updated requirement) with a local JSON fallback; single-flight run lock (pg advisory lock or lockfile). Store is the system of record; Sheets is a delta export | api/_db.py, api/_mentions.py | med |
| 1b | Shared `api/_enrich.py` (sentiment lexicon + batched LLM tagger, `enrich_mode` per row); `_report.py` now imports the primitives from it. Monitor caps the model call by count (`MONITOR_ENRICH_MAX`), not rank | api/_enrich.py, api/_report.py, api/_monitor.py | low |
| 1c | Groups drive the monitor: `_normalize` gained monitor fields (window_days/subreddits/review_brands/include_comments/quora_questions/sinks); two builtin monitor groups (competitor_watch 10d, cashfree_mentions 2d + comments). `_monitor.py` fully rewritten groups-driven: per-subreddit `restrict_sr=1` OAuth-primary Reddit (arctic fallback), Quora curated-URL + keyword, review sites, X keyword; LinkedIn honestly `needs_connection` (keyword search not implemented). Budget-bounded, per-track status (ok/quiet/blocked/error/timeout) | api/_groups.py, api/_monitor.py | med |
| 1d | Sheets hardened: `value_input_option=RAW` + formula-injection guard, `GTMSTACK_SHEET_URL` REQUIRED (never auto-create + public-share, the first-pass leak), APIError retry, gid capture for deep links, YYYY-MM tab rotation at 4000 rows, `MONITOR_SHEET_SAFETY` burn-in read | api/_sheets.py | low |
| 1e | Observability: run summary persisted to the reports table; Resend silent-zero + blocked-track alert; 13:00 IST launchd catch-up (fires only if 9am missed, marker-guarded); read-only Vercel-cron staleness watchdog (`api/watchdog.py`) | api/_monitor.py, api/_email.py, launchd/install.sh, api/watchdog.py | med |
| 2 | Registered trustpilot/quora/capterra/g2 as first-class Signals keyword sources (thin `_reviews` wrappers, honest status), Carlsen tiers (tp4/capterra3/quora3/g2 2), `GET/POST /api/monitor` (Flask + Vercel, POST CRON_SECRET-gated), a Monitor panel inside ReportsTool (per-source health strip, staleness banner, sentiment KPIs, model/lexicon badge, sheet deep links, archive as-of labels, IG/FB descope copy), SIG_META/SIG_ORDER/ACT_ICON entries | api/_signals.py, api/_carlsen.py, api/monitor.py, app.py, index.html | med |
| 3 | Competitor-negative velocity spike detection (last 24h vs trailing 7-day baseline -> the moment-marketing alert); `GET/POST /api/groups` (CRON_SECRET-gated) + in-app group editor; mentions retention (prune >180d after each run); install.sh code+env manifest stamp | api/_monitor.py, api/_groups.py, api/groups.py, app.py, index.html, launchd/install.sh | med |

New env (see .env.example): GOOGLE_SA_JSON/GOOGLE_SA_KEY, GTMSTACK_SHEET_URL
(required to push), MONITOR_BUDGET_S / _ENRICH_MAX / _POLITENESS_S / _MAX_SUBS /
_SHEET_SAFETY / _SHEET_ROTATE_ROWS / _ALERT_EMAIL / _STALE_HOURS /
_RETENTION_DAYS, G2_API_KEY, BRAVE/BING_SEARCH_KEY.

Honest scope held: Instagram + Facebook descoped (stated in the UI, not faked); G2
absent until G2_API_KEY (no scraping); TrustPilot/Capterra 403 from datacenter IPs
(the per-source health strip shows "blocked", not a fake "quiet" - they work from
the Mac's residential IP at 9am). LinkedIn keyword sentiment is not implemented
(only own-session person/company reads exist), stated as needs_connection.

Verified: 40 unit tests pass (19 fetch incl. fail_status breaker, 21 monitor:
kind-aware dedup, idempotent reruns, cross-group, single-flight lock, ISO date
parse, no-date-fabrication, velocity spike, group save). Endpoints curl-verified:
/api/monitor overview + staleness, /api/groups read + write round-trip persisted.
index.html node --check clean. Live monitor run end-to-end (no creds): honest
per-track statuses (quiet/blocked/needs_connection), no crash, budget-bounded,
persisted + deduped. Not verified live (needs the Mac's session + creds): real
Reddit OAuth, X cookies, residential-IP review reads, Google Sheets push, DB.
