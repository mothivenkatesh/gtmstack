"""
Automated tests for the resilient transport cascade (api/_fetch.py).

Tests the 7-layer engine in isolation, positive and negative, with no real
network: the transport call is patched and time.sleep is neutralised, so the
whole suite runs in milliseconds and is deterministic.

Run:  python tests/test_fetch.py        (or: python -m unittest -v tests.test_fetch)
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import _fetch  # noqa: E402


class FakeResp:
    """Minimal stand-in for a requests/curl_cffi response."""
    def __init__(self, status, headers=None, body=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FetchTests(unittest.TestCase):

    def setUp(self):
        _fetch._HOSTS.clear()
        _fetch._PROXY_RESTED.clear()
        self._orig_transport = _fetch._transport_get
        self._orig_sleep = time.sleep
        time.sleep = lambda *a, **k: None          # no real backoff waits
        for k in ("GTMSTACK_PROXIES", "WEBSHARE_PROXY_URL", "OPENAI_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        _fetch._transport_get = self._orig_transport
        time.sleep = self._orig_sleep

    def _seq(self, items):
        """Patch the transport to yield `items` (a FakeResp or an Exception) per
        attempt, recording how many times it was called and with which proxy."""
        calls = {"n": 0, "proxies": []}
        it = iter(items)

        def fake(url, headers, timeout, impersonate, proxydict):
            calls["n"] += 1
            calls["proxies"].append(proxydict)
            item = next(it)
            if isinstance(item, Exception):
                raise item
            return item
        _fetch._transport_get = fake
        return calls

    # ---- positive paths -----------------------------------------------------
    def test_200_first_try(self):
        self._seq([FakeResp(200, body={"ok": 1})])
        r = _fetch.get("https://a.test/x")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(_fetch.status().get("a.test", {}).get("open"))

    def test_429_then_200_retries(self):
        c = self._seq([FakeResp(429), FakeResp(200)])
        r = _fetch.get("https://b.test/x", retries=3)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c["n"], 2)

    def test_5xx_then_200_retries(self):
        c = self._seq([FakeResp(503), FakeResp(200)])
        r = _fetch.get("https://c.test/x", retries=2)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c["n"], 2)

    def test_connection_error_then_success(self):
        c = self._seq([ConnectionError("reset"), FakeResp(200)])
        r = _fetch.get("https://d.test/x", retries=2)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c["n"], 2)

    # ---- layer 4: backoff / Retry-After -------------------------------------
    def test_retry_after_header_honored(self):
        slept = []
        time.sleep = lambda s: slept.append(s)
        self._seq([FakeResp(429, headers={"Retry-After": "2"}), FakeResp(200)])
        _fetch.get("https://e.test/x", retries=2)
        self.assertIn(2.0, slept)

    def test_malformed_retry_after_does_not_crash(self):
        self._seq([FakeResp(429, headers={"Retry-After": "soon"}), FakeResp(200)])
        r = _fetch.get("https://f.test/x", retries=2)
        self.assertEqual(r.status_code, 200)

    # ---- 4xx passthrough (not retried) --------------------------------------
    def test_403_not_retried(self):
        c = self._seq([FakeResp(403)])
        r = _fetch.get("https://g.test/x", retries=3)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(c["n"], 1)              # auth errors are not transient

    def test_fail_status_403_trips_breaker_and_serves_archive(self):
        # A Cloudflare 403 with fail_status={403} must be a HARD failure: not
        # retried, tripped toward the breaker, and served from archive. Without
        # this, review-site blocks read as a clean empty page.
        c = self._seq([FakeResp(403)])
        r = _fetch.get("https://cf.test/x", retries=3,
                       fail_status={403}, archive=lambda: "ARCH")
        self.assertEqual(r, "ARCH")              # fell to archive, not returned 403
        self.assertEqual(c["n"], 1)              # not retried
        self.assertEqual(_fetch._state("cf.test").fails, 1)   # counted as a fail

    def test_fail_status_403_trips_breaker_after_threshold(self):
        # Repeated blocks trip the breaker open (fast-fail), unlike a plain 403.
        for _ in range(_fetch.BREAKER_FAILS):
            self._seq([FakeResp(403)])
            _fetch.get("https://cf2.test/x", retries=0, fail_status={403})
        st = _fetch._state("cf2.test")
        self.assertTrue(st.open_until > time.time())

    # ---- degradation when retries exhausted ---------------------------------
    def test_persistent_5xx_returns_response(self):
        c = self._seq([FakeResp(503)] * 4)
        r = _fetch.get("https://h.test/x", retries=3)
        self.assertEqual(r.status_code, 503)     # caller branches on it
        self.assertEqual(c["n"], 4)

    def test_persistent_5xx_with_archive_falls_back(self):
        self._seq([FakeResp(503)] * 4)
        r = _fetch.get("https://i.test/x", retries=3, archive=lambda: "ARCHIVE")
        self.assertEqual(r, "ARCHIVE")           # layer 6

    def test_persistent_connection_error_raises(self):
        self._seq([ConnectionError("x")] * 3)
        with self.assertRaises(ConnectionError):
            _fetch.get("https://j.test/x", retries=2)

    # ---- layer 7: circuit breaker -------------------------------------------
    def test_breaker_trips_and_fast_fails(self):
        n = _fetch.BREAKER_FAILS
        self._seq([ConnectionError("x")] * n)
        for _ in range(n):
            with self.assertRaises(Exception):
                _fetch.get("https://k.test/x", retries=0)
        self.assertTrue(_fetch.status()["k.test"]["open"])

        # breaker open -> must NOT touch the transport, raises Blocked
        touched = {"n": 0}

        def boom(*a, **k):
            touched["n"] += 1
            raise AssertionError("transport called while breaker open")
        _fetch._transport_get = boom
        with self.assertRaises(_fetch.Blocked):
            _fetch.get("https://k.test/x", retries=0)
        self.assertEqual(touched["n"], 0)

    def test_archive_served_when_breaker_open(self):
        n = _fetch.BREAKER_FAILS
        self._seq([ConnectionError("x")] * n)
        for _ in range(n):
            try:
                _fetch.get("https://l.test/x", retries=0)
            except Exception:
                pass
        r = _fetch.get("https://l.test/x", retries=0, archive=lambda: "ARCH")
        self.assertEqual(r, "ARCH")

    def test_breaker_recovers_on_success_after_cooldown(self):
        st = _fetch._state("m.test")
        st.fails = _fetch.BREAKER_FAILS
        st.open_until = time.time() - 1          # cooldown already elapsed
        self._seq([FakeResp(200)])
        r = _fetch.get("https://m.test/x")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_fetch.status()["m.test"]["fails"], 0)

    # ---- layer 5: BYO proxy pool --------------------------------------------
    def test_no_proxy_when_unset(self):
        c = self._seq([FakeResp(200)])
        _fetch.get("https://n.test/x")
        self.assertIsNone(c["proxies"][0])

    def test_proxy_used_when_configured(self):
        os.environ["GTMSTACK_PROXIES"] = "http://p1:1,http://p2:2"
        c = self._seq([FakeResp(200)])
        _fetch.get("https://o.test/x")
        self.assertIsNotNone(c["proxies"][0])

    def test_proxy_rested_on_failure(self):
        os.environ["GTMSTACK_PROXIES"] = "http://only:1"
        self._seq([ConnectionError("boom"), FakeResp(200)])
        _fetch.get("https://p.test/x", retries=2)
        self.assertTrue(any(v > 0 for v in _fetch._PROXY_RESTED.values()))

    # ---- observability ------------------------------------------------------
    def test_status_reports_per_host_state(self):
        self._seq([FakeResp(200)])
        _fetch.get("https://q.test/x")
        snap = _fetch.status()
        self.assertIn("q.test", snap)
        self.assertEqual(snap["q.test"]["fails"], 0)
        self.assertFalse(snap["q.test"]["open"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
