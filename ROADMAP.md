# gtmguy roadmap

> gtmguy is the new name for gtmstack. Same product, sharper name. This roadmap
> is grounded in the actual codebase (the `plays` engine, Signals, NoBounce, the
> competitive monitor, Tables, and the Nango connector scaffold merged to main).
> No em dashes, per house style.

## What gtmguy is

gtmguy is Cursor for GTM: a multi-tool workspace where every tool (Signals,
Account Research, List Building, NoBounce validation, Competitor Intel,
Reports/Monitor, Plays) is callable by a human click OR by an AI agent hitting
the same endpoint, returning the same stable, branchable JSON. It is for
AI-native GTM teams and the agents they build, plus founders doing manual
prospect research.

The wedge is fresh, agent-callable intelligence on the dev-native channels that
bulk-export tools miss (what THIS person posted today, not a stale nightly dump),
composed into Plays that chain read, enrich, validate, and route into one run an
agent can call and branch on.

Today only the content axis (5 Plays) and the monitoring axis compose cleanly.
The whole contact axis (prospect to enrich to validate to route) is blocked on
one thing, a routing connector, and that connector already exists in merged code
as an unwired Nango scaffold. The near-term product is to wire that connector,
add the missing enrich and list-build engines (whose upstream data providers are
already available as callable services), and turn four read-only research tools
into one actionable prospect-to-CRM pipeline, all under the compliance posture
(permissioned, no stealth scraping) and the gates that bar any external launch
until multi-tenancy, credential pools, legal review, and observability are real.

## Pillars

| Pillar | Thesis |
|---|---|
| **Playbooks** | Composite, agent-callable runs (`api/_plays.py` PLAYS registry + `/api/plays`) that chain single-tool engines into one POST or click and return `steps[]`. Content axis composes cleanly today (5 plays); the prize is the contact-axis play prospect to enrich to validate to route, which is one registry entry once a routing connector and enrich/list-build engines exist. Adding a play is a 1-3 file change, so this is a high-leverage assembly layer, not a rebuild. |
| **Account Research** | Turn a company or person into one grounded dossier, not five disconnected lookups. Signals already gives cross-channel footprint + a zero-config GitHub-org roster + LinkedIn firmographics; the gap is composing firmographics + tech stack + funding/news + buying-intent into one account brief. Upstream providers exist as callable services, so this is a compose-and-render job behind a new `account_research` play and tool. |
| **List Building** | The half-built Clay/Apollo job. Signals only fans out a list you already hold; there is no ICP-filtered net-new discovery, no contact enrichment (email/phone/title/seniority), no enrichment waterfall, and NoBounce validation is a solid standalone no play calls. Build the missing middle: ICP filter to candidate rows in Tables to a multi-provider enrich waterfall to a NoBounce validate gate to route, with Tables as the system-of-record. |
| **Signals & Monitoring** | The live, fresh, dev-native read layer plus the groups-driven competitive monitor (scan to system-of-record to delta-to-Sheets, Carlsen scan planner, velocity-spike alerts, staleness watchdog). This is the built moat and the freshness wedge. Keep it reliable, fix the two data-quality degeneracies that undercut it, and make it multi-tenant-safe and self-supplying rather than single-Mac, single-cookie, single-Sheet. |
| **Agent Surface & Platform** | Make "callable by an agent" first-class and make the product sellable. Ship the MCP server named in the lean canvas over the existing REST routes, wire the Nango proxy as the routing primitive, and harden the base (observability, `/health`, per-call trace, per-tenant secret vaulting, metering, multi-tenant isolation) so the legal and reliability gates can clear before any external launch. |

## NOW (0 to 1 month): finish what is 80 percent done

Nearly free wiring over code that already exists. The branch merge is a hard
prerequisite: neither branch is the whole product.

| Effort | Pillar | Item | Why |
|---|---|---|---|
| L | Platform | **Merge the two divergent branches into one tree.** Bring main's One UI design system (`DESIGN_SYSTEM.md`, `UI_GENERATION_CONTEXT.md`, `--ds-*` tokens) and the Nango `api/_connectors.py` scaffold into `feat/competitive-monitor-tables-signals` (which owns Reports/Monitor/Tables/Carlsen/review-sources). | Every downstream item depends on both halves in one tree. Shipping on either branch alone silently drops half the surface. |
| M | Platform | **Wire the Nango connector layer end to end.** Add `api/connectors.py` Vercel handler + Flask route + `NANGO_SECRET_KEY`, and turn ConnectorsTool's 8 disabled cards into live Connect buttons gated by `list_connections()`. | `proxy()` is the exact "route" primitive the contact axis lacks. This one wiring layer unblocks the entire prospect to route play and makes the placeholder cards real. |
| M | Platform | **Close the observability gate.** JSONL trace per `_llm.chat()` with a `fallback_reason` field (a live model degrading to heuristic is logged, not swallowed), a `/api/health` route, an explicit LLM timeout + circuit breaker, and atomic `_store` writes. | RISK.md blocks external ship on exactly these. Cheap now, hard preconditions for any external or agent traffic. |
| M | List Building | **Give Tables a backend.** A `/api/tables` read/write route persisting off localStorage into Neon (`api/_db.py`), so an agent can read and populate the pipeline and engines can write results INTO it. Wire it as the contact-axis system-of-record with kind-aware dedupe. | Tables is client-only localStorage today, contradicting the "every tool callable by an agent" thesis. It must become the sink before any contact-axis play can run. |
| M | Platform | **Ship the MCP server** over the existing REST routes (signals, jobs, clean, plays, report, monitor, groups) as a discoverable tool manifest, reusing each endpoint's stable shape. | The lean canvas names "an MCP server + API later" as the channel; agent access today is raw HTTP. Every endpoint already returns a branchable shape. |
| S | Playbooks | **Reconcile the connector narrative.** Adopt Nango (merged code) as the connector spine and retire the Activepieces plan in docs (CLAUDE.md, `_plays.py` header, ConnectorsTool copy). | Docs still name Activepieces while merged code is Nango. The contact axis needs one chosen spine, and Nango is the one that exists. |
| S | Playbooks | **Compose NoBounce into a callable play step** (not just `/api/clean`), and add a play category taxonomy (Content / Pipeline / Monitoring) so PLAYS can hold non-content plays. | NoBounce is the one cleanly-built contact-axis step no play can call. This is the prerequisite for the prospect to route chain. |
| S | Signals | **Fix the two Signals data-quality holes.** Raise the ~24-40 posts/brand cap (or add a recency window) so the competitor positioning quadrant is not degenerate, and add a search-based LinkedIn `universalName` resolver so firmographics stop degrading to blank (e.g. PhonePe). | Both are flagged in CLAUDE.md and make the shipped Competitor Intel output visibly wrong, eroding trust in an axis that already ships. |

## NEXT (1 to 3 months): the connector-unlocked contact axis

This is the core of what "list building" and "account research" mean. The
upstream data providers already exist as callable services, so these are wire-ups
plus composition, not from-scratch data builds.

| Effort | Pillar | Item | Unblocks |
|---|---|---|---|
| L | List Building | **Enrichment engine + waterfall.** `/api/enrich` taking email/domain/named-person, returning person + company + role + seniority + phone via multi-provider fallback (try A, fall back to B/C). Standalone tool AND a callable play step. | Enrich step of the contact-axis play; email-to-identity resolution; the lead-scoring model later. |
| L | List Building | **ICP list builder.** `/api/list-build` taking an ICP filter (industry / size / geo / tech / signal) and returning candidate accounts and contacts from a firmographic/contact-search provider, with rows landing in Tables. Net-new discovery, not fan-out of a list you already hold. | Prospect step of the contact-axis play; TAM-to-list; feeds Tables as the pipeline source. |
| L | Account Research | **Account research play + tool.** Compose Signals company footprint + GitHub-org roster + LinkedIn firmographics + a tech-stack/news-funding/buying-intent provider into one grounded account brief via `/api/plays` (`account_research`) and a dedicated tool, with provenance/confidence per field. | The "map the account into a brief" job; account-tier list building; lead scoring. |
| M | Playbooks | **The marquee contact-axis play.** One PLAYS entry chaining list-build (prospect) to enrich (waterfall) to NoBounce (validate gate) to Nango proxy (route to CRM/Slack/sequencer), through the existing `/api/plays` shape and the MCP manifest. | Turns four terminal read-only tools into one actionable prospect-to-CRM pipeline an agent can POST. |
| M | List Building | **Routing actions library over `proxy()`.** HubSpot/Salesforce contact upsert, Slack message, sequencer push (Smartlead/Instantly), and a dedupe-against-CRM read before any write. | Route step for every contact-axis play; write-back for monitoring alerts; dedupe-against-CRM. |
| M | Playbooks | **Extend the reliability contract to ALL plays.** Per-play run log with cost/latency on `/api/plays`, and a confidence-gate contract agents can rely on across every play, not just agents 12/13/14. | Agent trust across the contact axis; the metering/SLA layer later; an eval harness. |
| M | Signals | **Monitoring axis as scheduled plays.** Make Reports/Monitor callable as plays with an in-product scheduler (not only the launchd job), so an agent can trigger and consume a scan through `/api/plays`. | Agent-triggered monitoring; unifies monitoring under the plays surface + MCP. |

## LATER (3 to 6 months+): the platform and moat bets

Genuinely expensive, and the named Phase-2 gates. Deferred deliberately: do not
spend on the credential moat or the legal program until the contact axis proves
external demand.

- **Multi-tenant isolation** + per-tenant secret vaulting + per-user rate budgets (each workspace brings its own LinkedIn/X session and CRM connection, isolated). Gate 1 for external launch.
- **Managed credential supply**: a warmed burner-account pool + residential proxy rotation, so the product supplies working dev-channel access instead of BYO cookies + BYO proxies. The moat, the real COGS, and the riskiest assumption in one. Build only after the contact axis proves demand.
- **Legal and compliance program**: PII lawful-basis review (GDPR, India DPDP), ToS/CFAA posture, a DPA, subject opt-out + DSAR + deletion tooling, and a retention-policy surface beyond the 180-day mentions prune.
- **Usage metering + quota + billing** on every endpoint (usage-priced lookups or seats), with abuse control so one caller cannot exhaust the shared upstream sessions.
- **Lead scoring / fit model** over the enriched record, feeding routing (round-robin, territory, ownership assignment).
- **Validation depth**: phone validation, catch-all classification (`check_catchall` already exists in `_clean.py`, just hidden), and dedupe-against-CRM as a first-class step.
- **Community / marketplace plays**: user-published PLAYS entries, a play gallery, and sharing. The registry pattern already makes plays cheap to add; a marketplace turns the assembly layer into a network effect.
- **SLA / uptime / status page + error budget** on the sellable data API, built on the `/health` + per-call trace layer.

## Hard gates (must clear before any external or paid launch)

1. Multi-tenant isolation + per-user auth + per-user rate budgets (auth is shipped but single-user-grade).
2. Warmed burner-account pool + residential proxy rotation for LinkedIn/X reads at scale (the riskiest assumption, unsolved; proxies are BYO only and personal-cookie LinkedIn-at-scale is barred by the product's own rule).
3. PII/lawful-basis review (GDPR, India DPDP) + ToS/CFAA posture + subject opt-out/DSAR/deletion + retention-policy surface.
4. Observability on the silent LLM-fallback path: `fallback_reason` logging + per-call JSONL trace + `/api/health` + LLM timeout and circuit breaker (RISK.md blocks external ship on this).
5. Per-tenant secret vaulting: no external user can safely bring their own session or CRM connection while all creds live in one global `.env`.
6. Usage metering + quota + abuse control on agent-callable endpoints before exposing or pricing them.
7. Compliance posture held: no stealth browser, no bot-detection bypass, permissioned-only; descoped channels (Instagram/Facebook, G2-scrape, LinkedIn-engager) stay descoped; provenance + confidence on every AI output.
8. Repo in git (done) and the leaked RunPod LLM key rotated (irreversible per RISK.md).

## Metrics

- **North star**: agent-callable runs per week that produce an accepted output (a human keeps it or an agent routes it), across both the content and contact axes.
- **Signals**: fresh-lookup success rate per source, p95 latency, cache-hit rate.
- **List Building**: contact-axis funnel completion (built to enriched to validated to routed) as a percentage; share of built rows that pass NoBounce as deliverable or risky.
- **Account Research**: account briefs generated, time-to-brief, field-coverage percent (firmographics / tech / news / intent resolved per brief).
- **Playbooks**: play run count, per-play ok/success rate, grounded-insight citation coverage, cost + latency per run.
- **Signals & Monitoring**: daily scan freshness (staleness-alert count), delta rows per day, velocity-spike alerts actioned.
- **Platform**: MCP tool-call volume, connected connectors per workspace, metered-usage revenue, and the LinkedIn/X read ban rate (the direct riskiest-assumption metric).

## Why this order

Quickest-to-value first, riskiest-and-most-expensive last, dependencies
respected. NOW finishes what is 80 percent done and is nearly free: the branch
merge is a prerequisite because neither branch is the whole product, and the
observability fixes, Nango wiring, Tables backend, and MCP server are small,
self-contained wiring layers over code that already exists. The contact axis is
blocked on essentially ONE thing, a routing connector, and that connector is
already merged as an unwired Nango scaffold; wiring it is a handler + route + env
+ UI change, not a build.

NEXT is therefore the connector-unlocked contact axis: enrichment and
list-building engines whose upstream providers already exist as callable services
(wire-ups, not from-scratch data builds), an account-research dossier that
composes existing footprint primitives with those providers, and then the marquee
prospect to enrich to validate to route play, which is one PLAYS entry once its
three engines and the routing connector exist. That play sits last in NEXT
because it chains everything before it.

LATER holds the platform bets that are genuinely expensive and are the named
Phase-2 gates: the warmed-account/residential-proxy credential pool (moat, COGS,
and riskiest assumption in one), multi-tenancy, per-tenant secret vaulting,
legal/DPDP/opt-out, and metering/billing. These are deferred because you do not
spend on the credential moat or the legal program until the contact axis has
proven external demand, and because harden-before-sell means the observability
work (NOW) and the platform gates (LATER) bracket the contact-axis build so
nothing external ships before the gates clear.
