# GTMstack

**A GTM harness: standing agents that watch public conversations for buying intent, and tell you when someone is choosing a vendor.**

Live: [gtmforce-ashen.vercel.app](https://gtmforce-ashen.vercel.app)

---

## What it is

GTMstack is two layers that share one memory.

**A workforce of agents** that run on a schedule without you. You delegate in plain English ("watch for people asking which payment gateway to use"), and a teammate reads public posts, works out which ones are someone actively choosing a vendor, saves them with a link back to the original, and sends you an alert. When it needs a decision it stops and asks rather than guessing.

**A toolkit of deterministic tools** for when you already know what you want: look up a person across five platforms, validate an email list, score landing-page copy against developer personas, pull a YouTube transcript, compare share of voice against competitors. These are also the capabilities the agents call, and they are exposed over MCP so any AI agent can call them too.

The design rule underneath: **judgment is agentic, everything else is computed.** Set membership, dedup, math, and cohort queries are deterministic code. The model classifies and interprets. A model asked to enumerate a set will quietly invent members, so it is never asked to.

## Use cases

| You want to | What runs |
|---|---|
| Know when someone publicly asks which vendor to use | **Listener** on a standing watch, alerts to Slack or email |
| Catch a competitor comparison the day it is posted | Listener, `competitor_comparison` intent |
| See public complaints about you same-day | Listener, the "Publicly unhappy" cohort |
| Answer a pipeline or attribution question with an auditable trail | **Analyst**, plan-then-execute, every figure sourced |
| Find duplicate CRM records without a risky merge | **Steward**, blast radius before any change |
| Hand a clean, deliverable list to a sequencer | **NoBounce** |
| Test copy before launch | **Synthetic Persona** |
| Give your own AI agent GTM capabilities | The **MCP server**, five tools |

The wedge is Listener. It is the one agent that needs no connector to be useful, and public buying intent is a signal most GTM tools underweight.

## Capabilities

### The harness

- **Context graph.** One ontology every agent reads and writes: `account`, `person`, `signal`, `cohort`, `deal`, `action`, `outcome`, `definition`, `policy`, `run`, `watch`. Every node records which agent wrote it, in which run, and from what source. No unsourced rows.
- **Agents with AOPs.** Each agent's judgment is a plain-English Agent Operating Procedure (scope, numbered steps, guardrails, evals) that a RevOps lead can read and edit. Each step names the deterministic tool it calls.
- **Plan, then execute.** Nothing non-trivial runs off a prompt. The agent emits a plan showing per-step risk and self-flags steps that lean on low-completeness data. Only then does it run.
- **Tiered approvals.** READ is automatic, WRITE is approve-once-then-standing, SPEND is explicit until a standing policy exists. Every auto-allowed action cites the rule that allowed it. Guardrails are checked before grants, so a standing policy can never unlock one.
- **Cohorts.** Static, dynamic, outcome-learned, and predictive segments. Membership is computed, never guessed, and every member carries the reason it matched.
- **Key Definitions.** One authoritative versioned definition per metric, so two reports cannot disagree about win rate.
- **Standing watches.** A keyword plus an interval. Fires unattended, delivers once, never re-alerts the same post.
- **Outcomes.** Mark an alert actioned, ignored, or converted. This is what turns "we found things" into "N became conversations", and it doubles as the label that teaches the classifier.
- **Observability.** A local event log (runs, steps, decisions, errors, p50/p95) plus an optional OpenTelemetry exporter that emits an agent run as a proper trace.

### The tools

| Tool | What it does |
|---|---|
| **Signals** | Real-time person, company, or keyword lookup across GitHub, Reddit, LinkedIn, X, YouTube |
| **NoBounce** | Validate and de-dupe an email list into agent-ready rows |
| **Synthetic Persona** | Score copy against five developer personas |
| **YouTube Transcript** | Keyless transcript extraction, no API key or quota |
| **Competitor Intel** | Share of voice, positioning quadrant, shared voices |
| **Routines** | Scheduled briefs and the competitive monitor |

### MCP server

Five tools over JSON-RPC (HTTP and stdio): `gtm_signals`, `gtm_persona`, `gtm_youtube_transcript`, `gtm_nobounce`, `gtm_competitor_intel`. Thin adapters over the same engines the UI calls. Tool errors return as content, never a 500, because an agent recovers from a described failure.

---

## Quick start

```bash
pip install -r requirements.txt
python app.py                    # http://localhost:5000
```

Everything works with zero configuration. Sources and delivery light up as you add credentials, and each degrades honestly when absent rather than failing.

**Make it run unattended** (the difference between a toolkit and a product):

```bash
bash launchd/install_watch.sh    # macOS, every 6 hours
python watch_run.py --status     # is the unattended side alive
```

**Key environment variables** (all optional, each a feature flag):

| Var | Effect |
|---|---|
| `SLACK_WEBHOOK_URL` | Where alerts are delivered. The fastest path to a working loop. |
| `ALERT_EMAIL` + `RESEND_API_KEY` | Email delivery |
| `HARNESS_SECRET` | Required for harness endpoints in production. Unset on a deploy means they are disabled. |
| `REDDIT_CLIENT_ID` / `_SECRET` | Reddit via the official OAuth app |
| `GITHUB_TOKEN` | Lifts GitHub from 60 to 5,000 reads/hour |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enables OpenTelemetry tracing |
| `DATABASE_URL` | Postgres for accounts and run history |

See `.env.example` for the full list.

## Testing

```bash
python tests/test_harness.py        # 63 tests: graph, cohorts, agents, delivery, tracing
python tests/test_approvals.py      # 28 tests: the security boundary
python tests/smoke_e2e.py           # 51 checks against a running server
python evals/run_evals.py           # classifier accuracy against a golden set
```

Unit tests and end-to-end checks catch different things. Every production bug found in this repo so far was invisible to unit tests and obvious the moment real data moved through the assembled app.

The evals are a gate, not a report: `run_evals.py --gate` exits non-zero below target.

---

## Where it stands, honestly

**Working, verified on real data:**

- Listener reads live Reddit, classifies intent, and writes to the graph with provenance
- Buying-intent precision **0.952**, recall **1.0**, sentiment accuracy **0.825**, all above target
- Delivery to Slack and email, idempotent (verified: three calls, exactly one webhook POST)
- Standing watches fire on schedule and correctly report zero when nothing is new
- Approvals gate writes and shrink as standing policies accumulate
- 6 unit files, 51/51 end-to-end locally, 43 pass 0 fail in production

**Not there yet, stated plainly:**

- **Hard-case sentiment scores 0.571.** Sarcasm and implication still miss ("Oh brilliant, another failed settlement. Love it."). This is a keyword lexicon, not a model. Closing it needs a real classifier, and the eval harness is how that work gets measured.
- **8 of 11 agents are roadmap, not built.** They are deliberately kept out of the runnable catalog so nothing advertises capability it does not have.
- **The graph is SQLite**, ephemeral per cold start on serverless. Postgres via `DATABASE_URL` is the swap, and it stays inside `_graph.py`.
- **`/api/clean` is unavailable in production.** `mailguard` is a `git+https` dependency that stalls the Vercel build. Local dev installs it explicitly.
- **`useful_alert_rate` is null** until real alerts get marked. That number needs a user, not a test.

---

## Architecture

Dual deploy, one core. Local dev is Flask (`app.py`); production is a single Vercel function (`api/index.py`). Both dispatch through the same module registry, so the two cannot drift.

```
api/_registry.py     Module classes + REGISTRY. Adding an endpoint is one class.
api/_graph.py        The context graph (ontology, provenance, idempotent upserts)
api/_agents.py       AOPs, routing, plan-then-execute, the run record
api/_risk.py         READ / WRITE / SPEND classification
api/_approvals.py    The gate: guardrails, tiers, standing policies
api/_cohorts.py      Deterministic segment membership
api/_definitions.py  Key Definitions (the semantic layer)
api/_deliver.py      Slack and email delivery, outcomes, the value surface
api/_watch.py        Standing watches
api/_observe.py      Event log and metrics
api/_otel.py         OpenTelemetry exporter (optional)
api/_mcp.py          MCP server (HTTP + stdio)
api/_signals.py      The five-platform signal engine
api/index.py         The single Vercel function; dispatches every /api/* route
js/                  Frontend, native ES modules, no build step
```

Governed autonomy is adapted from [OpenWorker](https://github.com/andrewyng/openworker) (Andrew Ng, MIT) as a reference, not a dependency: risk as a declared property one `classify()` reads, approve-once-then-standing, and the Inbox as the human-attention queue.

---

## Product strategy

### The thesis

Every B2B revenue team runs a dozen tools that do not share a model of the account. The intelligence lives in people's heads and in dashboards that report but never act. Growth is capped by headcount, and the team still misses the account going dark.

Agents can now do that work rather than chat about it. GTMstack removes the headcount ceiling on execution: one team runs like ten. It does not replace the seller, it removes the operational sludge around selling.

### What the real work actually is

Published real-world GTM agent usage reshaped this product. The dominant categories by volume are **not outbound**. They are data audit (duplicates, fill rates, unused fields), data cleanup and standardised metric definitions, GTM reporting (pipeline health, stalls, velocity, loss patterns, attribution), and GTM planning. The buyer is **RevOps first**, then Sales, Marketing, and CX.

Observed task times: **2 to 4 hours by hand against 6 to 17 minutes with an agent.** That measured 10x to 15x compression is why the 10x bar is real rather than rhetorical, and why Analyst and Steward ship alongside the sell-side agents instead of after them.

### The wedge

We do not sell a harness on day one, because that is where the funded incumbents are strongest. We wedge in with **one agent that is valuable alone** and let the harness form as its memory. That agent is Listener: it needs no connector to be useful, and public buying intent is a signal the US-centric tools underweight.

### The honest competitive read

The category is crowded. Nevara sells "The GTM Harness." Warmly runs inbound and TAM agents on a context graph with an OODA-plus-learn loop. Nex is backed by the founders of HubSpot and Freshworks. Clay owns the data layer. Petavue owns paid media. Reo owns technical buying signals. GoZen owns the LinkedIn allbound loop. Hiver proved plain-English procedures.

**The harness, the context graph, and the learning loop are table stakes, not a moat.** Reo makes the winning pattern clearest: it won technical GTM by owning a proprietary signal and a niche, not by having a better harness.

### The moat

**Entry moat, what gets us in the door:**

1. **Proprietary signal.** Public-conversation intent (Reddit, X, LinkedIn India threads, including the un-named category posts) plus payments and commerce behaviour.
2. **Channel and geography.** India-native, WhatsApp-first as a system of record, not an afterthought.
3. **Distribution.** Audience, network, building in public.

**Compounding moat, what grows.** The test is not "more data", it is data that gets more valuable and harder to copy as it accumulates, and that we generate by running rather than buying. Ranked: the corrections and approvals ledger compounds fastest, then Key Definitions and AOPs, then engagement outcomes, then the win/loss ledger, then the resolved entity graph. Raw signals are not a moat; anyone with money buys them.

The read most GTM pitches skip: **B2B has no strong cross-customer data network effect.** Outcome data is low-volume and idiosyncratic, and no customer wants their win data training a rival's agent. So the compounding moat is a per-customer switching cost that rises every week, plus a niche-level prior from dominating one niche.

**In one line:** anyone can buy signals and connect systems of record. Nobody else has the map of which signals, cohorts, definitions, messages, and spend actually produced revenue for businesses like these, because that map is generated by running, not bought.

### Build filter

If a feature is not stronger on **proprietary signal**, on the **India and WhatsApp channel**, or on **distribution**, an incumbent already does it better. Do not build it.

### Business model

A platform fee for the harness (graph, connectors, definitions, approvals, evals, observability), a per-agent subscription so you land with one and expand across the workforce, and usage on heavy actions so cost tracks value. Net revenue retention comes from adding agents to the same graph: each new agent is cheaper to add and more valuable than the last, because the graph already exists.

### Non-goals

Not a horizontal automation builder (opinionated GTM agents, not Zapier). Not a dashboard (we act, we do not report). Not buy-side or procurement yet. **Not US-first**, on purpose.

---

## Roadmap

The planned phases against what is actually shipped. Reality did not follow the plan in order: the graph, approvals, evals, and the Cohort Engine landed early, while **connectors are the real lag** and now gate everything downstream.

| Phase | Planned | Status |
|---|---|---|
| **0** | Listener live, golden-set eval, Slack and email alerts | **Shipped.** Live on real Reddit data, delivery verified idempotent, evals gating at 0.952 precision |
| **1** | Context graph, Scout and Steward, CRM and WhatsApp connectors, approvals, eval harness | **Partial.** Graph, Steward, approvals, and evals shipped. **Scout and the CRM/WhatsApp connectors are not built.** |
| **2** | Analyst with plan-then-execute and Key Definitions, Cohort Engine v1 | **Partial.** All three shipped structurally; Analyst computes over the graph rather than a real CRM, because the connector is missing |
| **3** | Writer and Greeter, then Allocator. The allbound loop | Not started |
| **4** | Pulse, Planner, Focus. The flywheel complete | Not started |
| **Later** | Buy-side and procurement agents, the one open white space on the market map | Not started |

### The next three things, in order

1. **A CRM connector (HubSpot or Salesforce).** This is the single biggest unlock. Analyst and Steward are built but reasoning over a graph fed only by public signals, which is a fraction of their value. Everything in Phases 1 and 2 is gated on it.
2. **A real classifier to replace the lexicon.** Hard-case sentiment is 0.571. The eval harness and golden set already exist, so this is measurable work, not a research project.
3. **Outcome data from a real user.** `useful_alert_rate` is null until alerts get marked in production. That number predicts churn better than any offline metric, and no amount of testing can produce it.

### Success metrics

- **North Star:** revenue influenced by GTMstack agents
- Agents live per customer (the expansion metric)
- Approval-shrink rate per agent (trust and quality)
- Hours compressed per task versus the manual baseline (the 10x proof)
- Key Definitions in use (institutional memory)
- Cohort lift over baseline (the moat metric)

### Known risks

| Risk | Mitigation |
|---|---|
| Crowded category with funded incumbents | Do not sell the harness. Wedge with one agent, win India and WhatsApp where they are absent |
| Architecture is commoditised | Compete on signal, channel, and distribution. Apply the build filter |
| Hard data access on X and LinkedIn | Buy the data, build the brain. License the hard platforms, build the intelligence |
| Agents acting on money, messaging, and CRM records | Tiered approvals, hard guardrails, plan-then-execute, glass-box traces, guardrail evals at zero |
| Small team against funded players | Build in public. Distribution and speed are the edge |
| Quality regressions erode trust | Evals as a hard gate. Nothing ships that fails its suite |

---

## Version history

One commit per coherent change. `CLAUDE.md` carries a detailed build plan and an honest scope note for every entry.

| Version | Commit | What changed |
|---|---|---|
| **v0.6** | `d871254` | **Vercel deploy fixed.** Four causes: corporate TLS interception, a 210MB `.venv` upload, Vercel's Python builder requiring a `handler` **class statement** rather than an assignment, and the 12-function Hobby cap. Consolidated to one dispatcher function. Running the suite against production then caught a read-only-filesystem crash. |
| **v0.5** | `7627072` | **OpenTelemetry exporter.** An agent run as a trace: run is a root span, steps are children, tool calls grandchildren, following GenAI semantic conventions. An exporter, not a replacement for the local log. |
| **v0.4** | `4d7fbb8` | **The loop closed.** Real Slack and email delivery, standing watches on a schedule, outcome tracking. Fixed an honesty bug where a re-fired watch claimed the same finds forever and inflated every value metric. |
| **v0.3** | `f89aea2` | **End-to-end suite,** 51 checks, smoke and functional per module. Found and fixed a dev server serving `.env` with nine live credentials. |
| **v0.2** | `e90a733` | **Dead code culled, harness gated, evals added.** Removed an unused integration, a duplicate endpoint, and 8 empty agents. 69 tests. Evals exposed the classifier, which was then rewritten: recall 0.688 to 1.0. |
| **v0.1** | `001b2ea` | **The harness.** Context graph, 11 agents with AOPs, cohorts, Key Definitions, tiered approvals, Inbox, MCP server. |
| **v0.0** | `95543e6` | The toolkit: Signals, NoBounce, Persona, Transcript, Competitor Intel, on a shared module registry. |

### What each version actually improved

**v0.1 to v0.2 was the most valuable change, and it was mostly deletion.** A review found roughly 1,300 lines of surface that did nothing: an OAuth integration nothing imported, an endpoint nothing called, and eight agents that rendered as available and returned empty cards. Removing them made the remaining product legible. The evals added in the same pass immediately proved the classifier was below target, which is what made fixing it possible.

**v0.4 was the difference between a demo and a product.** Everything before it only did work while a human watched. Scheduling, delivery, and outcomes are what let the app answer "what did this do for me last month."

**Every version after v0.2 found at least one bug that only real data revealed:** a sentence-shaped search query returning essay-writing spam, a blocked approval counted as an error, a re-run inflating its own metrics, a read-only filesystem crash in production. None were visible to unit tests.

## Deploying

```bash
export NODE_EXTRA_CA_CERTS=$HOME/.corp-ca.pem   # only behind a TLS-intercepting proxy
npx vercel build --prod && npx vercel deploy --prebuilt --prod
```

Building locally is what makes failures visible: a remote Vercel build that fails reports `UNKNOWN` with no logs. Connecting the Git repo in the Vercel dashboard removes this whole class of problem and is worth doing.

`HARNESS_SECRET` must be set in the deployment, or the harness endpoints stay disabled by design (fail closed).
