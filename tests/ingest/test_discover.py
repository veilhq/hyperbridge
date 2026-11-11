"""Tests for finding candidate images on a pasted page and adding the chosen ones to a set."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import discover  # noqa: E402
from bridge.library import sets  # noqa: E402
from tests.ingest.test_capture import png_bytes  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

PAGE = "https://example.com/board"
HTML = b"""<html><head><meta property="og:image" content="/cover.png"><title>A Board</title></head><body>
<img src="/a.png" srcset="/a-small.png 200w, /a-big.png 800w">
<img data-src="/lazy.png">
<img src="/cover.png">
<img src="data:image/gif;base64,AAAA">
<img src="/tiny.png">
<a href="/full.jpg">link</a>
<a href="/page.html">not an image</a>
</body></html>"""


def fake_fetcher(sizes):
    def fetch(url):
        if url == PAGE:
            return SimpleNamespace(body=HTML, content_type="text/html", final_url=PAGE, url=PAGE)
        path = url.replace("https://example.com", "")
        if path in sizes:
            return SimpleNamespace(body=png_bytes(*sizes[path]), content_type="image/png", final_url=url, url=url)
        raise OSError("missing")
    return fetch


class PageImagesTests(unittest.TestCase):
    def test_finds_preview_lazy_srcset_and_linked_images_once(self):
        urls = discover.page_images(HTML, PAGE)
        self.assertEqual(urls[0], "https://example.com/cover.png")
        for expected in ("/a-big.png", "/lazy.png", "/full.jpg", "/tiny.png"):
            self.assertIn("https://example.com" + expected, urls)
        self.assertNotIn("https://example.com/a-small.png", urls)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertFalse([url for url in urls if url.startswith("data:") or url.endswith(".html")])


class ArenaTests(LibraryCase):
    def test_channel_link_lists_the_images_from_its_api(self):
        seen = []
        channel = {"data": [
            {"type": "Image", "image": {"src": "https://cdn.example.com/a.png"}},
            {"type": "Text", "image": None},
            {"type": "Link", "image": {"src": "https://cdn.example.com/b.png"}},
        ]}

        def fetch(url):
            seen.append(url)
            if "api.are.na" in url:
                data = channel if "/contents" in url else {"title": "Scans"}
                return SimpleNamespace(body=json.dumps(data).encode(), content_type="application/json", final_url=url)
            return SimpleNamespace(body=png_bytes(400, 300), content_type="image/png", final_url=url)

        result = discover.discover(self.conn, "https://www.are.na/someone/scans", fetch)
        self.assertEqual(result["title"], "Scans")
        self.assertEqual([item["url"] for item in result["candidates"]], ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"])
        self.assertIn("https://api.are.na/v3/channels/scans/contents?per=100&page=1", seen)

    def test_only_channel_links_use_the_api(self):
        self.assertEqual(discover._arena_slug("https://www.are.na/someone/scans"), "scans")
        self.assertIsNone(discover._arena_slug("https://www.are.na/block/123"))
        self.assertIsNone(discover._arena_slug("https://example.com/someone/scans"))


class DiscoverTests(LibraryCase):
    SIZES = {"/cover.png": (400, 300), "/a-big.png": (800, 600), "/lazy.png": (300, 300), "/tiny.png": (40, 40)}

    def test_small_and_unreachable_images_are_left_out(self):
        result = discover.discover(self.conn, PAGE, fake_fetcher(self.SIZES))
        urls = {item["url"] for item in result["candidates"]}
        self.assertEqual(urls, {"https://example.com/cover.png", "https://example.com/a-big.png", "https://example.com/lazy.png"})
        self.assertEqual(result["title"], "A Board")
        self.assertTrue(all(item["thumb"].startswith("data:image/jpeg;base64,") for item in result["candidates"]))

    def test_images_already_in_the_library_are_marked(self):
        from bridge.ingest import capture

        existing = capture.add_link(self.conn, "https://example.com/lazy.png")["entry_id"]
        result = discover.discover(self.conn, PAGE, fake_fetcher(self.SIZES))
        marks = {item["url"]: item["known_entry_id"] for item in result["candidates"]}
        self.assertEqual(marks["https://example.com/lazy.png"], existing)
        self.assertIsNone(marks["https://example.com/cover.png"])

    def test_adding_candidates_credits_the_page_and_fills_the_set(self):
        made = sets.create_set("Board")["set"]["id"]
        urls = ["https://example.com/cover.png", "https://example.com/lazy.png"]
        result = discover.add_candidates(self.conn, urls, PAGE, made)
        self.assertEqual(result, {"added": 2, "placed": 2})
        rows = self.conn.execute("SELECT source_url, source_key FROM entries ORDER BY id").fetchall()
        self.assertEqual([row["source_url"] for row in rows], [PAGE, PAGE])
        self.assertEqual(rows[0]["source_key"], "https://example.com/cover.png")
        again = discover.add_candidates(self.conn, urls, PAGE, made)
        self.assertEqual(again, {"added": 0, "placed": 2})


if __name__ == "__main__":
    unittest.main()
