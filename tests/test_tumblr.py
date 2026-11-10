"""Tests for following and pulling from a Tumblr blog."""

import json
import os
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HYPERBRIDGE_EMBEDDINGS"] = "0"

import feed  # noqa: E402
import tumblr  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402

BODY = ('<div class="npf_row"><figure><img src="https://m.example/a/s640.jpg" srcset="https://m.example/a/s75.jpg 75w, '
        'https://m.example/a/s2048.jpg 2000w, https://m.example/a/s400.jpg 400w"></figure></div><p>Sign &amp; type</p>')


class FakeBlog:
    def __init__(self, posts=None):
        self.requests = []
        self.posts = posts if posts is not None else [
            {"url": "https://blog.example/post/1", "regular-title": "", "regular-body": BODY, "tags": ["signage", "type"]},
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
        self.assertEqual(tumblr.post_images({"regular-body": BODY}), [("https://m.example/a/s2048.jpg", "https://m.example/a/s640.jpg")])

    def test_older_photo_posts_use_their_photo_fields(self):
        post = {"photo-url-1280": "https://m.example/big.jpg", "photo-url-500": "https://m.example/mid.jpg"}
        self.assertEqual(tumblr.post_images(post), [("https://m.example/big.jpg", "https://m.example/mid.jpg")])

    def test_items_skip_posts_without_images_and_read_a_random_stretch(self):
        fetcher = FakeBlog()
        result = tumblr.items("https://blog.example/", fetcher, random.Random(1))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["source_id"], result[0]["url"], result[0]["title"], result[0]["term"]),
                         ("tumblr", "https://m.example/a/s2048.jpg", "Sign & type", "signage"))
        self.assertEqual(result[0]["page_url"], "https://blog.example/post/1")
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
        self.assertEqual(feed.list_items(self.conn)["items"][0]["source_id"], "tumblr")


if __name__ == "__main__":
    unittest.main()
