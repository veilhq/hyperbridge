"""Tests for Find similar: ranking the feed against a set and weighting its sources."""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import feed  # noqa: E402
from bridge.ingest import similar  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

NOW = "2026-11-15T10:00:00"


class SimilarCase(LibraryCase):
    def make_set(self, name="Concrete"):
        return self.conn.execute("INSERT INTO sets (name, description, created_at) VALUES (?, '', ?)", (name, NOW)).lastrowid

    def member(self, set_id, title="", tags=(), collection="", creator="", source_url=""):
        entry = self.add_entry(title=title, creator=creator)
        self.conn.execute("UPDATE entries SET collection = ?, source_url = ? WHERE id = ?", (collection, source_url, entry))
        if tags:
            library.add_entry_tags(self.conn, entry, list(tags))
        self.conn.execute("INSERT INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)", (set_id, entry, NOW))
        return entry

    def feed_item(self, url, tags=(), collection="", title="", creator="", source_id="tumblr", state="new"):
        cursor = self.conn.execute(
            "INSERT INTO feed_items (source_id, url, thumb, width, height, title, creator, page_url, term, created_at,"
            " source_ref, collection, posted_at, tags, state) VALUES (?, ?, ?, 10, 10, ?, ?, '', '', ?, '', ?, '', ?, ?)",
            (source_id, url, url, title, creator, NOW, collection, json.dumps(list(tags)), state))
        return cursor.lastrowid


class WordTests(unittest.TestCase):
    def test_folds_plurals_and_drops_noise(self):
        self.assertEqual(similar.words("Brutalist Posters of the 1970s via Tumblr"), {"brutalist", "poster", "1970"})

    def test_ies_plural(self):
        self.assertEqual(similar.words("galleries"), {"gallery"})


class ProfileTests(SimilarCase):
    def test_empty_set_has_no_profile(self):
        self.assertEqual(similar.profile(self.conn, self.make_set()), {})

    def test_shares_reflect_how_many_images_carry_a_term(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete", "brutalism"])
        self.member(set_id, tags=["concrete"])
        wanted = similar.profile(self.conn, set_id)
        self.assertEqual(wanted["concrete"], 1.0)
        self.assertEqual(wanted["brutalism"], 0.5)
        self.assertEqual(wanted["tag:concrete"], 1.0)

    def test_service_tags_are_ignored(self):
        set_id = self.make_set()
        self.member(set_id, tags=["pinterest", "are.na"])
        self.assertEqual(similar.profile(self.conn, set_id), {})

    def test_filename_titles_are_ignored(self):
        set_id = self.make_set()
        self.member(set_id, title="IMG_20240101_1234.jpg")
        self.assertEqual(similar.profile(self.conn, set_id), {})


class RankTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.set_id = self.make_set()
        self.member(self.set_id, tags=["concrete", "brutalism"], collection="Brutal Buildings")
        self.member(self.set_id, tags=["concrete"])

    def test_only_matching_unseen_items_are_ranked_best_first(self):
        weak = self.feed_item("https://x/weak.jpg", tags=["concrete", "cat", "dog", "food", "sunset", "beach"])
        strong = self.feed_item("https://x/strong.jpg", tags=["concrete", "brutalism"])
        self.feed_item("https://x/off.jpg", tags=["kittens"])
        self.feed_item("https://x/gone.jpg", tags=["concrete"], state="dismissed")
        result = similar.list_items(self.conn, self.set_id)
        self.assertEqual([item["id"] for item in result["items"]], [strong, weak])
        self.assertEqual(result["total"], 2)
        self.assertIn("concrete", result["items"][0]["matched"])

    def test_untagged_items_match_on_their_collection(self):
        board = self.feed_item("https://x/pin.jpg", collection="Brutal Buildings", source_id="pinterest")
        result = similar.list_items(self.conn, self.set_id)
        self.assertEqual([item["id"] for item in result["items"]], [board])

    def test_leading_terms_are_reported(self):
        terms = similar.list_items(self.conn, self.set_id)["terms"]
        self.assertEqual(terms[0], "concrete")

    def test_paging(self):
        for index in range(5):
            self.feed_item(f"https://x/{index}.jpg", tags=["concrete"])
        page = similar.list_items(self.conn, self.set_id, offset=3, limit=10)
        self.assertEqual((len(page["items"]), page["total"]), (2, 5))


class SourceWeightTests(SimilarCase):
    def test_named_and_origin_sources_outweigh_others(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete"], source_url="https://www.are.na/someone/raw-forms")
        followed = [
            {"url": "https://www.are.na/someone/raw-forms", "label": "Raw Forms"},
            {"url": "https://concrete-daily.tumblr.com", "label": "concrete daily"},
            {"url": "https://www.are.na/someone/flowers", "label": "Flowers"},
        ]
        weights = similar.source_weights(self.conn, set_id, followed)
        self.assertEqual(weights["https://www.are.na/someone/flowers"], 1.0)
        self.assertGreater(weights["https://www.are.na/someone/raw-forms"], 1.0)
        self.assertGreater(weights["https://concrete-daily.tumblr.com"], 1.0)


class RefreshTests(SimilarCase):
    def test_pulls_and_stores_through_the_feed(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete"])
        self.conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES ('channel', 'https://www.are.na/me/chan', 'Chan', ?)", (NOW,))
        item = {"source_id": "arena", "url": "https://arena.example/o.jpg", "thumb": "", "width": 1, "height": 1,
                "title": "", "creator": "", "page_url": "", "term": "", "tags": ["concrete"]}
        original = feed.pull
        feed.pull = lambda url, fetcher, rng: [item]
        self.addCleanup(setattr, feed, "pull", original)
        result = similar.refresh(self.conn, set_id, fetcher=lambda url: None, rng=random.Random(1))
        self.assertEqual((result["added"], result["jobs"]), (1, 1))
        self.assertEqual(similar.list_items(self.conn, set_id)["total"], 1)


if __name__ == "__main__":
    unittest.main()
