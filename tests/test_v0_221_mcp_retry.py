"""v0.221 — MCP/HTTP retry-with-backoff coverage.

Verifies that S2 + OpenAlex urlopen calls now go through
`lib.retry.retry_with_backoff` for transient failures (HTTP 429,
5xx, network errors), and that 4xx-other passes through directly
without retry.
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request
from unittest import mock

from tests.harness import TestCase, isolated_cache, run_tests


def _http_error(code: int, reason: str = "boom") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://x", code=code, msg=reason,
        hdrs=None, fp=io.BytesIO(b""),
    )


class S2RetryTransientTests(TestCase):
    def setUp(self):
        # No real sleeps in tests.
        self._sleep_patch = mock.patch("lib.retry.time.sleep")
        self._sleep_patch.start()
        # No rate_limit writes to real cache.
        self._s2_rate_patch = mock.patch(
            "lib.s2_enrichment.rate_wait", lambda *a, **k: None,
        )
        self._s2_rate_patch.start()
        self._oa_rate_patch = mock.patch(
            "lib.rate_limit.wait", lambda *a, **k: None,
        )
        self._oa_rate_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        self._s2_rate_patch.stop()
        self._oa_rate_patch.stop()

    def test_429_retries_then_succeeds(self):
        from lib.s2_enrichment import S2Client
        client = S2Client(cache_path=":memory:", timeout=1.0)
        ok_resp = mock.MagicMock()
        ok_resp.read.return_value = b'{"data": [{"paperId": "p1"}]}'
        ok_resp.__enter__ = mock.Mock(return_value=ok_resp)
        ok_resp.__exit__ = mock.Mock(return_value=False)
        calls = [
            _http_error(429, "rate limit"),
            _http_error(429, "rate limit"),
            ok_resp,
        ]

        def _side_effect(*a, **k):
            v = calls.pop(0)
            if isinstance(v, urllib.error.HTTPError):
                raise v
            return v

        with mock.patch("urllib.request.urlopen", side_effect=_side_effect):
            r = client.search_papers(query="test", limit=1)
        # Recovered after retry — payload visible.
        self.assertNotIn("error", r)
        self.assertIn("data", r)

    def test_503_retries_exhausted(self):
        from lib.s2_enrichment import S2Client
        client = S2Client(cache_path=":memory:", timeout=1.0)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_http_error(503, "unavail"),
        ):
            r = client.search_papers(query="test", limit=1)
        self.assertIn("error", r)
        self.assertTrue(r.get("retries_exhausted"))

    def test_404_no_retry(self):
        from lib.s2_enrichment import S2Client
        client = S2Client(cache_path=":memory:", timeout=1.0)
        attempts = {"n": 0}

        def _se(*a, **k):
            attempts["n"] += 1
            raise _http_error(404, "not found")

        with mock.patch("urllib.request.urlopen", side_effect=_se):
            r = client.search_papers(query="missing", limit=1)
        # 404 returns without retry — single call.
        self.assertEqual(attempts["n"], 1)
        self.assertIn("error", r)
        self.assertFalse(r.get("retries_exhausted"))


class OpenAlexRetryTransientTests(TestCase):
    def setUp(self):
        self._sleep_patch = mock.patch("lib.retry.time.sleep")
        self._sleep_patch.start()
        # No rate_limit writes to real cache.
        self._rate_patch = mock.patch(
            "lib.rate_limit.wait", lambda *a, **k: None,
        )
        self._rate_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        self._rate_patch.stop()

    def test_500_retries_exhausted(self):
        from lib.openalex_client import OpenAlexClient
        client = OpenAlexClient(cache_path=":memory:", timeout=1.0)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, "boom"),
        ):
            r = client._request("/works", {"search": "x"})
        self.assertIn("error", r)
        self.assertTrue(r.get("retries_exhausted"))

    def test_400_no_retry(self):
        from lib.openalex_client import OpenAlexClient
        client = OpenAlexClient(cache_path=":memory:", timeout=1.0)
        attempts = {"n": 0}

        def _se(*a, **k):
            attempts["n"] += 1
            raise _http_error(400, "bad")

        with mock.patch("urllib.request.urlopen", side_effect=_se):
            r = client._request("/works", {"search": "x"})
        self.assertEqual(attempts["n"], 1)
        self.assertIn("error", r)


class RetryHelperUnitTests(TestCase):
    def setUp(self):
        self._sleep_patch = mock.patch("lib.retry.time.sleep")
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()

    def test_succeeds_first_try(self):
        from lib.retry import retry_with_backoff
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return 42

        v = retry_with_backoff(fn, max_attempts=4, base_delay=0.01)
        self.assertEqual(v, 42)
        self.assertEqual(calls["n"], 1)

    def test_retries_then_succeeds(self):
        from lib.retry import retry_with_backoff
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("transient")
            return "ok"

        v = retry_with_backoff(fn, max_attempts=4, base_delay=0.01)
        self.assertEqual(v, "ok")
        self.assertEqual(calls["n"], 3)

    def test_exhausted_raises(self):
        from lib.retry import retry_with_backoff

        def fn():
            raise TimeoutError("always")

        with self.assertRaises(TimeoutError):
            retry_with_backoff(fn, max_attempts=2, base_delay=0.01)

    def test_non_retryable_raises_immediately(self):
        from lib.retry import retry_with_backoff
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            retry_with_backoff(
                fn, max_attempts=4, base_delay=0.01,
                retryable=(TimeoutError,),
            )
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        S2RetryTransientTests,
        OpenAlexRetryTransientTests,
        RetryHelperUnitTests,
    ))
