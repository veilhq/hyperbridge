"""Tests for Are.na sampling and followed sources."""

import json
import os
import random
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HYPERBRIDGE_EMBEDDINGS"] = "0"

import arena  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


def block(number):
    return {"id": number, "title": f"b{number}", "image": {
        "src": f"https://arena.example/{number}.jpg", "large": {"src": f"https://arena.example/d{number}.jpg"}}}


def channel(slug, owner="me", length=3, status="public"):
    return {"slug": slug, "title": slug.title(), "length": length, "status": status, "user": {"slug": owner}}


class FakeArena:
    """Serves canned Are.na API responses and records the requests made."""

    def __init__(self):
        self.requests = []

    def __call__(self, url):
        self.requests.append(url)
        if "/blocks/" in url:
            data = {"channels": [channel("home"), channel("sibling", "other"), channel("private-one", "x", status="private")]}
        elif "/v3/users/" in url:
            data = {"meta": {"total_pages": 1}, "data": [
                {"id": 9, "type": "Image", "title": "Mine", "image": {"src": "https://arena.example/u9.jpg", "large": {"src": "https://arena.example/u9l.jpg"}}},
                {"id": 10, "type": "Link", "title": "No image"}]}
        elif "/users/" in url:
            data = {"username": "ada"}
        elif "/v3/channels/" in url and "/contents" in url:
            data = {"data": [block(n) for n in (range(200, 210) if "page=2" in url else (1, 2, 3))]}
        else:
            big = url.endswith("/big")
            data = {"title": "Big" if big else "Chan", "counts": {"contents": 150 if big else 3}}
        return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


class TargetTests(unittest.TestCase):
    def test_channels_users_and_other_links(self):
        self.assertEqual(arena.target("https://www.are.na/me/chan"), ("channel", "chan"))
        self.assertEqual(arena.target("https://are.na/ada"), ("user", "ada"))
        self.assertIsNone(arena.target("https://www.are.na/explore"))
        self.assertIsNone(arena.target("https://www.are.na/block/12"))
        self.assertIsNone(arena.target("https://example.com/me/chan"))


class SamplingTests(unittest.TestCase):
    def test_large_channels_are_read_beyond_the_first_page(self):
        fetcher = FakeArena()
        urls = set()
        for seed in range(12):
            urls |= {item["url"] for item in arena.channel_items("https://www.are.na/me/big", fetcher, random.Random(seed))}
        self.assertTrue(any("/2" in url and "arena.example/2" in url for url in urls))

    def test_user_items_are_the_images_the_user_saved(self):
        items = arena.user_items("https://www.are.na/ada", FakeArena(), random.Random(1))
        self.assertEqual([(item["url"], item["thumb"]) for item in items], [("https://arena.example/u9.jpg", "https://arena.example/u9l.jpg")])
        self.assertEqual(items[0]["page_url"], "https://www.are.na/block/9")

    def test_related_items_come_from_a_public_sibling_channel(self):
        items = arena.related_items("https://www.are.na/me/home", FakeArena(), random.Random(1))
        self.assertTrue(items)
        self.assertEqual(items[0]["page_url"], "https://www.are.na/other/sibling")


class RetryTests(unittest.TestCase):
    def test_a_rate_limited_read_is_retried_then_succeeds(self):
        calls = []

        def flaky(url):
            calls.append(url)
            if len(calls) < 3:
                raise OSError("HTTP 429")
            return SimpleNamespace(body=b'{"ok": 1}')

        with unittest.mock.patch.object(arena.time, "sleep") as sleep:
            self.assertEqual(arena._json(flaky, "u", retries=3), {"ok": 1})
        self.assertEqual((len(calls), sleep.call_count), (3, 2))
        with self.assertRaises(OSError):
            arena._json(lambda url: (_ for _ in ()).throw(OSError("HTTP 500")), "u", retries=3)


class OriginFake(FakeArena):
    """A channel whose block 1 has real metadata and a co-occurrence graph around it."""

    def __call__(self, url):
        self.requests.append(url)
        if "/blocks/1/channels" in url:
            data = {"channels": [channel("home", "me"), channel("shared", "ann", length=9), channel("lone", "bob", length=9)]}
        elif "/blocks/2/channels" in url:
            data = {"channels": [channel("shared", "ann", length=9)]}
        elif "/v3/blocks/77" in url:
            data = {"id": 77, "title": "Poster Wall", "description": {"plain": "grid study"},
                    "source": {"provider": {"name": "site.example"}}}
        elif "/v3/channels/home/contents" in url:
            blocks = [block(1), block(2)]
            blocks[0].update(title="Glass Tower", description={"plain": "curtain wall"}, user={"username": "Ada"},
                             source={"provider": {"name": "https://site.example"}})
            data = {"data": blocks}
        elif "/v3/channels/home" in url:
            data = {"title": "❊ Alkaline Graphics", "counts": {"contents": 2},
                    "description": {"plain": "datacore and nostalgia"}}
        else:
            return super().__call__(url)
        return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


class OriginTests(LibraryCase):
    def saved(self, number, title):
        entry = self.add_entry(title=title)
        self.conn.execute("UPDATE entries SET source_url = ?, source_key = ? WHERE id = ?",
                          ("https://www.are.na/me/home", f"https://arena.example/{number}.jpg", entry))
        return entry

    def test_junk_titles_are_recognized(self):
        for title in ("original_ec6b292b2a779f6a73de4c15c3004904.jpg", "IMG_2034.jpg", "f666d7ed-71d7-4aaa-a6c3-24f36e89ea3c.jpg", ""):
            self.assertTrue(arena.junk_title(title), title)
        self.assertFalse(arena.junk_title("Glass Tower"))

    def test_backfill_records_the_block_and_fills_empty_fields(self):
        first = self.saved(1, "original_ec6b292b2a779f6a73de4c15c3004904.jpg")
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1)), 1)
        entry = self.conn.execute("SELECT title, creator, description, publisher FROM entries WHERE id = ?", (first,)).fetchone()
        self.assertEqual(tuple(entry), ("Glass Tower", "", "curtain wall", "site.example"))
        origin = self.conn.execute("SELECT block_id, channel_title, channel_text FROM entry_origins").fetchone()
        self.assertEqual(tuple(origin), (1, "Alkaline Graphics", "datacore and nostalgia"))
        source = self.conn.execute("SELECT source_service, source_ref, collection FROM entries WHERE id = ?", (first,)).fetchone()
        self.assertEqual(tuple(source), ("arena", "1", "Alkaline Graphics"))
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1)), 0)

    def test_saved_urls_with_a_different_query_still_match_and_unmatched_rows_retry(self):
        entry = self.saved(1, "original_ec6b292b2a779f6a73de4c15c3004904.jpg")
        self.conn.execute("UPDATE entries SET source_key = ? WHERE id = ?", ("https://arena.example/1.jpg?15%3Fbc=0", entry))
        self.conn.execute("INSERT INTO entry_origins (entry_id, block_id, channel_slug, channel_title, channel_text, checked_at)"
                          " VALUES (?, NULL, 'home', '', '', 'then')", (entry,))
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1)), 1)
        self.assertEqual(self.conn.execute("SELECT block_id FROM entry_origins").fetchone()[0], 1)

    def test_entries_saved_from_a_block_page_are_read_directly(self):
        entry = self.saved(5, "original_ec6b292b2a779f6a73de4c15c3004904.jpg")
        self.conn.execute("UPDATE entries SET source_url = 'https://www.are.na/block/77' WHERE id = ?", (entry,))
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1), max_channels=None), 1)
        row = self.conn.execute("SELECT title, description, publisher FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual(tuple(row), ("Poster Wall", "grid study", "site.example"))
        self.assertEqual(self.conn.execute("SELECT block_id FROM entry_origins").fetchone()[0], 77)

    def test_all_channels_are_read_when_no_limit_is_given(self):
        for number, slug in ((1, "home"), (2, "other"), (3, "third")):
            entry = self.saved(number, "x")
            self.conn.execute("UPDATE entries SET source_url = ? WHERE id = ?", (f"https://www.are.na/me/{slug}", entry))
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1)), 2)
        self.assertEqual(arena.backfill_origins(self.conn, OriginFake(), random.Random(1), max_channels=None), 1)

    def test_feed_terms_use_channel_words_not_filenames(self):
        self.saved(1, "original_ec6b292b2a779f6a73de4c15c3004904.jpg")
        self.saved(2, "original_bdd0d1cbffec079cf41f8f4f3145d6b8.png")
        arena.backfill_origins(self.conn, OriginFake(), random.Random(1))
        terms = feed.search_terms(self.conn)
        self.assertIn("Alkaline Graphics", terms)
        self.assertIn("alkaline", terms)
        self.assertNotIn("original", terms)
        self.assertNotIn("datacore", terms)

    def test_graph_items_pull_from_a_channel_that_shares_saved_blocks(self):
        self.saved(1, "x")
        self.saved(2, "y")
        arena.backfill_origins(self.conn, OriginFake(), random.Random(1))
        fake = OriginFake()
        items = arena.graph_items(self.conn, fake, random.Random(1), seeds=2)
        self.assertTrue(items)
        self.assertEqual(items[0]["page_url"], "https://www.are.na/ann/shared")


class FollowTests(LibraryCase):
    def test_follow_lists_dedupes_and_unfollows(self):
        item = arena.follow(self.conn, "https://www.are.na/me/chan", FakeArena())
        self.assertEqual((item["kind"], item["label"]), ("channel", "Chan"))
        arena.follow(self.conn, "https://www.are.na/me/chan", FakeArena())
        self.assertEqual(len(arena.list_followed(self.conn)), 1)
        self.assertEqual(arena.follow(self.conn, "https://are.na/ada", FakeArena())["label"], "ada")
        self.assertTrue(arena.unfollow(self.conn, item["id"]))
        self.assertFalse(arena.unfollow(self.conn, item["id"]))

    def test_other_links_and_unreadable_links_are_refused(self):
        with self.assertRaises(ValueError):
            arena.follow(self.conn, "https://example.com/x/y", FakeArena())

        def broken(url):
            raise OSError("down")

        with self.assertRaises(ValueError):
            arena.follow(self.conn, "https://www.are.na/me/chan", broken)

    def test_refresh_pulls_from_a_followed_channel_without_saved_entries(self):
        self.add_entry(title="x")
        feed_sources.set_source("arena", True)
        arena.follow(self.conn, "https://www.are.na/me/chan", FakeArena())
        result = feed.refresh(self.conn, FakeArena(), random.Random(1))
        self.assertGreater(result["added"], 0)
        self.assertEqual(feed.list_items(self.conn)["items"][0]["source_id"], "arena")


if __name__ == "__main__":
    unittest.main()
