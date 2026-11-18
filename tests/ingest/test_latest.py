"""Tests for Latest: the newest posts of the dated followed sources."""

import json
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import arena  # noqa: E402
from bridge.ingest import feed  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402


def reply(data):
    return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


def item(url, posted_at=""):
    return {"source_id": "rss", "url": url, "thumb": url, "width": 0, "height": 0, "title": "", "creator": "",
            "page_url": "", "term": "", "posted_at": posted_at}


class LatestCase(LibraryCase):
    def follow(self, url, kind="rss"):
        self.conn.execute("INSERT INTO followed_sources (kind, url, created_at) VALUES (?, ?, '2026-01-01')", (kind, url))

    def refresh(self, pulled=None, batch=feed.LATEST_BATCH):
        calls = []

        def fake_pull(url, fetcher, rng, kind="", newest=False):
            calls.append((url, newest))
            return (pulled or {}).get(url, [])

        with mock.patch.object(feed, "pull", fake_pull), mock.patch.object(feed.labels, "check_new", lambda *args: 0):
            result = feed.refresh_latest(self.conn, object(), random.Random(1), batch=batch)
        return result, calls


class RefreshLatestTests(LatestCase):
    def test_pinterest_boards_are_not_checked(self):
        self.follow("https://site.example/feed")
        self.follow("https://www.pinterest.com/me/board/", "pinterest")
        result, calls = self.refresh()
        self.assertEqual(calls, [("https://site.example/feed", True)])
        self.assertEqual((result["jobs"], result["enabled"]), (1, ["latest"]))

    def test_each_batch_takes_the_sources_checked_longest_ago(self):
        for name in ("a", "b", "c"):
            self.follow(f"https://{name}.example/feed")
        _, first = self.refresh(batch=2)
        _, second = self.refresh(batch=2)
        self.assertEqual([url for url, _ in first], ["https://a.example/feed", "https://b.example/feed"])
        self.assertEqual(second[0][0], "https://c.example/feed")

    def test_new_posts_are_stored(self):
        self.follow("https://site.example/feed")
        result, _ = self.refresh({"https://site.example/feed": [item("https://site.example/a.jpg", "2026-11-01")]})
        self.assertEqual(result["added"], 1)

    def test_nothing_followed_reports_no_sources(self):
        result, _ = self.refresh()
        self.assertEqual((result["jobs"], result["enabled"]), (0, []))


class ListLatestTests(LatestCase):
    def insert(self, url, posted_at, created_at, source_id="rss"):
        self.conn.execute("INSERT INTO feed_items (source_id, url, thumb, width, height, title, creator, page_url, term,"
                          " created_at, posted_at) VALUES (?, ?, ?, 0, 0, '', '', '', '', ?, ?)",
                          (source_id, url, url, created_at, posted_at))

    def test_items_are_newest_posted_first_without_pinterest(self):
        self.insert("https://a.example/1.jpg", "2026-10-01", "2026-11-01T00:00:00")
        self.insert("https://a.example/2.jpg", "2026-11-10", "2026-11-11T00:00:00")
        self.insert("https://p.example/3.jpg", "2026-11-12", "2026-11-12T00:00:00", "pinterest")
        urls = [row["url"] for row in feed.list_latest(self.conn)["items"]]
        self.assertEqual(urls, ["https://a.example/2.jpg", "https://a.example/1.jpg"])

    def test_only_recent_posts_arriving_after_the_visit_are_fresh(self):
        today = date.today()
        arrived = today.isoformat() + "T12:00:00"
        self.insert("https://a.example/new.jpg", (today - timedelta(days=2)).isoformat(), arrived)
        self.insert("https://a.example/archive.jpg", (today - timedelta(days=400)).isoformat(), arrived)
        self.insert("https://a.example/seen.jpg", today.isoformat(), "2000-01-01T00:00:00")
        fresh = {row["url"]: row["fresh"] for row in feed.list_latest(self.conn, since="2001-01-01T00:00:00")["items"]}
        self.assertEqual(fresh, {"https://a.example/new.jpg": True, "https://a.example/archive.jpg": False,
                                 "https://a.example/seen.jpg": False})
        self.conn.execute("INSERT INTO feed_marks (name, value) VALUES ('latest_seen', '2001-01-01T00:00:00')")
        self.assertEqual(feed.latest_status(self.conn), {"fresh": 1})

    def test_marking_a_visit_returns_the_previous_one(self):
        self.assertEqual(feed.mark_latest_seen(self.conn), "")
        first = feed.latest_seen(self.conn)
        self.assertTrue(first)
        self.assertEqual(feed.mark_latest_seen(self.conn), first)

    def test_never_checked_sources_are_stale(self):
        self.follow("https://site.example/feed")
        self.assertTrue(feed.list_latest(self.conn)["stale"])
        self.refresh()
        self.assertFalse(feed.list_latest(self.conn)["stale"])


class ArenaNewestTests(unittest.TestCase):
    def test_a_channel_reads_its_first_and_last_pages_newest_first(self):
        def fetcher(url):
            if "/contents" in url:
                page = "1" if "page=1" in url else "2"
                return reply({"data": [{"title": page, "connected_at": f"2026-0{page}-01T00:00:00Z",
                                        "image": {"src": f"https://arena.example/{page}.jpg"}}]})
            return reply({"title": "Chan", "counts": {"contents": arena.PAGE_SIZE + 1}})

        found = arena.channel_items("https://www.are.na/me/chan", fetcher, random.Random(1), newest=True)
        self.assertEqual([entry["url"] for entry in found], ["https://arena.example/2.jpg", "https://arena.example/1.jpg"])


if __name__ == "__main__":
    unittest.main()
