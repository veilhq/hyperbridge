"""Tests for the discovery feed."""

import json
import os
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HYPERBRIDGE_EMBEDDINGS"] = "0"

import arena  # noqa: E402
import capture  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
import library  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


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
    def follow(self, url="https://www.are.na/me/chan"):
        arena.follow(self.conn, url, fake_fetcher)

    def refresh(self):
        return feed.refresh(self.conn, fake_fetcher, random.Random(1))

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
        self.refresh()
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

    def test_failing_channel_is_counted_and_skipped(self):
        self.follow()

        def broken(url):
            raise OSError("down")

        result = feed.refresh(self.conn, broken, random.Random(1))
        self.assertEqual((result["added"], result["failed"]), (0, 1))


class KeywordTests(FeedCase):
    def test_untagged_entries_contribute_title_and_description_words(self):
        self.add_entry(title="Brutalist concrete tower")
        self.add_entry(title="Concrete stairwell photo")
        terms = feed.search_terms(self.conn)
        self.assertEqual(terms[0], "concrete")
        self.assertIn("brutalist", terms)
        self.assertNotIn("photo", terms)
        self.assertEqual(feed.term_weights(self.conn)["concrete"], 2)


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
