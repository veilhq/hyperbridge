"""Tests for filling saved X and Instagram posts from their links."""

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import social  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

MEDIA = {"gql_data": {"shortcode_media": {"shortcode": "Abc123", "owner": {"username": "studio"},
                                          "edge_media_to_caption": {"edges": [{"node": {"text": "New sign #Wayfinding #type_2 done"}}]}}}}


def fetcher(url):
    if "syndication" in url:
        data = {"text": "Look &amp; see #Poster", "created_at": "2026-03-04T10:00:00.000Z", "user": {"screen_name": "ada"},
                "entities": {"hashtags": [{"text": "Poster"}]}}
        body = json.dumps(data).encode()
    elif "instagram.com" in url:
        body = ('<html>"contextJSON":' + json.dumps(json.dumps(MEDIA)) + "</html>").encode()
    else:
        raise OSError("HTTP 404")
    return SimpleNamespace(body=body, final_url="", status=200, content_type="text/html")


class SocialTests(LibraryCase):
    def saved(self, url):
        entry = self.add_entry(title="x")
        self.conn.execute("UPDATE entries SET source_url = ? WHERE id = ?", (url, entry))
        return entry

    def tags(self, entry):
        return sorted(row[0] for row in self.conn.execute(
            "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id WHERE et.entry_id = ?", (entry,)))

    def test_hashtags_are_lowercased_distinct_and_skip_numbers(self):
        self.assertEqual(social.hashtags("a #One #one #2024 #two_x &#39;"), ["one", "two_x"])

    def test_x_posts_fill_creator_text_date_and_tags(self):
        entry = self.saved("https://x.com/ada/status/99?s=20")
        self.assertEqual(social.backfill(self.conn, fetcher), 1)
        row = self.conn.execute("SELECT creator, description, publisher, source_service, source_ref, posted_at FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual(tuple(row), ("ada", "Look & see #Poster", "X", "x", "99", "2026-03-04"))
        self.assertEqual(self.tags(entry), ["Poster"])

    def test_instagram_posts_fill_creator_caption_and_tags(self):
        entry = self.saved("https://www.instagram.com/p/Abc123/")
        self.assertEqual(social.backfill(self.conn, fetcher), 1)
        row = self.conn.execute("SELECT creator, publisher, source_service, source_ref FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual(tuple(row), ("studio", "Instagram", "instagram", "Abc123"))
        self.assertEqual(self.tags(entry), ["type_2", "wayfinding"])

    def test_filled_fields_are_kept_and_unreadable_posts_are_retried(self):
        kept = self.saved("https://twitter.com/ada/status/5")
        self.conn.execute("UPDATE entries SET creator = 'Ada L' WHERE id = ?", (kept,))
        broken = self.saved("https://www.instagram.com/p/Zzz/")
        self.assertEqual(social.backfill(self.conn, lambda url: (_ for _ in ()).throw(OSError("down"))), 0)
        self.assertEqual(social.backfill(self.conn, fetcher), 2)
        self.assertEqual(self.conn.execute("SELECT creator FROM entries WHERE id = ?", (kept,)).fetchone()[0], "Ada L")
        self.assertEqual(social.backfill(self.conn, fetcher), 0)
        self.assertTrue(broken)


if __name__ == "__main__":
    unittest.main()
