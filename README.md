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
