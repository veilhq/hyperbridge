"""Tests for library indexing and similarity ranking of feed candidates."""

import os
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HYPERBRIDGE_EMBEDDINGS"] = "0"

import db  # noqa: E402
import embed  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402

AXES = {b"red": [1.0, 0.0, 0.0], b"warm": [0.9, 0.436, 0.0], b"blue": [0.0, 0.0, 1.0], b"copy": [1.0, 0.0, 0.0]}


def fake_embedder(bodies):
    """Turn each body into a fixed unit vector chosen by its text; unknown bodies cannot be read."""
    vectors = []
    for body in bodies:
        vector = AXES.get(body.rsplit(b"/", 1)[-1])
        vectors.append(None if vector is None else (np.asarray(vector) / np.linalg.norm(vector)).astype("float32"))
    return vectors


class EmbedCase(LibraryCase):
    def store_vector(self, entry, body):
        vector = fake_embedder([body])[0]
        self.conn.execute(
            "INSERT INTO entry_vectors (entry_id, model, dim, vector, created_at) VALUES (?, ?, ?, ?, 'now')",
            (entry, embed.MODEL, len(vector), vector.tobytes()))

    def seed_library(self):
        for name in range(3):
            self.store_vector(self.add_entry(title=f"red {name}"), b"red")


class IndexTests(EmbedCase):
    def test_pending_entries_are_embedded_once(self):
        entry = self.add_entry(title="x")
        path = Path(db.data_dir()) / "assets" / "one.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"red")
        self.conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path) VALUES (?, 0, 'original', 'assets/one.bin')", (entry,))
        self.assertEqual(embed.index_library(self.conn, fake_embedder), 1)
        self.assertEqual(embed.index_library(self.conn, fake_embedder), 0)
        self.assertEqual(embed.library_matrix(self.conn).shape, (1, 3))


class RankTests(EmbedCase):
    def rank(self, items):
        bodies = {item["url"]: item["url"].encode() for item in items}
        return embed.rank(self.conn, items, lambda url: bodies.get(url, b"").replace(b"thumb:", b""), fake_embedder)

    def item(self, name):
        return {"source_id": "arena", "url": name, "thumb": name}

    def test_candidates_closer_to_the_library_come_first(self):
        self.seed_library()
        ranked = self.rank([self.item("blue"), self.item("warm")])
        self.assertEqual([item["url"] for item in ranked], ["warm", "blue"])
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_near_copies_of_saved_images_and_unreadable_ones_are_dropped(self):
        self.seed_library()
        ranked = self.rank([self.item("copy"), self.item("missing"), self.item("warm")])
        self.assertEqual([item["url"] for item in ranked], ["warm"])

    def test_candidates_far_below_the_librarys_own_closeness_are_dropped(self):
        extra = {b"orange": [0.8, 0.6, 0.0], b"mid1": [0.95, 0.3, 0.0], b"mid2": [0.9, 0.3, 0.1], b"mid3": [0.92, 0.35, 0.0],
                 b"far1": [0.0, 0.1, 1.0], b"far2": [0.0, 0.2, 1.0], b"far3": [0.1, 0.0, 1.0], b"far4": [0.0, 0.3, 1.0]}
        AXES.update(extra)
        self.addCleanup(lambda: [AXES.pop(key, None) for key in extra])
        for body in (b"red", b"red", b"red", b"orange", b"orange", b"orange"):
            self.store_vector(self.add_entry(title="x"), body)
        urls = [item["url"] for item in self.rank([self.item(name.decode()) for name in extra if name != b"orange"])]
        self.assertEqual(sorted(urls), ["mid1", "mid2", "mid3"])

    def test_small_library_leaves_items_untouched(self):
        self.store_vector(self.add_entry(title="x"), b"red")
        items = [self.item("blue")]
        self.assertIs(self.rank(items), items)


class FeedRankingTests(EmbedCase):
    def test_refresh_stores_scores_best_first(self):
        self.seed_library()
        feed_sources.set_source("commons", True)
        self.add_entry(title="poster design")
        blue, warm = "https://img.example/blue", "https://img.example/warm"
        pages = {"1": {"title": "File:A.jpg", "imageinfo": [{"url": blue, "thumburl": blue, "width": 800, "height": 800,
                                                              "descriptionurl": "https://c.example/a"}]},
                 "2": {"title": "File:B.jpg", "imageinfo": [{"url": warm, "thumburl": warm, "width": 800, "height": 800,
                                                              "descriptionurl": "https://c.example/b"}]}}

        def fetcher(url):
            if "commons.wikimedia.org" in url:
                import json
                return SimpleNamespace(body=json.dumps({"query": {"pages": pages}}).encode(), final_url="", status=200,
                                       content_type="application/json")
            return SimpleNamespace(body=url.encode(), final_url="", status=200, content_type="image/jpeg")

        result = feed.refresh(self.conn, fetcher, random.Random(1), fake_embedder)
        self.assertTrue(result["ranked"])
        items = feed.list_items(self.conn)["items"]
        self.assertEqual([item["url"] for item in items], [warm, blue])


if __name__ == "__main__":
    unittest.main()
