"""
Tests for the approval engine - the security boundary.

This is the gate that decides whether an agent may write, spend, or act at all.
It is now reachable from a public deployment, so it gets the most adversarial
tests in the repo. The properties asserted here are the ones whose failure would
be a security incident, not a bug:

  1. A guardrail can NEVER be unlocked by a standing policy.
  2. A read is free; a write or spend is not.
  3. An auto-allow always cites the rule that allowed it.
  4. ALWAYS creates a standing policy; ONCE does not.
  5. A policy for one agent does not leak to another.

Stdlib unittest, isolated on a temp DB, runs in milliseconds.
    python tests/test_approvals.py

No em dashes.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "api"))

_TMP = tempfile.mkdtemp(prefix="gtmstack_test_")
os.environ["GTMSTACK_GRAPH_DB"] = os.path.join(_TMP, "graph.db")
os.environ["OBSERVE_DB"] = os.path.join(_TMP, "events.db")

import _approvals as A          # noqa: E402
import _graph as G              # noqa: E402
from _risk import RiskClass, classify, is_consequential, tier_meta  # noqa: E402


class RiskClassification(unittest.TestCase):
    def test_unknown_action_defaults_to_read(self):
        """Fail SAFE on the read side: an unclassified action is inert, so a new
        tool cannot accidentally be treated as a spend."""
        self.assertIs(classify("some_new_tool"), RiskClass.READ)

    def test_writes_and_spends_classified(self):
        self.assertIs(classify("send_message"), RiskClass.WRITE)
        self.assertIs(classify("write_signal"), RiskClass.WRITE)
        self.assertIs(classify("set_budget"), RiskClass.SPEND)
        self.assertIs(classify("bulk_delete"), RiskClass.SPEND)

    def test_only_read_is_inconsequential(self):
        self.assertFalse(is_consequential(RiskClass.READ))
        self.assertTrue(is_consequential(RiskClass.WRITE))
        self.assertTrue(is_consequential(RiskClass.SPEND))

    def test_override_wins_over_base(self):
        self.assertIs(classify("send_message", overrides=lambda n: RiskClass.SPEND),
                      RiskClass.SPEND)

    def test_every_tier_has_ui_copy(self):
        for r in RiskClass:
            m = tier_meta(r)
            self.assertTrue(m["label"] and m["gate"] and m["desc"])


class Guardrails(unittest.TestCase):
    """The hard limits. These must hold even against an explicit standing grant,
    which is the whole difference between a guardrail and a default."""

    def setUp(self):
        G.reset()

    def test_excluded_account_blocked(self):
        d = A.decide("send_message", agent="writer", payload={"excluded": True})
        self.assertFalse(d.allowed)
        self.assertIn("guardrail", d.reason)

    def test_over_budget_blocked(self):
        d = A.decide("set_budget", agent="allocator",
                     payload={"amount": A.BUDGET_CAP + 1})
        self.assertFalse(d.allowed)
        self.assertIn("guardrail", d.reason)

    def test_under_budget_not_guardrail_blocked(self):
        """Still needs approval, but for tier reasons, not a guardrail."""
        d = A.decide("set_budget", agent="allocator", payload={"amount": 10})
        self.assertFalse(d.allowed)
        self.assertNotIn("guardrail", d.reason)
        self.assertTrue(d.needs_user)

    def test_bulk_delete_always_blocked(self):
        self.assertFalse(A.decide("bulk_delete", agent="steward").allowed)

    def test_bulk_update_blocked_only_over_cap(self):
        small = A.decide("bulk_update", agent="steward",
                         payload={"count": A.BULK_CAP - 1})
        big = A.decide("bulk_update", agent="steward",
                       payload={"count": A.BULK_CAP + 1})
        self.assertNotIn("guardrail", small.reason)
        self.assertIn("guardrail", big.reason)

    def test_unsourced_claim_blocked(self):
        d = A.decide("send_message", agent="writer",
                     payload={"claims": ["we are 3x faster"], "sources": []})
        self.assertFalse(d.allowed)
        self.assertIn("guardrail", d.reason)

    def test_standing_policy_CANNOT_unlock_a_guardrail(self):
        """The single most important test in this file. Grant the broadest
        possible policy, then confirm the guardrail still refuses."""
        A.grant("bulk_delete", "*", None)
        A.grant("send_message", "*", None)
        self.assertFalse(A.decide("bulk_delete", agent="steward").allowed)
        d = A.decide("send_message", agent="writer", payload={"excluded": True})
        self.assertFalse(d.allowed, "an exclusion list must survive any grant")


class Tiers(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_read_is_automatic_and_cites_a_rule(self):
        d = A.decide("classify_relevance", agent="listener")
        self.assertTrue(d.allowed)
        self.assertFalse(d.needs_user)
        self.assertTrue(d.rule, "an auto-allow with no rule is indistinguishable "
                                "from an agent doing whatever it wants")

    def test_write_needs_a_human_by_default(self):
        d = A.decide("send_message", agent="listener")
        self.assertFalse(d.allowed)
        self.assertTrue(d.needs_user)

    def test_spend_needs_a_human_by_default(self):
        d = A.decide("set_budget", agent="allocator")
        self.assertFalse(d.allowed)
        self.assertTrue(d.needs_user)

    def test_decision_serialises(self):
        d = A.decide("classify_relevance", agent="listener").as_dict()
        for k in ("allowed", "reason", "needs_user", "rule", "risk"):
            self.assertIn(k, d)


class StandingPolicies(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_grant_then_allowed_with_rule(self):
        self.assertFalse(A.decide("send_message", agent="listener").allowed)
        A.grant("send_message", "*", "listener")
        d = A.decide("send_message", agent="listener")
        self.assertTrue(d.allowed)
        self.assertIn("standing policy", d.rule)

    def test_policy_does_not_leak_across_agents(self):
        """A grant to Listener must not silently authorise Writer."""
        A.grant("send_message", "*", "listener")
        self.assertTrue(A.decide("send_message", agent="listener").allowed)
        self.assertFalse(A.decide("send_message", agent="writer").allowed)

    def test_policy_does_not_leak_across_actions(self):
        A.grant("send_message", "*", "listener")
        self.assertFalse(A.decide("set_budget", agent="listener").allowed)

    def test_grant_is_idempotent(self):
        A.grant("send_message", "*", "listener")
        A.grant("send_message", "*", "listener")
        same = [p for p in A.policies() if p["data"]["action"] == "send_message"]
        self.assertEqual(len(same), 1)

    def test_revoke_restores_the_gate(self):
        pid = A.grant("send_message", "*", "listener")
        self.assertTrue(A.decide("send_message", agent="listener").allowed)
        A.revoke(pid)
        self.assertFalse(A.decide("send_message", agent="listener").allowed)


class Queue(unittest.TestCase):
    def setUp(self):
        G.reset()

    def test_request_appears_pending(self):
        A.request("send_message", "listener", summary="tell you about it")
        self.assertEqual(len(A.pending()), 1)

    def test_once_approves_without_creating_a_policy(self):
        aid = A.request("send_message", "listener")
        out = A.resolve(aid, A.ONCE)
        self.assertTrue(out["ok"])
        self.assertIsNone(out["policy"])
        self.assertEqual(len(A.policies()), 0)
        self.assertEqual(len(A.pending()), 0, "resolving must clear the queue")

    def test_always_creates_a_standing_policy(self):
        aid = A.request("send_message", "listener")
        out = A.resolve(aid, A.ALWAYS)
        self.assertTrue(out["policy"])
        self.assertTrue(A.decide("send_message", agent="listener").allowed)

    def test_deny_clears_without_granting(self):
        aid = A.request("send_message", "listener")
        A.resolve(aid, A.DENY)
        self.assertEqual(len(A.pending()), 0)
        self.assertFalse(A.decide("send_message", agent="listener").allowed)

    def test_unknown_action_is_handled(self):
        out = A.resolve("action_does_not_exist", A.ONCE)
        self.assertFalse(out["ok"])

    def test_resolving_twice_is_safe(self):
        aid = A.request("send_message", "listener")
        A.resolve(aid, A.ONCE)
        self.assertTrue(A.resolve(aid, A.ONCE)["ok"])

    def test_stats_report_the_shrink_metric(self):
        aid = A.request("send_message", "listener")
        A.resolve(aid, A.ALWAYS)
        s = A.stats()
        self.assertEqual(s["standing_policies"], 1)
        self.assertEqual(s["pending"], 0)
        self.assertGreaterEqual(s["asked_this_week"], 1)
        self.assertTrue(s["guardrails"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
