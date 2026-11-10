"""Tests for the discovery-feed source catalog and its opt-in switches."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feed_sources  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


class FeedSourceTests(LibraryCase):
    def source(self, source_id):
        return next(item for item in feed_sources.list_sources() if item["id"] == source_id)

    def test_every_source_starts_off(self):
        self.assertFalse(any(item["enabled"] for item in feed_sources.list_sources()))
        self.assertEqual(feed_sources.enabled_sources(), [])

    def test_only_are_na_and_tumblr_are_pullable(self):
        self.assertEqual([item["id"] for item in feed_sources.list_sources() if item["available"]], ["arena", "tumblr"])

    def test_switching_a_source_on_and_off(self):
        self.assertTrue(feed_sources.set_source("arena", True)["enabled"])
        self.assertEqual(feed_sources.enabled_sources(), ["arena"])
        self.assertFalse(feed_sources.set_source("arena", False)["enabled"])

    def test_sources_that_forbid_automation_cannot_be_switched_on(self):
        for source_id in ("cosmos", "savee", "pinterest", "missing"):
            self.assertIsNone(feed_sources.set_source(source_id, True))
        self.assertFalse(self.source("cosmos")["enabled"])


if __name__ == "__main__":
    unittest.main()
