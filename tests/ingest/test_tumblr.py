"""Tests for following and pulling from a Tumblr blog."""

import json
import os
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import feed  # noqa: E402
from bridge.library import library  # noqa: E402
from bridge.ingest import tumblr  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

BODY = ('<div class="npf_row"><figure><img src="https://m.example/a/s640.jpg" data-orig-width="1200" data-orig-height="1800" srcset="https://m.example/a/s75.jpg 75w, '
        'https://m.example/a/s2048.jpg 2000w, https://m.example/a/s400.jpg 400w"></figure></div><p>Sign &amp; type</p>')


class FakeBlog:
    def __init__(self, posts=None):
        self.requests = []
        self.posts = posts if posts is not None else [
            {"url": "https://blog.example/post/1", "regular-title": "", "regular-body": BODY, "tags": ["signage", "type"],
             "id": "11", "date-gmt": "2026-09-02 06:16:30 GMT"},
            {"url": "https://blog.example/post/2", "regular-title": "", "regular-body": "<p>text only</p>", "tags": []}]

    def __call__(self, url):
        self.requests.append(url)
        if "/api/read/json" not in url:
            raise OSError("HTTP 403")
        data = {"tumblelog": {"title": "Blog"}, "posts-total": 300, "posts": self.posts}
        return SimpleNamespace(body=b"var tumblr_api_read = " + json.dumps(data).encode() + b";",
                               final_url="", status=200, content_type="text/javascript")


class TumblrTests(LibraryCase):
    def test_post_images_take_the_widest_variant_as_full_size(self):
        self.assertEqual(tumblr.post_images({"regular-body": BODY}), [("https://m.example/a/s2048.jpg", "https://m.example/a/s640.jpg", 1200, 1800)])

    def test_older_photo_posts_use_their_photo_fields(self):
        post = {"photo-url-1280": "https://m.example/big.jpg", "photo-url-500": "https://m.example/mid.jpg"}
        self.assertEqual(tumblr.post_images(post), [("https://m.example/big.jpg", "https://m.example/mid.jpg", 0, 0)])

    def test_items_skip_posts_without_images_and_read_a_random_stretch(self):
        fetcher = FakeBlog()
        result = tumblr.items("https://blog.example/", fetcher, random.Random(1))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["source_id"], result[0]["url"], result[0]["title"], result[0]["term"]),
                         ("tumblr", "https://m.example/a/s2048.jpg", "Sign & type", "signage"))
        self.assertEqual(result[0]["page_url"], "https://blog.example/post/1")
        self.assertEqual((result[0]["tags"], result[0]["source_ref"], result[0]["posted_at"], result[0]["collection"],
                          result[0]["width"], result[0]["height"]), (["signage", "type"], "11", "2026-09-02", "Blog", 1200, 1800))
        self.assertIn("start=", fetcher.requests[-1])

    def test_follow_lists_the_blog_once_and_refuses_unreadable_links(self):
        first = tumblr.follow(self.conn, "https://Blog.example/page/2", FakeBlog())
        again = tumblr.follow(self.conn, "https://blog.example", FakeBlog())
        self.assertEqual((first["id"], first["label"], first["url"]), (again["id"], "Blog", "https://blog.example/"))
        with self.assertRaises(ValueError):
            tumblr.follow(self.conn, "https://down.example/", lambda url: (_ for _ in ()).throw(OSError("down")))
        with self.assertRaises(ValueError):
            tumblr.follow(self.conn, "not a link", FakeBlog())

    def test_refresh_stores_a_followed_blogs_images(self):
        tumblr.follow(self.conn, "https://blog.example/", FakeBlog())
        result = feed.refresh(self.conn, FakeBlog(), random.Random(1))
        self.assertEqual(result["added"], 1)
        item = feed.list_items(self.conn)["items"][0]
        self.assertEqual(item["source_id"], "tumblr")
        self.assertEqual(feed.accept(self.conn, [item["id"]])["added"], 1)
        entry = library.get_entry(self.conn.execute("SELECT id FROM entries").fetchone()[0])
        self.assertEqual(entry["tags"], ["signage", "type"])
        self.assertEqual(entry["source"], {"source_service": "tumblr", "source_ref": "11", "collection": "Blog",
                                           "posted_at": "2026-09-02"})

    def test_backfill_fills_saved_entries_from_their_post_link(self):
        entry = self.add_entry(title="x")
        self.conn.execute("UPDATE entries SET source_url = 'https://blog.example/post/11/slug' WHERE id = ?", (entry,))
        self.assertEqual(tumblr.backfill(self.conn, FakeBlog()), 1)
        self.assertEqual(tumblr.backfill(self.conn, FakeBlog()), 0)
        row = self.conn.execute("SELECT source_service, source_ref, collection, posted_at FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual(tuple(row), ("tumblr", "11", "Blog", "2026-09-02"))
        self.assertEqual(len(self.conn.execute("SELECT 1 FROM entry_tags WHERE entry_id = ?", (entry,)).fetchall()), 2)


if __name__ == "__main__":
    unittest.main()
