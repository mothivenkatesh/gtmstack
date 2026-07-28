"""
Tests for the harness: context graph, cohorts, definitions, agents, observability.

The properties here are the ones the PRD's claims rest on. If any of these
break, a stated product guarantee is silently false:

  graph       idempotent upserts (a re-run must not duplicate), provenance on
              every node, edges resolvable
  cohorts     membership is DETERMINISTIC and every member carries its reason
  definitions one authoritative version per metric, promotion bumps the version
  agents      routing is honest about unbuilt teammates; the gate queues rather
              than forces; runnable agents all have procedures
  observe     logging never raises, metrics roll up, the table stays bounded

    python tests/test_harness.py

No em dashes.
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "api"))

_TMP = tempfile.mkdtemp(prefix="gtmstack_test_")
os.environ["GTMSTACK_GRAPH_DB"] = os.path.join(_TMP, "graph.db")
os.environ["OBSERVE_DB"] = os.path.join(_TMP, "events.db")

import _agents as AG           # noqa: E402
import _deliver as DL          # noqa: E402
import _watch as W             # noqa: E402
import _cohorts as C           # noqa: E402
import _definitions as D       # noqa: E402
import _graph as G             # noqa: E402
import _observe as O           # noqa: E402


class Graph(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_upsert_with_key_is_idempotent(self):
        """The property the whole retry story depends on: running Listener twice
        over the same post updates one node, it does not create two."""
        a = G.upsert("signal", {"text": "hello"}, key="reddit:1")
        b = G.upsert("signal", {"text": "hello again"}, key="reddit:1")
        self.assertEqual(a, b)
        self.assertEqual(len(G.query("signal")), 1)
        self.assertEqual(G.get(a)["data"]["text"], "hello again")

    def test_upsert_merges_rather_than_replaces(self):
        k = "reddit:merge"
        G.upsert("signal", {"text": "t", "sentiment": "positive"}, key=k)
        G.upsert("signal", {"text": "t2"}, key=k)
        self.assertEqual(G.get(G.upsert("signal", {}, key=k))["data"]["sentiment"],
                         "positive", "an update must not silently drop fields")

    def test_no_key_means_distinct_nodes(self):
        G.upsert("signal", {"text": "a"})
        G.upsert("signal", {"text": "a"})
        self.assertEqual(len(G.query("signal")), 2)

    def test_provenance_is_recorded(self):
        nid = G.upsert("signal", {"text": "x"}, key="k", agent="listener",
                       run_id="run_1", source="https://example.com/p")
        n = G.get(nid)
        self.assertEqual(n["agent"], "listener")
        self.assertEqual(n["run_id"], "run_1")
        self.assertEqual(n["source"], "https://example.com/p")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            G.upsert("not_a_type", {})

    def test_edges_and_neighbours(self):
        s = G.upsert("signal", {"text": "s"}, key="s1")
        p = G.upsert("person", {"handle": "h"}, key="p1")
        G.link(s, "authored_by", p)
        nb = G.neighbours(s, "authored_by")
        self.assertEqual(len(nb), 1)
        self.assertEqual(nb[0]["node"]["id"], p)

    def test_link_is_idempotent(self):
        s = G.upsert("signal", {}, key="s"); p = G.upsert("person", {}, key="p")
        self.assertEqual(G.link(s, "r", p), G.link(s, "r", p))
        self.assertEqual(G.counts()["edges"], 1)

    def test_query_where_filters(self):
        G.upsert("signal", {"sentiment": "negative"}, key="a")
        G.upsert("signal", {"sentiment": "positive"}, key="b")
        self.assertEqual(len(G.query("signal", where={"sentiment": "negative"})), 1)

    def test_get_missing_returns_none(self):
        self.assertIsNone(G.get("nope"))


class Cohorts(unittest.TestCase):
    def setUp(self):
        G.reset()
        C.seed()
        for i, (intent, sent) in enumerate(
                [("category_intent", "neutral"), ("category_intent", "positive"),
                 ("brand_mention", "negative"), ("complaint", "negative")]):
            G.upsert("signal", {"intent_type": intent, "sentiment": sent,
                                "platform": "reddit", "text": f"post {i}"},
                     key=f"reddit:{i}")

    def test_membership_is_deterministic(self):
        """Same graph, same answer, every time. A model asked to enumerate a set
        would drift; this must not."""
        runs = [C.members("buying_intent")["count"] for _ in range(5)]
        self.assertEqual(len(set(runs)), 1)

    def test_membership_is_correct(self):
        self.assertEqual(C.members("buying_intent")["count"], 2)
        self.assertEqual(C.members("unhappy_public")["count"], 2)

    def test_every_member_states_its_reason(self):
        for m in C.members("buying_intent")["members"]:
            self.assertTrue(m["reason"], "a cohort with unexplained members is a black box")

    def test_unknown_cohort_errors(self):
        self.assertIn("error", C.members("does_not_exist"))

    def test_seed_is_idempotent(self):
        before = len(C.all()); C.seed(); C.seed()
        self.assertEqual(len(C.all()), before)

    def test_create_then_query(self):
        C.create("Negative only", "just the negative ones", "signal",
                 {"sentiment_in": ["negative"]}, "dynamic")
        self.assertEqual(C.members("negative_only")["count"], 2)

    def test_lift_is_honest_when_no_outcomes(self):
        """We must not invent an outcome lift with no closed-won data. Claiming
        one would undermine the exact thing the cohort is selling."""
        for c in C.all():
            if c.get("lift"):
                self.assertIsNone(c["lift"]["outcome_lift"])


class Definitions(unittest.TestCase):
    def setUp(self):
        G.reset()
        D.seed()

    def test_seeded_and_idempotent(self):
        n = len(D.all()); D.seed()
        self.assertEqual(len(D.all()), n)
        self.assertGreaterEqual(n, 6)

    def test_resolution_is_deterministic(self):
        a = [d["key"] for d in D.resolve_for_question("what is our win rate")]
        b = [d["key"] for d in D.resolve_for_question("what is our win rate")]
        self.assertEqual(a, b)
        self.assertIn("win_rate", a)

    def test_promote_creates_v1_then_bumps(self):
        r1 = D.promote("Cycle Length", "close - created")
        self.assertEqual(r1["version"], 1)
        r2 = D.promote("Cycle Length", "close - qualified")
        self.assertEqual(r2["version"], 2)

    def test_promote_requires_a_name(self):
        self.assertFalse(D.promote("", "x")["ok"])

    def test_one_row_per_metric(self):
        D.promote("Cycle Length", "a"); D.promote("Cycle Length", "b")
        self.assertEqual(sum(1 for d in D.all() if d["key"] == "cycle_length"), 1)


class Agents(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_every_runnable_agent_has_a_procedure(self):
        """The bug this repo actually shipped: eight agents advertised with zero
        steps, so they reported success over an empty card."""
        for aid, a in AG.AGENTS.items():
            self.assertTrue(a.get("steps"), f"{aid} is runnable with no steps")
            self.assertTrue(a.get("guardrails"), f"{aid} has no guardrails")

    def test_catalog_never_exposes_an_unbuilt_agent_as_runnable(self):
        self.assertTrue(all(c["runnable"] for c in AG.catalog()))
        self.assertTrue(all(not c["runnable"] for c in AG.roadmap()))

    def test_roadmap_and_agents_are_disjoint(self):
        self.assertFalse(set(AG.AGENTS) & set(AG.ROADMAP))

    def test_routing_picks_the_right_teammate(self):
        for text, want in (
                ("watch for people asking which payment gateway", "listener"),
                ("how many duplicate contacts do we have", "steward"),
                ("what is our win rate this quarter", "analyst"),
                ("who is talking about us on reddit", "listener")):
            self.assertEqual(AG.route(text)["agent"], want, f"misrouted: {text}")

    def test_routing_is_honest_about_unbuilt_teammates(self):
        r = AG.route("what competitors changed their pricing change")
        if r["agent"] in AG.ROADMAP:
            self.assertTrue(r.get("roadmap"))
            self.assertIn("not built", r["why"])

    def test_running_a_roadmap_agent_is_refused_clearly(self):
        rec, status = AG.run("watcher", {})
        self.assertEqual(status, 400)
        self.assertTrue(rec.get("roadmap"))

    def test_unknown_agent_404s(self):
        self.assertEqual(AG.run("nobody", {})[1], 404)

    def test_plan_marks_consequential_steps(self):
        p = AG.plan("listener", {"query": "x"})
        self.assertTrue(any(s["needs_approval"] for s in p["steps"]),
                        "listener writes and messages, so something must be gated")
        for s in p["steps"]:
            if s["auto"]:
                self.assertTrue(s["rule"], "an auto step must cite its rule")

    def test_plan_self_flags_weak_input(self):
        self.assertTrue(AG.plan("listener", {})["risk_flags"])

    def test_run_queues_rather_than_forcing(self):
        """The gate must stop the write, not push it through."""
        rec, _ = AG.run("steward", {"query": "x"})
        gated = [s for s in rec["steps"] if s["status"] == "awaiting_approval"]
        self.assertTrue(gated)
        self.assertTrue(rec["queued"])

    def test_run_is_recorded_in_the_graph(self):
        AG.run("steward", {"query": "x"})
        self.assertTrue(G.query("run"))


class Observe(unittest.TestCase):
    def setUp(self):
        O.reset()

    def test_log_and_read_back(self):
        O.log(O.RUN_END, agent="listener", ok=True, ms=12.0, summary="done")
        ev = O.recent(10)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["agent"], "listener")

    def test_log_never_raises(self):
        """Telemetry that can break the request it measures is worse than none."""
        class Boom:
            def __repr__(self): raise RuntimeError("boom")
        try:
            O.log(O.STEP, summary=Boom(), weird=Boom())
        except Exception as e:                                   # noqa: BLE001
            self.fail(f"log() raised {e}")

    def test_metrics_rollup(self):
        O.log(O.RUN_END, agent="listener", ok=True, ms=100)
        O.log(O.RUN_END, agent="listener", ok=False, ms=300)
        m = O.metrics()
        self.assertEqual(m["runs"], 2)
        self.assertEqual(m["runs_ok"], 1)
        self.assertEqual(m["runs_failed"], 1)
        self.assertEqual(m["success_rate"], 50.0)
        self.assertEqual(m["by_agent"]["listener"]["runs"], 2)

    def test_metrics_on_empty_is_safe(self):
        m = O.metrics()
        self.assertTrue(m["available"])
        self.assertEqual(m["runs"], 0)
        self.assertIsNone(m["success_rate"])

    def test_errors_surface_in_top_errors(self):
        O.log(O.ERROR, agent="listener", ok=False, summary="reddit timed out")
        self.assertEqual(O.metrics()["top_errors"][0]["error"], "reddit timed out")

    def test_filter_by_run(self):
        O.log(O.STEP, run_id="r1"); O.log(O.STEP, run_id="r2")
        self.assertEqual(len(O.recent(10, run_id="r1")), 1)

    def test_a_blocked_decision_is_not_an_error(self):
        """A gate refusing an ungranted write is the system working. Counting it
        as a failure makes a healthy install look broken."""
        O.log(O.DECISION, agent="listener", ok=False, summary="write needs approval")
        O.log(O.RUN_END, agent="listener", ok=True, ms=10)
        m = O.metrics()
        self.assertEqual(m["errors"], 0, "a blocked decision must not count as an error")
        self.assertEqual(m["blocked"], 1)
        self.assertEqual(m["success_rate"], 100.0)

    def test_a_real_error_still_counts(self):
        O.log(O.ERROR, agent="listener", ok=False, summary="reddit timed out")
        self.assertEqual(O.metrics()["errors"], 1)

    def test_prune_bounds_the_table(self):
        for i in range(40):
            O.log(O.STEP, summary=f"e{i}")
        O.prune(keep=10)
        self.assertLessEqual(len(O.recent(100)), 10)


class DeliveryAndOutcomes(unittest.TestCase):
    """The loop that turns a demo into a product: deliver once, record what the
    human did, and report a number worth paying for."""

    def setUp(self):
        G.reset()
        self.sig = G.upsert("signal", {"text": "which payment gateway should I use",
                                       "intent_type": "category_intent",
                                       "sentiment": "neutral", "platform": "reddit"},
                            key="reddit:t1", agent="listener")

    def test_pending_only_undelivered_buying_intent(self):
        G.upsert("signal", {"text": "nice docs", "intent_type": "brand_mention"},
                 key="reddit:t2", agent="listener")
        p = DL.pending()
        self.assertEqual(len(p), 1, "only buying intent should be alert-worthy")

    def test_delivery_is_idempotent(self):
        """A watch firing every six hours must never re-alert the same post."""
        G.upsert("signal", {"delivered_at": 123.0}, key="reddit:t1")
        self.assertEqual(len(DL.pending()), 0)

    def test_unconfigured_reports_ready_not_sent(self):
        """It must never pretend to have sent."""
        out = DL.deliver()
        self.assertEqual(out["sent"], 0)
        self.assertEqual(out.get("ready"), 1)
        self.assertIn("Connect", out["note"])

    def test_mark_writes_an_outcome_and_links_it(self):
        r = DL.mark(self.sig, DL.CONVERTED, note="booked a call")
        self.assertTrue(r["ok"])
        self.assertTrue(G.query("outcome"))
        self.assertTrue(G.neighbours(self.sig, "resulted_in"))

    def test_mark_rejects_a_bad_outcome(self):
        self.assertFalse(DL.mark(self.sig, "vibes")["ok"])

    def test_mark_unknown_signal_is_handled(self):
        self.assertFalse(DL.mark("signal_nope", DL.ACTIONED)["ok"])

    def test_value_is_honest_with_no_outcomes(self):
        v = DL.value()
        self.assertEqual(v["converted"], 0)
        self.assertIn("cannot tell you what it was worth", v["sentence"])

    def test_value_reports_conversions(self):
        DL.mark(self.sig, DL.CONVERTED)
        v = DL.value()
        self.assertEqual(v["converted"], 1)
        self.assertIn("became conversations", v["sentence"])


class Watches(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_add_requires_a_keyword(self):
        self.assertFalse(W.add("")["ok"])

    def test_add_is_idempotent(self):
        W.add("payment gateway"); W.add("payment gateway")
        self.assertEqual(len(W.list_watches()), 1)

    def test_a_new_watch_is_due(self):
        W.add("payment gateway")
        self.assertEqual(len(W.due()), 1)

    def test_a_just_run_watch_is_not_due(self):
        W.add("payment gateway")
        w = W.list_watches()[0]
        d = dict(w); d.pop("id", None); d["last_run"] = time.time()
        G.upsert("watch", d, key="payment gateway")
        self.assertEqual(len(W.due()), 0)

    def test_status_flags_a_never_run_watch(self):
        W.add("payment gateway")
        self.assertFalse(W.status()["healthy"])

    def test_status_is_healthy_with_no_watches_configured(self):
        self.assertEqual(W.status()["watches"], 0)


class GraphCreatedFlag(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_upsert_ex_reports_created_then_updated(self):
        """`new` must mean new, or a watch reports the same finds forever and
        every value metric downstream is inflated."""
        _, created = G.upsert_ex("signal", {"text": "a"}, key="k1")
        self.assertTrue(created)
        _, created2 = G.upsert_ex("signal", {"text": "b"}, key="k1")
        self.assertFalse(created2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
