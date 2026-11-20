"""Tests for the shared request pacer: per-host gaps, cooldowns after pushback, and challenge pages."""

import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import pacer  # noqa: E402
from bridge.core.fetchguard import FetchError  # noqa: E402


class FakeClock:
    """A clock that only moves when the pacer sleeps or a test advances it."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def ok(content_type="application/json", body=b"{}"):
    return SimpleNamespace(body=body, final_url="", status=200, content_type=content_type)


class PacerCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.calls = []
        self.replies = {}

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        reply = self.replies.get(url)
        if isinstance(reply, Exception):
            raise reply
        return reply or ok()

    def make(self):
        return pacer.Pacer(self.fetch, clock=self.clock, sleep=self.clock.sleep, wall=lambda: 0.0)


class GapTests(PacerCase):
    def test_hosts_get_their_own_gap(self):
        self.assertEqual(pacer.gap_for("https://api.are.na/v3/blocks/1"), pacer.API_GAP)
        self.assertEqual(pacer.gap_for("https://blog.tumblr.com/api/read/json?id=1"), pacer.API_GAP)
        self.assertEqual(pacer.gap_for("https://blog.tumblr.com/post/1"), pacer.SITE_GAP)
        self.assertEqual(pacer.gap_for("https://64.media.tumblr.com/a.jpg"), pacer.IMAGE_GAP)
        self.assertEqual(pacer.gap_for("https://i.pinimg.com/originals/a.jpg"), pacer.IMAGE_GAP)
        self.assertEqual(pacer.gap_for("https://example.com/page"), pacer.SITE_GAP)

    def test_back_to_back_requests_to_one_host_are_spaced(self):
        paced = self.make()
        for number in range(3):
            paced(f"https://api.are.na/v3/blocks/{number}")
        self.assertEqual(self.clock.slept, [pacer.API_GAP, pacer.API_GAP])

    def test_different_hosts_do_not_wait_on_each_other(self):
        paced = self.make()
        paced("https://api.are.na/v3/blocks/1")
        paced("https://example.com/")
        self.assertEqual(self.clock.slept, [])

    def test_threads_aimed_at_one_host_take_turns(self):
        active, peak, guard = [0], [0], threading.Lock()

        def slow(url, **kwargs):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with guard:
                active[0] -= 1
            return ok()

        paced = pacer.Pacer(slow, sleep=lambda seconds: None)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(paced, [f"https://api.are.na/v3/blocks/{number}" for number in range(6)]))
        self.assertEqual(peak[0], 1)

    def test_keyword_arguments_reach_the_fetcher(self):
        self.make()("https://example.com/a.png", max_bytes=10, partial=True, headers={"Range": "bytes=0-9"})
        self.assertEqual(self.calls[0][1], {"max_bytes": 10, "partial": True, "headers": {"Range": "bytes=0-9"}})


class CooldownTests(PacerCase):
    def test_a_rate_limit_cools_the_host_without_retrying(self):
        paced = self.make()
        self.replies["https://api.are.na/a"] = FetchError("http_status", "HTTP 429", 429)
        with self.assertRaises(FetchError):
            paced("https://api.are.na/a")
        with self.assertRaises(pacer.HostCooling):
            paced("https://api.are.na/b")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(paced.is_cooling("api.are.na"))
        paced("https://example.com/")
        self.clock.now += pacer.COOLDOWN + 1
        paced("https://api.are.na/b")
        self.assertEqual(len(self.calls), 3)

    def test_retry_after_longer_than_the_cooldown_is_honored(self):
        paced = self.make()
        self.replies["https://api.are.na/a"] = FetchError("http_status", "HTTP 429", 429, str(pacer.COOLDOWN * 2))
        with self.assertRaises(FetchError):
            paced("https://api.are.na/a")
        self.clock.now += pacer.COOLDOWN + 1
        self.assertTrue(paced.is_cooling("https://api.are.na/b"))

    def test_other_failures_do_not_cool_the_host(self):
        paced = self.make()
        self.replies["https://example.com/gone"] = FetchError("http_status", "HTTP 404", 404)
        with self.assertRaises(FetchError):
            paced("https://example.com/gone")
        paced("https://example.com/next")
        self.assertFalse(paced.is_cooling("example.com"))

    def test_a_challenge_page_counts_as_pushback(self):
        paced = self.make()
        self.replies["https://example.com/"] = ok("text/html", b"<title>Just a moment...</title><div id=cf-chl-widget>")
        with self.assertRaises(FetchError) as caught:
            paced("https://example.com/")
        self.assertEqual(caught.exception.status, 403)
        self.assertTrue(paced.is_cooling("example.com"))

    def test_retry_after_reads_seconds_and_dates(self):
        self.assertEqual(pacer._retry_after("120", 0.0), 120.0)
        self.assertEqual(pacer._retry_after("Thu, 01 Jan 1970 00:10:00 GMT", 0.0), 600.0)
        self.assertEqual(pacer._retry_after("soon", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
