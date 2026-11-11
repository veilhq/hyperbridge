"""Tests for the discovery feed."""

import json
import os
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import arena  # noqa: E402
from bridge.ingest import capture  # noqa: E402
from bridge.ingest import feed  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402


def reply(data):
    return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


def fake_fetcher(url):
    if "/contents" in url:
        return reply({"data": [{"title": "b", "image": {"src": "https://arena.example/o.jpg",
                                                       "large": {"src": "https://arena.example/d.jpg"}}}]})
    if "api.are.na" in url:
        return reply({"title": "Chan", "counts": {"contents": 1}})
    raise AssertionError(url)


class FeedCase(LibraryCase):
    def tagged(self, tag="poster"):
        entry = self.add_entry(title="x")
        library.add_tags([entry], tag)
        return entry


class RefreshTests(FeedCase):
    def follow(self, url="https://www.are.na/me/chan"):
        arena.follow(self.conn, url, fake_fetcher)

    def refresh(self, replace=False):
        return feed.refresh(self.conn, fake_fetcher, random.Random(1), replace=replace)

    def test_nothing_followed_pulls_nothing(self):
        self.tagged()
        result = self.refresh()
        self.assertEqual((result["added"], result["jobs"], result["enabled"]), (0, 0, []))

    def test_followed_channels_are_stored(self):
        self.tagged()
        self.follow()
        result = self.refresh()
        self.assertEqual((result["added"], result["enabled"]), (1, ["arena"]))
        self.assertEqual(feed.list_items(self.conn)["items"][0]["thumb"], "https://arena.example/d.jpg")

    def test_channels_only_in_saved_entries_are_not_pulled(self):
        entry = self.tagged()
        self.conn.execute("UPDATE entries SET source_url = 'https://www.are.na/me/saved' WHERE id = ?", (entry,))
        self.assertEqual(self.refresh()["jobs"], 0)

    def test_refresh_replaces_unseen_items_from_other_sources_and_old_pulls(self):
        self.follow()
        self.conn.execute("INSERT INTO feed_items (source_id, url, thumb, width, height, title, creator, page_url, term, created_at)"
                          " VALUES ('met', 'https://old.example/a.jpg', 'x', 1, 1, '', '', '', '', 'now')")
        self.refresh(replace=True)
        self.assertEqual([item["source_id"] for item in feed.list_items(self.conn)["items"]], ["arena"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0], 1)

    def test_repeat_refresh_and_saved_images_are_not_added_twice(self):
        self.follow()
        self.refresh()
        self.refresh()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0], 1)
        self.conn.execute("DELETE FROM feed_items")
        capture.add_link(self.conn, "https://arena.example/o.jpg")
        self.assertEqual(self.refresh()["added"], 0)

    def test_appending_refresh_keeps_shown_items_and_retries_past_repeats(self):
        self.follow()
        calls = []

        def drifting(url):
            if "/contents" not in url:
                return fake_fetcher(url)
            calls.append(url)
            name = "a" if len(calls) <= 2 else "b"
            return reply({"data": [{"title": name, "image": {"src": f"https://arena.example/{name}.jpg",
                                                           "large": {"src": f"https://arena.example/{name}.jpg"}}}]})

        feed.refresh(self.conn, drifting, random.Random(1))
        result = feed.refresh(self.conn, drifting, random.Random(1))
        self.assertEqual(result["added"], 1)
        self.assertEqual(sorted(item["thumb"][-5:] for item in feed.list_items(self.conn)["items"]), ["a.jpg", "b.jpg"])

    def test_old_dismissed_and_unseen_items_are_pruned(self):
        for state, created in (("dismissed", "2020-01-01T00:00:00"), ("new", "2020-01-01T00:00:00"),
                               ("dismissed", feed._now()), ("saved", "2020-01-01T00:00:00")):
            self.conn.execute(
                "INSERT INTO feed_items (source_id, url, term, state, created_at) VALUES ('arena', ?, '', ?, ?)",
                (f"https://x.example/{state}{created}", state, created))
        self.assertEqual(feed.prune(self.conn), 2)
        self.assertEqual(sorted(row[0] for row in self.conn.execute("SELECT state FROM feed_items")), ["dismissed", "saved"])

    def test_failing_channel_is_counted_and_skipped(self):
        self.follow()

        def broken(url):
            raise OSError("down")

        result = feed.refresh(self.conn, broken, random.Random(1))
        self.assertEqual((result["added"], result["failed"]), (0, 1))


class ReviewTests(FeedCase):
    def seed(self):
        self.tagged()
        arena.follow(self.conn, "https://www.are.na/me/chan", fake_fetcher)
        feed.refresh(self.conn, fake_fetcher, random.Random(1))
        return [item["id"] for item in feed.list_items(self.conn)["items"]]

    def test_stale_until_something_is_pulled(self):
        self.assertTrue(feed.list_items(self.conn)["stale"])
        self.seed()
        self.assertFalse(feed.list_items(self.conn)["stale"])

    def test_dismissed_items_leave_the_list_and_do_not_return(self):
        ids = self.seed()
        self.assertEqual(feed.dismiss(self.conn, ids[:1]), 1)
        self.assertEqual(feed.list_items(self.conn)["total"], len(ids) - 1)
        feed.refresh(self.conn, fake_fetcher, random.Random(1))
        self.assertEqual(feed.list_items(self.conn)["total"], len(ids) - 1)

    def test_accept_creates_entries_credited_to_the_page_and_places_them(self):
        ids = self.seed()
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Mine', '2026-01-01')")
        result = feed.accept(self.conn, ids, 1)
        self.assertEqual((result["added"], result["placed"]), (1, 1))
        sources = {row[0] for row in self.conn.execute("SELECT source_url FROM entries WHERE source_url != ''")}
        self.assertIn("https://www.are.na/me/chan", sources)
        self.assertEqual(feed.list_items(self.conn)["total"], 0)


if __name__ == "__main__":
    unittest.main()
