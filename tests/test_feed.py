"""Tests for the discovery feed."""

import json
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
import library  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


def reply(data):
    return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


COMMONS = {"query": {"pages": {"1": {"title": "File:Poster.jpg", "imageinfo": [{
    "url": "https://upload.example/poster.jpg", "thumburl": "https://upload.example/t.jpg", "width": 800, "height": 600,
    "descriptionurl": "https://commons.example/File:Poster.jpg",
    "extmetadata": {"Artist": {"value": "<a href='x'>Ada &amp; Co</a>"}}}]},
    "2": {"title": "File:Tiny.png", "imageinfo": [{"url": "https://upload.example/tiny.png", "width": 20, "height": 20}]}}}}


def fake_fetcher(url):
    if "commons.wikimedia.org" in url:
        return reply(COMMONS)
    if "collectionapi" in url and "/search" in url:
        return reply({"objectIDs": [7]})
    if "/objects/7" in url:
        return reply({"isPublicDomain": True, "primaryImage": "https://met.example/7.jpg",
                      "primaryImageSmall": "https://met.example/7s.jpg", "title": "Vase",
                      "artistDisplayName": "Anon", "objectURL": "https://met.example/obj/7"})
    if "api.are.na" in url:
        return reply({"title": "Chan", "contents": [{"title": "b", "image": {
            "original": {"url": "https://arena.example/o.jpg"}, "display": {"url": "https://arena.example/d.jpg"}}}]})
    raise AssertionError(url)


class FeedCase(LibraryCase):
    def enable(self, *ids):
        for source_id in ids:
            feed_sources.set_source(source_id, True)

    def tagged(self, tag="poster"):
        entry = self.add_entry(title="x")
        library.add_tags([entry], tag)
        return entry


class TermTests(FeedCase):
    def test_tags_first_then_set_names_without_duplicates(self):
        first = self.tagged("poster")
        library.add_tags([first], "type")
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Poster', '2026-01-01')")
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Moods', '2026-01-01')")
        self.assertEqual(feed.search_terms(self.conn), ["poster", "type", "Moods"])


class WeightTests(FeedCase):
    def test_usage_raises_weight_and_choices_move_it(self):
        first, second = self.tagged("poster"), self.add_entry(title="y")
        library.add_tags([second], "poster, rare")
        weights = feed.term_weights(self.conn)
        self.assertEqual((weights["poster"], weights["rare"]), (2, 1))
        for url, state in (("a", "saved"), ("b", "dismissed")):
            self.conn.execute(
                "INSERT INTO feed_items (source_id, url, term, state, created_at) VALUES ('met', ?, ?, ?, 'x')",
                (url, "rare" if state == "saved" else "poster", state))
        weights = feed.term_weights(self.conn)
        self.assertEqual((weights["poster"], weights["rare"]), (1, 4))

    def test_pick_terms_returns_distinct_words(self):
        self.tagged("poster")
        library.add_tags([self.add_entry(title="z")], "type")
        picked = feed.pick_terms(self.conn, random.Random(3), 5)
        self.assertEqual(sorted(picked), ["poster", "type"])


class RefreshTests(FeedCase):
    def refresh(self):
        return feed.refresh(self.conn, fake_fetcher, random.Random(1))

    def test_nothing_enabled_pulls_nothing(self):
        self.tagged()
        self.assertEqual(self.refresh()["added"], 0)

    def test_commons_and_met_items_are_stored_with_credit(self):
        self.tagged()
        self.enable("commons", "met")
        self.assertEqual(self.refresh()["added"], 2)
        items = {item["source_id"]: item for item in feed.list_items(self.conn)["items"]}
        self.assertEqual(items["commons"]["creator"], "Ada & Co")
        self.assertEqual(items["commons"]["title"], "Poster")
        self.assertEqual(items["met"]["page_url"], "https://met.example/obj/7")

    def test_arena_uses_channels_from_saved_entries(self):
        entry = self.tagged()
        self.conn.execute("UPDATE entries SET source_url = 'https://www.are.na/me/chan' WHERE id = ?", (entry,))
        self.enable("arena")
        self.assertEqual(self.refresh()["added"], 1)
        self.assertEqual(feed.list_items(self.conn)["items"][0]["thumb"], "https://arena.example/d.jpg")

    def test_repeat_refresh_and_saved_images_are_not_added_twice(self):
        self.tagged()
        self.enable("commons")
        self.refresh()
        self.assertEqual(self.refresh()["added"], 0)
        self.conn.execute("DELETE FROM feed_items")
        capture.add_link(self.conn, "https://upload.example/poster.jpg")
        self.assertEqual(self.refresh()["added"], 0)

    def test_failing_source_is_counted_and_skipped(self):
        self.tagged()
        self.enable("commons")

        def broken(url):
            raise OSError("down")

        result = feed.refresh(self.conn, broken, random.Random(1))
        self.assertEqual((result["added"], result["failed"]), (0, 1))


class ReviewTests(FeedCase):
    def seed(self):
        self.tagged()
        self.enable("commons", "met")
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
        self.assertEqual((result["added"], result["placed"]), (2, 2))
        sources = {row[0] for row in self.conn.execute("SELECT source_url FROM entries WHERE source_url != ''")}
        self.assertIn("https://met.example/obj/7", sources)
        self.assertEqual(feed.list_items(self.conn)["total"], 0)


if __name__ == "__main__":
    unittest.main()
