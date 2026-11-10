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

    def test_switching_a_source_on_and_off(self):
        self.assertTrue(feed_sources.set_source("arena", True)["enabled"])
        self.assertEqual(feed_sources.enabled_sources(), ["arena"])
        self.assertFalse(feed_sources.set_source("arena", False)["enabled"])

    def test_sources_that_forbid_automation_cannot_be_switched_on(self):
        for source_id in ("cosmos", "savee", "pinterest", "missing"):
            self.assertIsNone(feed_sources.set_source(source_id, True))
        self.assertFalse(self.source("cosmos")["enabled"])

    def test_key_sources_need_a_key_before_they_count_as_enabled(self):
        feed_sources.set_source("unsplash", True)
        self.assertTrue(self.source("unsplash")["enabled"])
        self.assertFalse(self.source("unsplash")["has_key"])
        self.assertEqual(feed_sources.enabled_sources(), [])
        feed_sources.set_source("unsplash", True, " abc123 ")
        self.assertEqual(feed_sources.enabled_sources(), ["unsplash"])

    def test_the_key_is_never_returned_and_survives_a_switch(self):
        feed_sources.set_source("pexels", True, "secret")
        self.assertNotIn("secret", str(feed_sources.list_sources()))
        feed_sources.set_source("pexels", False)
        feed_sources.set_source("pexels", True)
        self.assertTrue(self.source("pexels")["has_key"])


if __name__ == "__main__":
    unittest.main()
