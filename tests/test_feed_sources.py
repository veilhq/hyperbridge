"""Tests for the catalog of outside services."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feed_sources  # noqa: E402


class FeedSourceTests(unittest.TestCase):
    def test_only_are_na_and_tumblr_are_pullable(self):
        self.assertEqual([item["id"] for item in feed_sources.list_sources() if item["available"]], ["arena", "tumblr"])

    def test_services_that_forbid_automation_are_listed_as_unavailable(self):
        blocked = {item["id"] for item in feed_sources.list_sources() if not item["available"]}
        self.assertEqual(blocked, {"cosmos", "savee", "pinterest"})


if __name__ == "__main__":
    unittest.main()
