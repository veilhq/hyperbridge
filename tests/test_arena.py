"""Tests for Are.na sampling and followed sources."""

import json
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arena  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


def block(number):
    return {"id": number, "title": f"b{number}", "image": {
        "original": {"url": f"https://arena.example/{number}.jpg"}, "display": {"url": f"https://arena.example/d{number}.jpg"}}}


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
        elif "/users/" in url and url.endswith("/channels?per=100"):
            data = {"channels": [channel("first", "ada"), channel("empty", "ada", length=0)]}
        elif "/users/" in url:
            data = {"username": "ada"}
        elif "page=2" in url:
            data = {"title": "Big", "length": 150, "contents": [block(n) for n in range(200, 210)]}
        else:
            length = 150 if "/big?" in url else 3
            data = {"title": "Big" if length == 150 else "Chan", "length": length, "contents": [block(n) for n in (1, 2, 3)]}
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

    def test_user_items_come_from_a_non_empty_channel(self):
        items = arena.user_items("https://www.are.na/ada", FakeArena(), random.Random(1))
        self.assertTrue(items)
        self.assertEqual(items[0]["page_url"], "https://www.are.na/ada/first")

    def test_related_items_come_from_a_public_sibling_channel(self):
        items = arena.related_items("https://www.are.na/me/home", FakeArena(), random.Random(1))
        self.assertTrue(items)
        self.assertEqual(items[0]["page_url"], "https://www.are.na/other/sibling")


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
