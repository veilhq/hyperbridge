"""Tests for following and pulling from a site's RSS or Atom feed."""

import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import enrich  # noqa: E402
from bridge.ingest import feed  # noqa: E402
from bridge.ingest import rss  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

PAGE = ('<!doctype html><html><head><title>Figs</title>'
        '<link rel="alternate" type="application/rss+xml" title="Figs" href="/rss.xml"></head><body></body></html>')
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Figs &amp; Plums</title><link>https://site.example/</link>
<item><title>Nomad Workstation</title><link>https://site.example/article?id=nomad</link><guid isPermaLink="false">nomad</guid>
<pubDate>Tue, 17 Nov 2026 23:00:00 GMT</pubDate><category>Design</category>
<description>&lt;p&gt;&lt;a href="https://www.approach.studio/work"&gt;Approach Studio&lt;/a&gt;&lt;/p&gt;</description>
<media:content url="https://site.example/images/nomad.webp" medium="image" width="1600" height="1200"/></item>
<item><title>Inline</title><link>/article?id=inline</link><guid>inline</guid>
<description>&lt;p&gt;Painted&lt;/p&gt;&lt;img src="/images/inline.jpg"&gt;</description></item>
<item><title>Words only</title><link>https://site.example/article?id=words</link><description>No pictures</description></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Site</title>
<entry><title>Chair</title><id>tag:chair</id><published>2026-10-01T08:00:00Z</published><category term="furniture"/>
<link rel="alternate" href="https://atom.example/chair"/><link rel="enclosure" href="https://atom.example/chair.zip"/>
<content type="html">&lt;img src="https://atom.example/chair.jpg"&gt;</content></entry>
</feed>"""


class FakeSite:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def __call__(self, url, headers=None):
        self.requests.append(url)
        if url not in self.pages:
            raise OSError("HTTP 404")
        return SimpleNamespace(body=self.pages[url].encode(), final_url=url, status=200, content_type="text/html")


SITE = {"https://site.example/": PAGE, "https://site.example/rss.xml": RSS}


class RssTests(LibraryCase):
    def test_entries_read_media_and_inline_images_and_skip_text_only_posts(self):
        title, found = rss.entries(rss._parse(RSS.encode()), "https://site.example/rss.xml")
        self.assertEqual(title, "Figs & Plums")
        self.assertEqual([entry["images"] for entry in found], [
            [("https://site.example/images/nomad.webp", 1600, 1200)], [("https://site.example/images/inline.jpg", 0, 0)], []])
        self.assertEqual((found[0]["date"], found[0]["categories"], found[0]["credit"]), ("2026-11-17", ["Design"], "approach.studio"))

    def test_atom_entries_are_read_too(self):
        title, found = rss.entries(rss._parse(ATOM.encode()), "https://atom.example/feed")
        self.assertEqual((title, found[0]["link"], found[0]["date"]), ("Atom Site", "https://atom.example/chair", "2026-10-01"))
        self.assertEqual(found[0]["images"], [("https://atom.example/chair.jpg", 0, 0)])

    def test_items_carry_the_post_page_tags_and_credit(self):
        items = rss.items("https://site.example/rss.xml", FakeSite(SITE), random.Random(1))
        by_title = {item["title"]: item for item in items}
        self.assertEqual(sorted(by_title), ["Inline", "Nomad Workstation"])
        nomad = by_title["Nomad Workstation"]
        self.assertEqual((nomad["source_id"], nomad["page_url"], nomad["tags"], nomad["collection"], nomad["description"], nomad["publisher"]),
                         ("rss", "https://site.example/article?id=nomad", ["Design"], "Figs & Plums", "Approach Studio", "approach.studio"))
        self.assertEqual(by_title["Inline"]["page_url"], "https://site.example/article?id=inline")

    def test_following_a_site_page_finds_its_feed(self):
        item = rss.follow(self.conn, "https://site.example/", FakeSite(SITE))
        self.assertEqual((item["kind"], item["url"], item["label"]), ("rss", "https://site.example/rss.xml", "Figs & Plums"))

    def test_a_site_without_a_feed_or_without_images_cannot_be_followed(self):
        with self.assertRaisesRegex(ValueError, "Could not find"):
            rss.follow(self.conn, "https://bare.example/", FakeSite({"https://bare.example/": "<html></html>"}))
        words = RSS.replace('<media:content url="https://site.example/images/nomad.webp" medium="image" width="1600" height="1200"/>', "")
        words = words.replace("&lt;img src=\"/images/inline.jpg\"&gt;", "")
        with self.assertRaisesRegex(ValueError, "no images"):
            rss.follow(self.conn, "https://site.example/rss.xml", FakeSite({"https://site.example/rss.xml": words}))

    def test_follow_site_tries_tumblr_first_then_the_feed(self):
        site = FakeSite(SITE)
        self.assertEqual(feed.follow_site(self.conn, "https://site.example/", site)["kind"], "rss")
        self.assertIn("/api/read/json", site.requests[0])

    def test_feed_refresh_pulls_followed_feeds_into_discover(self):
        rss.follow(self.conn, "https://site.example/", FakeSite(SITE))
        result = feed.refresh(self.conn, fetcher=FakeSite(SITE), rng=random.Random(1))
        self.assertEqual((result["added"], result["failed"]), (2, 0))
        self.assertEqual(feed.list_items(self.conn)["total"], 2)

    def test_an_embedded_post_list_reaches_past_the_feed(self):
        posts = ('[{"id": "nomad", "date": "2026-11-17", "section": "design", "title": "Approach Studio", "src": "images/nomad.webp",'
                 ' "article": {"title": "Nomad Workstation", "by": "Approach Studio", "blocks": ['
                 '{"type": "text", "text": "Made by [Approach & Co](https://www.approach.studio/work?a=1&b=2)"},'
                 '{"type": "image", "src": "images/nomad-2.jpg"}]}},'
                 ' {"id": "old", "date": "2026-10-01", "section": "art", "title": "Old Maker", "src": "/images/old.jpg",'
                 ' "article": {"title": "Old Work", "by": "Editors"}},'
                 ' {"id": "later", "date": "2099-01-01", "publishAt": "2099-01-01T00:00:00-05:00", "src": "images/later.jpg"}]')
        site = dict(SITE, **{"https://site.example/": PAGE.replace("<body>", f"<body><script>window.POSTS={posts};</script>")})
        items = rss.items("https://site.example/rss.xml", FakeSite(site), random.Random(1))
        self.assertEqual(sorted(item["url"] for item in items), [
            "https://site.example/images/nomad-2.jpg", "https://site.example/images/nomad.webp", "https://site.example/images/old.jpg"])
        nomad = next(item for item in items if item["url"].endswith("nomad.webp"))
        self.assertEqual((nomad["title"], nomad["creator"], nomad["page_url"], nomad["tags"], nomad["description"], nomad["publisher"]),
                         ("Nomad Workstation", "Approach Studio", "https://site.example/article?id=nomad", ["Design"],
                          "Made by Approach & Co", "approach.studio"))
        self.assertEqual(nomad["collection"], "Figs & Plums")
        old = next(item for item in items if item["url"].endswith("old.jpg"))
        self.assertEqual((old["title"], old["creator"]), ("Old Work", "Old Maker"))

    def test_a_feed_is_used_when_the_home_page_cannot_be_read(self):
        items = rss.items("https://site.example/rss.xml", FakeSite({"https://site.example/rss.xml": RSS}), random.Random(1))
        self.assertEqual(len(items), 2)

    def test_saved_feed_images_are_tagged_with_their_site_not_the_service(self):
        row = {"source_service": "rss", "domain": "www.site.example", "collection": "Figs"}
        self.assertEqual(enrich.source_tags(row), ["site.example", "figs"])


if __name__ == "__main__":
    unittest.main()
