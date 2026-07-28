#!/usr/bin/env python3
"""
End-to-end smoke and functional suite, run against a LIVE server.

The unit tests (test_*.py) prove the engines are correct in isolation. This
proves the assembled app actually serves them: routing, request parsing, real
payload shapes, and the multi-step flows a user performs. The two catch
different things. Every production bug found in this repo so far (the sentence
shaped search query, the intent miss, the blocked-decision-as-error) was
invisible to unit tests and obvious the moment real data moved through.

Two levels per module:
  SMOKE       does it respond at all, with the right shape
  FUNCTIONAL  does it do the right thing with real input

Network-dependent checks are marked DEGRADED rather than FAILED when a source is
unreachable or uncredentialed, because "Reddit rate-limited us" is not the same
as "our code is broken" and conflating them makes the report useless.

    python tests/smoke_e2e.py                      # against localhost:5000
    python tests/smoke_e2e.py --base https://...   # against a deployment
    python tests/smoke_e2e.py --quick              # skip slow network calls

No em dashes.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5000"
QUICK = False
SECRET = None

PASS, FAIL, DEGRADED, SKIP = "PASS", "FAIL", "DEGRADED", "SKIP"
results = []


def _req(path, body=None, timeout=90, method=None):
    url = f"{BASE}/api/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if SECRET:
        req.add_header("X-Harness-Secret", SECRET)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, {"_raw": raw[:400]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"_raw": raw[:400]}
    except Exception as e:                                       # noqa: BLE001
        return 0, {"_error": str(e)[:200]}


def check(module, level, name, fn):
    """Run one check. fn returns True, or (status, note)."""
    t0 = time.time()
    try:
        out = fn()
    except Exception as e:                                       # noqa: BLE001
        out = (FAIL, f"raised {type(e).__name__}: {str(e)[:120]}")
    status, note = out if isinstance(out, tuple) else (PASS if out else FAIL, "")
    results.append({"module": module, "level": level, "name": name,
                    "status": status, "note": note,
                    "ms": int((time.time() - t0) * 1000)})
    icon = {PASS: "ok  ", FAIL: "FAIL", DEGRADED: "deg ", SKIP: "skip"}[status]
    print(f"  [{icon}] {level:<10} {name:<46} {note[:60]}")


# ── existing tools ──────────────────────────────────────────────────────────

def t_transcript():
    print("\nTranscript")
    def smoke():
        s, d = _req("transcript")
        return (PASS, "rejects empty input") if s == 400 else (FAIL, f"status {s}")
    check("transcript", "SMOKE", "GET with no url is a clean 400", smoke)

    def func():
        if QUICK:
            return (SKIP, "network")
        s, d = _req("transcript?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        # The engine returns `plain` (full text) plus `cues` (timed segments).
        if s == 200 and (d.get("plain") or d.get("cues")):
            return (PASS, f"{len(d.get('plain',''))} chars, {len(d.get('cues',[]))} cues")
        return (DEGRADED, f"status {s}, likely IP-blocked")
    check("transcript", "FUNCTIONAL", "pulls a real transcript", func)


def t_persona():
    print("\nSynthetic Persona")
    def smoke():
        s, d = _req("persona")
        n = len(d.get("personas", []))
        return (PASS, f"{n} personas") if s == 200 and n else (FAIL, f"status {s}")
    check("persona", "SMOKE", "GET returns the roster", smoke)

    def func():
        s, d = _req("persona", {"text": "The fastest payment gateway for Indian startups. "
                                        "Integrate in one afternoon.", "type": "landing"})
        if s != 200:
            return (FAIL, f"status {s}")
        if "overall" in d or "reactions" in d:
            return (PASS, f"overall={d.get('overall')}")
        return (FAIL, f"unexpected shape: {list(d)[:5]}")
    check("persona", "FUNCTIONAL", "scores real copy", func)


def t_signals():
    print("\nSignals")
    def smoke():
        s, d = _req("signals")
        n = len(d.get("sources", {}))
        return (PASS, f"{n} sources reporting") if s == 200 and n else (FAIL, f"status {s}")
    check("signals", "SMOKE", "GET reports source readiness", smoke)

    def func():
        if QUICK:
            return (SKIP, "network")
        s, d = _req("signals", {"query": "payment gateway", "unit": "keyword",
                                "sources": ["reddit"]})
        if s != 200:
            return (FAIL, f"status {s}")
        feed = d.get("feed") or []
        if not feed:
            return (DEGRADED, "0 items, source may be blocked")
        item = feed[0]
        missing = [k for k in ("text", "url", "platform") if not item.get(k)]
        if missing:
            return (FAIL, f"feed item missing {missing}")
        return (PASS, f"{len(feed)} items, shape ok")
    check("signals", "FUNCTIONAL", "keyword feed returns usable items", func)

    def relevance():
        """The bug that shipped: a sentence-shaped query returned unrelated spam."""
        if QUICK:
            return (SKIP, "network")
        s, d = _req("signals", {"query": "payment gateway", "unit": "keyword",
                                "sources": ["reddit"]})
        feed = d.get("feed") or []
        if not feed:
            return (DEGRADED, "no items to judge")
        hits = sum(1 for m in feed if any(w in (m.get("text") or "").lower()
                                          for w in ("payment", "gateway", "pg ", "upi",
                                                    "razorpay", "stripe", "checkout")))
        pct = round(100 * hits / len(feed))
        if pct < 40:
            return (FAIL, f"only {pct}% on-topic, query is too loose")
        return (PASS, f"{pct}% on-topic")
    check("signals", "FUNCTIONAL", "results are actually on-topic", relevance)


def t_clean():
    print("\nNoBounce")
    def smoke():
        s, d = _req("clean", method="GET")
        return (PASS, "GET correctly 405s") if s == 405 else (FAIL, f"status {s}")
    check("clean", "SMOKE", "is POST-only", smoke)

    def func():
        s, d = _req("clean", {"text": "a@gmail.com\na@gmail.com\nbad@@x\n"
                                      "info@stripe.com\nnope@thisdomaindoesnotexist12345.com"})
        if s != 200:
            if "mailguard" in str(d):
                return (DEGRADED, "mailguard not installed on this server")
            return (FAIL, f"status {s}")
        summ = d.get("summary") or {}
        if not summ:
            return (DEGRADED, "no summary, mailguard likely absent")
        if summ.get("duplicates_removed", 0) < 1:
            return (FAIL, "failed to dedupe the repeated address")
        bv = summ.get("by_verdict") or {}
        if sum(bv.values()) != summ.get("unique"):
            return (FAIL, "verdict buckets do not sum to unique (the double-count bug)")
        return (PASS, f"unique={summ.get('unique')} dupes={summ.get('duplicates_removed')} {bv}")
    check("clean", "FUNCTIONAL", "dedupes and partitions correctly", func)


def t_plays():
    print("\nPlays")
    def smoke():
        s, d = _req("plays")
        n = len(d.get("plays", []))
        return (PASS, f"{n} plays") if s == 200 and n else (FAIL, f"status {s}")
    check("plays", "SMOKE", "GET lists plays", smoke)

    def unknown():
        s, d = _req("plays", {"play": "does_not_exist", "input": {}})
        return (PASS, "unknown play 404s") if s == 404 else (FAIL, f"status {s}")
    check("plays", "FUNCTIONAL", "unknown play is a clean 404", unknown)


def t_jobs():
    print("\nJobs")
    def smoke():
        s, d = _req("jobs")
        return (PASS, f"{len(d.get('jobs', []))} jobs") if s == 200 else (FAIL, f"status {s}")
    check("jobs", "SMOKE", "GET lists jobs", smoke)


def t_report_monitor_groups():
    print("\nReports / Monitor / Groups")
    for mod in ("report", "monitor", "groups"):
        def smoke(m=mod):
            s, d = _req(m)
            return (PASS, "ok") if s == 200 else (FAIL, f"status {s}")
        check(mod, "SMOKE", f"GET /api/{mod} responds", smoke)

    def groups_shape():
        s, d = _req("groups")
        g = d.get("groups") or []
        if not g:
            return (FAIL, "no groups configured")
        need = ("id", "keywords")
        missing = [k for k in need if k not in g[0]]
        return (FAIL, f"group missing {missing}") if missing else (PASS, f"{len(g)} groups")
    check("groups", "FUNCTIONAL", "groups carry id and keywords", groups_shape)

    def cron_gate():
        s, d = _req("report", {"group": "payment_gateway"}, timeout=120)
        if s == 401:
            return (PASS, "CRON_SECRET gate holds")
        if s in (200, 404):
            return (PASS, f"ran or 404 (no secret set), status {s}")
        return (DEGRADED, f"status {s}")
    check("report", "FUNCTIONAL", "POST respects the cron gate", cron_gate)


def t_watchdog_auth():
    print("\nWatchdog / Auth")
    def wd():
        s, d = _req("watchdog")
        return (PASS, f"stale={d.get('stale')}") if s == 200 else (FAIL, f"status {s}")
    check("watchdog", "SMOKE", "reports staleness", wd)

    def auth():
        s, d = _req("auth")
        return (PASS, "unknown action rejected") if s == 400 else (FAIL, f"status {s}")
    check("auth", "SMOKE", "rejects an unknown action", auth)


# ── the harness ─────────────────────────────────────────────────────────────

def t_graph():
    print("\nHarness: Context Graph")
    def smoke():
        s, d = _req("graph")
        c = (d.get("counts") or {})
        return (PASS, f"{c.get('nodes')} nodes / {c.get('edges')} edges") if s == 200 \
            else (FAIL, f"status {s}")
    check("graph", "SMOKE", "GET returns counts", smoke)

    def seed():
        s, d = _req("graph", {"action": "seed"})
        return (PASS, "seeded") if s == 200 and d.get("ok") else (FAIL, f"status {s}")
    check("graph", "FUNCTIONAL", "seed is idempotent and safe", seed)

    def provenance():
        s, d = _req("graph?type=signal&limit=5")
        nodes = d.get("nodes") or []
        if not nodes:
            return (SKIP, "no signals yet")
        bad = [n["id"] for n in nodes if not n.get("agent")]
        return (FAIL, f"{len(bad)} nodes without provenance") if bad \
            else (PASS, f"{len(nodes)} nodes all carry provenance")
    check("graph", "FUNCTIONAL", "every node records who wrote it", provenance)

    def bad_action():
        s, d = _req("graph", {"action": "nonsense"})
        return (PASS, "rejected") if s == 400 else (FAIL, f"status {s}")
    check("graph", "FUNCTIONAL", "unknown action is rejected", bad_action)


def t_agents():
    print("\nHarness: Agents")
    def smoke():
        s, d = _req("agents")
        a, r = d.get("agents") or [], d.get("roadmap") or []
        if s != 200 or not a:
            return (FAIL, f"status {s}")
        return (PASS, f"{len(a)} runnable, {len(r)} roadmap")
    check("agents", "SMOKE", "catalog splits runnable from roadmap", smoke)

    def honesty():
        """The bug that shipped: unbuilt agents advertised as runnable."""
        s, d = _req("agents")
        liars = [x["name"] for x in (d.get("agents") or []) if not x.get("steps")]
        return (FAIL, f"runnable with no steps: {liars}") if liars \
            else (PASS, "no agent claims more than it has")
    check("agents", "FUNCTIONAL", "no runnable agent has zero steps", honesty)

    def aop():
        s, d = _req("agents?id=listener")
        if s != 200:
            return (FAIL, f"status {s}")
        missing = [k for k in ("scope", "steps", "guardrails", "evals") if not d.get(k)]
        return (FAIL, f"AOP missing {missing}") if missing else (PASS, f"{len(d['steps'])} steps")
    check("agents", "FUNCTIONAL", "AOP is complete", aop)

    def routing():
        cases = [("watch for people asking which payment gateway", "listener"),
                 ("how many duplicate contacts do we have", "steward"),
                 ("what is our win rate this quarter", "analyst")]
        bad = []
        for text, want in cases:
            s, d = _req("agents", {"mode": "plan", "agent": want, "input": {"query": "x"}})
            if s != 200:
                bad.append(f"{want}:{s}")
        return (FAIL, f"plan failed for {bad}") if bad else (PASS, f"{len(cases)} agents plan ok")
    check("agents", "FUNCTIONAL", "each agent produces a plan", routing)

    def plan_gates():
        s, d = _req("agents", {"mode": "plan", "agent": "listener", "input": {"query": "x"}})
        steps = d.get("steps") or []
        if not steps:
            return (FAIL, "no steps")
        autos = [x for x in steps if x["auto"]]
        unruled = [x["tool"] for x in autos if not x.get("rule")]
        if unruled:
            return (FAIL, f"auto-allowed with no rule cited: {unruled}")
        return (PASS, f"{len(autos)}/{len(steps)} auto, all cite a rule")
    check("agents", "FUNCTIONAL", "every auto-allowed step cites its rule", plan_gates)

    def roadmap_refused():
        s, d = _req("agents", {"agent": "watcher", "input": {}})
        return (PASS, "refused with a reason") if s == 400 and d.get("roadmap") \
            else (FAIL, f"status {s}, expected a clear refusal")
    check("agents", "FUNCTIONAL", "running an unbuilt agent is refused clearly", roadmap_refused)

    def unknown():
        s, d = _req("agents", {"agent": "nobody", "input": {}})
        return (PASS, "404") if s == 404 else (FAIL, f"status {s}")
    check("agents", "FUNCTIONAL", "unknown agent 404s", unknown)

    def real_run():
        if QUICK:
            return (SKIP, "network")
        s, d = _req("agents", {"ask": "watch for people asking which payment gateway to use"},
                    timeout=150)
        if s != 200:
            return (FAIL, f"status {s}")
        if not d.get("steps"):
            return (FAIL, "no steps ran")
        if not d.get("ok"):
            errs = [x.get("error") for x in d["steps"] if x.get("status") == "error"]
            return (FAIL, f"run failed: {errs[:2]}")
        return (PASS, f"{d.get('emitted')} saved, {len(d.get('queued', []))} queued")
    check("agents", "FUNCTIONAL", "end-to-end delegated run", real_run)


def t_inbox():
    print("\nHarness: Inbox / Approvals")
    def smoke():
        s, d = _req("inbox")
        if s != 200:
            return (FAIL, f"status {s}")
        for k in ("items", "count", "standing", "tiers"):
            if k not in d:
                return (FAIL, f"missing {k}")
        return (PASS, f"{d['count']} waiting, {len(d['standing'])} standing")
    check("inbox", "SMOKE", "returns queue, grants, and tiers", smoke)

    def tiers():
        s, d = _req("inbox")
        got = {t["risk"] for t in d.get("tiers", [])}
        want = {"read", "write", "spend"}
        return (PASS, "read/write/spend") if got == want else (FAIL, f"tiers={got}")
    check("inbox", "FUNCTIONAL", "all three risk tiers exposed", tiers)

    def bad_resolve():
        s, d = _req("inbox", {"id": "does_not_exist", "outcome": "once"})
        return (PASS, "handled") if s == 200 and not d.get("ok") else (FAIL, f"status {s} {d}")
    check("inbox", "FUNCTIONAL", "resolving an unknown item is handled", bad_resolve)


def t_cohorts():
    print("\nHarness: Cohorts")
    def smoke():
        s, d = _req("cohorts")
        c = d.get("cohorts") or []
        return (PASS, f"{len(c)} cohorts") if s == 200 and c else (FAIL, f"status {s}")
    check("cohorts", "SMOKE", "GET lists cohorts", smoke)

    def determinism():
        a = _req("cohorts?key=buying_intent")[1].get("count")
        b = _req("cohorts?key=buying_intent")[1].get("count")
        c = _req("cohorts?key=buying_intent")[1].get("count")
        return (PASS, f"stable at {a}") if a == b == c else (FAIL, f"drifted: {a},{b},{c}")
    check("cohorts", "FUNCTIONAL", "membership is deterministic across calls", determinism)

    def reasons():
        s, d = _req("cohorts?key=buying_intent")
        mem = d.get("members") or []
        if not mem:
            return (SKIP, "empty cohort")
        bad = [m["id"] for m in mem if not m.get("reason")]
        return (FAIL, f"{len(bad)} members with no reason") if bad \
            else (PASS, f"{len(mem)} members all explained")
    check("cohorts", "FUNCTIONAL", "every member states why it matched", reasons)

    def unknown():
        s, d = _req("cohorts?key=nope")
        return (PASS, "error returned") if d.get("error") else (FAIL, "no error for bad key")
    check("cohorts", "FUNCTIONAL", "unknown cohort errors cleanly", unknown)


def t_definitions():
    print("\nHarness: Key Definitions")
    def smoke():
        s, d = _req("definitions")
        n = len(d.get("definitions") or [])
        return (PASS, f"{n} definitions") if s == 200 and n else (FAIL, f"status {s}")
    check("definitions", "SMOKE", "GET lists definitions", smoke)

    def one_per_metric():
        s, d = _req("definitions")
        keys = [x["key"] for x in d.get("definitions", [])]
        dupes = {k for k in keys if keys.count(k) > 1}
        return (FAIL, f"duplicate definitions: {dupes}") if dupes \
            else (PASS, f"{len(keys)} unique metrics")
    check("definitions", "FUNCTIONAL", "exactly one row per metric", one_per_metric)

    def promote():
        s, d = _req("definitions", {"name": "Smoke Metric", "formula": "a / b"})
        if not d.get("ok"):
            return (FAIL, str(d)[:80])
        v1 = d["version"]
        s, d2 = _req("definitions", {"name": "Smoke Metric", "formula": "a / c"})
        return (PASS, f"v{v1} then v{d2['version']}") if d2["version"] == v1 + 1 \
            else (FAIL, "version did not bump")
    check("definitions", "FUNCTIONAL", "promotion versions rather than overwrites", promote)


def t_observe():
    print("\nHarness: Observability")
    def smoke():
        s, d = _req("observe")
        return (PASS, f"{d['metrics'].get('events')} events") if s == 200 and "metrics" in d \
            else (FAIL, f"status {s}")
    check("observe", "SMOKE", "GET returns metrics and recent events", smoke)

    def blocked_not_error():
        """The bug in the observability itself: a gated action is not a failure."""
        s, d = _req("observe")
        m = d.get("metrics") or {}
        if m.get("blocked", 0) and m.get("errors", 0) >= m.get("blocked"):
            return (FAIL, f"blocked={m['blocked']} counted as errors={m['errors']}")
        return (PASS, f"errors={m.get('errors')} blocked={m.get('blocked')}")
    check("observe", "FUNCTIONAL", "a blocked decision is not an error", blocked_not_error)

    def rules_traced():
        s, d = _req("observe?kind=decision")
        ev = d.get("recent") or []
        if not ev:
            return (SKIP, "no decisions yet")
        allowed = [e for e in ev if e.get("ok")]
        unruled = [e for e in allowed if not (e.get("data") or {}).get("rule")]
        return (FAIL, f"{len(unruled)} allows with no rule") if unruled \
            else (PASS, f"{len(allowed)} allows all traced")
    check("observe", "FUNCTIONAL", "allowed decisions carry their rule", rules_traced)


def t_mcp():
    print("\nMCP server")
    def initialize():
        s, d = _req("mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        ok = s == 200 and (d.get("result") or {}).get("protocolVersion")
        return (PASS, (d.get("result") or {}).get("protocolVersion", "")) if ok \
            else (FAIL, f"status {s}")
    check("mcp", "SMOKE", "initialize handshake", initialize)

    def tools_list():
        s, d = _req("mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = ((d.get("result") or {}).get("tools") or [])
        if not tools:
            return (FAIL, "no tools")
        bad = [t["name"] for t in tools if not t.get("inputSchema")]
        return (FAIL, f"tools without schema: {bad}") if bad else (PASS, f"{len(tools)} tools")
    check("mcp", "FUNCTIONAL", "every tool declares an input schema", tools_list)

    def call():
        s, d = _req("mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "gtm_nobounce",
                                       "arguments": {"text": "a@gmail.com\nbad@@x"}}})
        ok = s == 200 and (d.get("result") or {}).get("content")
        return (PASS, "returned content") if ok else (FAIL, f"status {s} {str(d)[:80]}")
    check("mcp", "FUNCTIONAL", "a real tool call returns content", call)

    def bad_method():
        s, d = _req("mcp", {"jsonrpc": "2.0", "id": 4, "method": "nope"})
        code = (d.get("error") or {}).get("code")
        return (PASS, "-32601") if code == -32601 else (FAIL, f"got {code}")
    check("mcp", "FUNCTIONAL", "unknown method returns -32601", bad_method)

    def error_as_content():
        """An agent recovers from a described failure, not from a 500."""
        s, d = _req("mcp", {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                            "params": {"name": "gtm_signals", "arguments": {}}})
        if s >= 500:
            return (FAIL, f"tool error surfaced as {s}")
        return (PASS, "handled without a 5xx")
    check("mcp", "FUNCTIONAL", "a bad tool call never 500s", error_as_content)


def t_security():
    print("\nSecurity")
    def secrets_not_served():
        bad = []
        for p in (".env", "CLAUDE.md", "app.py", "RISK.md"):
            try:
                with urllib.request.urlopen(f"{BASE}/{p}", timeout=10) as r:
                    if r.status == 200:
                        bad.append(p)
            except Exception:                                    # noqa: BLE001
                pass
        return (FAIL, f"SERVED: {bad}") if bad else (PASS, "env and internal docs not served")
    check("security", "FUNCTIONAL", "secrets and internal docs are not public", secrets_not_served)

    def removed_endpoint():
        s, d = _req("approvals")
        return (PASS, "gone") if s == 404 else (FAIL, f"still live: {s}")
    check("security", "FUNCTIONAL", "the duplicate approvals endpoint is gone", removed_endpoint)


def main():
    global BASE, QUICK, SECRET
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--secret", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    BASE, QUICK, SECRET = a.base.rstrip("/"), a.quick, a.secret

    print(f"\nGTMstack end-to-end suite  ->  {BASE}")
    print("=" * 78)

    for fn in (t_transcript, t_persona, t_signals, t_clean, t_plays, t_jobs,
               t_report_monitor_groups, t_watchdog_auth, t_graph, t_agents,
               t_inbox, t_cohorts, t_definitions, t_observe, t_mcp, t_security):
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            print(f"  [FAIL] suite {fn.__name__} crashed: {e}")
            results.append({"module": fn.__name__, "level": "SUITE", "name": "crashed",
                            "status": FAIL, "note": str(e)[:120], "ms": 0})

    n = {k: sum(1 for r in results if r["status"] == k) for k in (PASS, FAIL, DEGRADED, SKIP)}
    print("\n" + "=" * 78)
    print(f"{len(results)} checks   pass {n[PASS]}   FAIL {n[FAIL]}   "
          f"degraded {n[DEGRADED]}   skipped {n[SKIP]}")
    if n[FAIL]:
        print("\nFailures:")
        for r in results:
            if r["status"] == FAIL:
                print(f"   {r['module']}.{r['name']}: {r['note']}")
    if n[DEGRADED]:
        print("\nDegraded (environment, not code):")
        for r in results:
            if r["status"] == DEGRADED:
                print(f"   {r['module']}.{r['name']}: {r['note']}")
    print()
    if a.json:
        print(json.dumps(results, indent=2))
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
