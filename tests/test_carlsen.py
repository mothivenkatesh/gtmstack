"""
Unit tests for the Carlsen scan strategy (api/_carlsen.py).

Pure logic, no network. Verifies the chess principles actually hold in code:
opening book first, king (LinkedIn) last, prophylaxis (skip tripped hosts),
king-safety resign, budget split, and the post evaluation ranking.

Run: python tests/test_carlsen.py
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import _carlsen as C  # noqa: E402

GROUP = {
    "id": "payment_gateway",
    "name": "Payment Gateway",
    "keywords": ["cashfree", "razorpay", "payment gateway"],
    "primary": ["cashfree"],
}
ALL = ["github", "youtube", "reddit", "x", "linkedin"]


class OrderingTests(unittest.TestCase):
    def test_opening_book_first_king_last(self):
        order = C.order_sources(ALL)
        self.assertIn(order[0], C.OPENING)          # develop a safe piece first
        self.assertEqual(order[-1], C.KING)         # king always last

    def test_prophylaxis_skips_open_breaker(self):
        status = {"api.github.com": {"open": True, "fails": 5}}
        order = C.order_sources(ALL, status)
        self.assertNotIn("github", order)           # tripped host is skipped
        self.assertIn("youtube", order)

    def test_king_dropped_when_its_host_is_tripped(self):
        status = {"www.linkedin.com": {"open": True, "fails": 9}}
        self.assertNotIn("linkedin", C.order_sources(ALL, status))


class PlanTests(unittest.TestCase):
    def test_king_is_sequential_capped_and_last(self):
        moves = C.plan(GROUP, ALL, budget_s=45)
        king = moves[-1]
        self.assertTrue(king["is_king"])
        self.assertTrue(king["sequential"])
        self.assertLessEqual(len(king["keywords"]), C.KING_MAX_KEYWORDS)

    def test_body_budget_excludes_king_slice(self):
        moves = C.plan(GROUP, ALL, budget_s=45)
        body = [m for m in moves if not m["is_king"]]
        self.assertAlmostEqual(sum(m["budget_s"] for m in body),
                               45 - C.KING_BUDGET_S, delta=1.0)

    def test_safer_source_gets_more_clock(self):
        moves = {m["source"]: m for m in C.plan(GROUP, ALL, budget_s=60)}
        self.assertGreater(moves["github"]["budget_s"], moves["x"]["budget_s"])

    def test_empty_when_everything_tripped(self):
        status = {h[0]: {"open": True} for h in C.SOURCE_HOSTS.values()}
        self.assertEqual(C.plan(GROUP, ALL, status, budget_s=30), [])


class SafetyTests(unittest.TestCase):
    def test_king_resigns_on_challenge_or_first_fail(self):
        self.assertTrue(C.resign("linkedin", fails=0, challenged=True))
        self.assertTrue(C.resign("linkedin", fails=1))
        self.assertFalse(C.resign("github", fails=1))   # body sources tolerate more
        self.assertTrue(C.resign("github", fails=3))

    def test_politeness_gap_widens_with_fails(self):
        self.assertGreater(C.politeness_gap("reddit", fails=3),
                           C.politeness_gap("reddit", fails=0))
        self.assertGreater(C.politeness_gap("linkedin", 0),
                           C.politeness_gap("reddit", 0))   # king paced slowest


class EvaluationTests(unittest.TestCase):
    def _post(self, text, eng, age_days):
        ts = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        return {"text": text, "engagement": [{"value": str(eng), "label": "likes"}], "ts": ts}

    def test_fresh_high_engagement_relevant_ranks_first(self):
        fresh = self._post("cashfree vs razorpay, which gateway?", 500, 0.2)
        stale = self._post("cashfree outage last year", 500, 90)
        offtopic = self._post("unrelated chatter", 500, 0.2)
        ranked = C.rank([stale, offtopic, fresh], GROUP)
        self.assertEqual(ranked[0]["text"], fresh["text"])
        self.assertTrue(all("score" in p for p in ranked))

    def test_comparison_beats_single_mention_at_equal_reach(self):
        compare = self._post("cashfree vs razorpay", 100, 1)
        single = self._post("cashfree is fine", 100, 1)
        self.assertGreater(C.evaluate(compare, GROUP), C.evaluate(single, GROUP))


if __name__ == "__main__":
    unittest.main(verbosity=2)
