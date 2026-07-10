"""
Automated tests for the competitive monitor store + dedup (_mentions.py) and the
review date parsing (_reviews.py). No network: the local JSON store is exercised
directly and date parsing is pure. Runs in milliseconds.

Run:  python tests/test_monitor.py
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import _mentions       # noqa: E402
import _reviews        # noqa: E402
import _enrich         # noqa: E402


class DedupKeyTests(unittest.TestCase):
    def test_kind_aware_post_vs_comment(self):
        p = {"kind": "post", "url": "https://r.co/t/abc", "text": "hi"}
        c = {"kind": "comment", "url": "https://r.co/t/abc", "text": "a reply"}
        self.assertNotEqual(_mentions.dedup_key(p), _mentions.dedup_key(c))

    def test_two_comments_same_thread_distinct(self):
        c1 = {"kind": "comment", "url": "https://r.co/t/abc", "text": "first"}
        c2 = {"kind": "comment", "url": "https://r.co/t/abc", "text": "second"}
        self.assertNotEqual(_mentions.dedup_key(c1), _mentions.dedup_key(c2))

    def test_explicit_id_preferred(self):
        m = {"kind": "post", "id": "xyz", "url": "https://r.co/1", "text": "hi"}
        self.assertEqual(_mentions.dedup_key(m), "post:xyz")

    def test_key_stable_across_calls(self):
        m = {"kind": "review", "url": "https://g2.co/r/1", "text": "great"}
        self.assertEqual(_mentions.dedup_key(m), _mentions.dedup_key(dict(m)))


class StoreTests(unittest.TestCase):
    def setUp(self):
        # force the local-file path by pointing the store at a temp dir
        self._tmp = tempfile.mkdtemp()
        self._orig_store = _mentions._STORE
        self._orig_locks = _mentions._LOCKS
        from pathlib import Path
        _mentions._STORE = Path(self._tmp)
        _mentions._LOCKS = Path(self._tmp) / "locks"
        # ensure DB path is not taken
        self._orig_db = _mentions._db
        _mentions._db = None

    def tearDown(self):
        _mentions._STORE = self._orig_store
        _mentions._LOCKS = self._orig_locks
        _mentions._db = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _rows(self):
        return [
            {"kind": "post", "id": "p1", "url": "https://r.co/1",
             "text": "cashfree great", "where": "reddit", "ts": "2026-07-01T00:00:00+00:00"},
            {"kind": "comment", "id": "c1", "url": "https://r.co/1",
             "text": "razorpay reply", "where": "reddit", "ts": "2026-07-01T01:00:00+00:00"},
        ]

    def test_idempotent_reruns(self):
        ins1, upd1 = _mentions.upsert("g", self._rows())
        ins2, upd2 = _mentions.upsert("g", self._rows())
        self.assertEqual(len(ins1), 2)
        self.assertEqual(upd1, 0)
        self.assertEqual(len(ins2), 0)     # nothing new on the second run
        self.assertEqual(upd2, 2)

    def test_intra_run_dupes_collapsed(self):
        rows = self._rows() + self._rows()   # same rows twice in one batch
        ins, upd = _mentions.upsert("g", rows)
        self.assertEqual(len(ins), 2)        # collapsed to 2 unique

    def test_cross_group_lands_in_both(self):
        ins_a, _ = _mentions.upsert("group_a", self._rows())
        ins_b, _ = _mentions.upsert("group_b", self._rows())
        self.assertEqual(len(ins_a), 2)
        self.assertEqual(len(ins_b), 2)      # same rows, different group -> fresh

    def test_recent_returns_stored(self):
        _mentions.upsert("g", self._rows())
        got = _mentions.recent("g", limit=10)
        self.assertEqual(len(got), 2)

    def test_lock_single_flight(self):
        self.assertTrue(_mentions.acquire_lock("t", ttl=3600))
        self.assertFalse(_mentions.acquire_lock("t", ttl=3600))  # held
        _mentions.release_lock("t")
        self.assertTrue(_mentions.acquire_lock("t", ttl=3600))
        _mentions.release_lock("t")


class ReviewDateTests(unittest.TestCase):
    def test_iso_parsed(self):
        self.assertTrue(_reviews._parse_date("2026-03-15T10:00:00Z").startswith("2026-03-15"))

    def test_bare_date_parsed(self):
        self.assertTrue(_reviews._parse_date("2026-03-15").startswith("2026-03-15"))

    def test_relative_parsed(self):
        self.assertIsNotNone(_reviews._parse_date("2 days ago"))

    def test_garbage_is_none_not_fabricated(self):
        # the fix: no real date -> None -> row dropped, never stamped with now()
        self.assertIsNone(_reviews._parse_date("not a date"))
        self.assertIsNone(_reviews._parse_date(""))


class EnrichTests(unittest.TestCase):
    def test_lexicon_sentiment(self):
        self.assertEqual(_enrich.heuristic_sentiment("worst support, funds on hold"), "negative")
        self.assertEqual(_enrich.heuristic_sentiment("smooth and reliable, love it"), "positive")
        self.assertEqual(_enrich.heuristic_sentiment("integrated the api"), "neutral")

    def test_enrich_tags_and_records_mode(self):
        ms = [{"text": "cashfree held my funds", "where": "reddit"}]
        _enrich.enrich_mentions(ms, cap=10, use_llm=False)
        self.assertEqual(ms[0]["sentiment"], "negative")
        self.assertEqual(ms[0]["enrich_mode"], "lexicon")
        self.assertEqual(ms[0]["company"], "Unknown")


class VelocityTests(unittest.TestCase):
    """Moment-marketing spike detection: a burst of negative competitor chatter
    in the last 24h versus the trailing 7-day baseline."""
    def setUp(self):
        import _monitor
        self._m = _monitor
        self._orig = _monitor._mentions

    def tearDown(self):
        self._m._mentions = self._orig

    def _fake_store(self, rows):
        class _S:
            @staticmethod
            def recent(gid, limit=1000): return rows
        self._m._mentions = _S()

    def _row(self, brand, sentiment, hours_ago):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        return {"brand": brand, "sentiment": sentiment, "post_ts": ts}

    def test_spike_detected(self):
        rows = [self._row("razorpay", "negative", 2) for _ in range(6)]   # 6 in last 24h
        rows += [self._row("razorpay", "negative", 24*5)]                 # tiny baseline
        self._fake_store(rows)
        spikes = self._m._velocity_check({"id": "g", "competitors": ["razorpay"]})
        self.assertTrue(spikes and spikes[0]["brand"] == "razorpay")

    def test_no_spike_when_quiet(self):
        rows = [self._row("razorpay", "negative", 2)]                     # 1 in 24h, under floor
        self._fake_store(rows)
        self.assertIsNone(self._m._velocity_check({"id": "g", "competitors": ["razorpay"]}))

    def test_positive_mentions_ignored(self):
        rows = [self._row("razorpay", "positive", 2) for _ in range(9)]
        self._fake_store(rows)
        self.assertIsNone(self._m._velocity_check({"id": "g", "competitors": ["razorpay"]}))


class GroupSaveTests(unittest.TestCase):
    def setUp(self):
        import _groups
        self._g = _groups
        self._tmp = tempfile.mkdtemp()
        from pathlib import Path
        self._orig = _groups._STORE
        _groups._STORE = Path(self._tmp) / "groups.json"

    def tearDown(self):
        self._g._STORE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_and_readback(self):
        saved = self._g.save_group({"id": "competitor_watch", "window_days": 14})
        self.assertEqual(saved["window_days"], 14)
        # built-in fields survive a partial edit
        self.assertTrue(len(saved["keywords"]) > 0)

    def test_bad_group_rejected(self):
        self.assertIsNone(self._g.save_group({"window_days": 5}))   # no id

    def test_only_editable_fields_kept(self):
        saved = self._g.save_group({"id": "x", "name": "X", "evil": "drop me",
                                    "keywords": ["a"]})
        self.assertNotIn("evil", saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
