"""Tests for reading Tumblr posts and Pinterest pins again to fill what saved entries lack."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core.fetchguard import FetchError  # noqa: E402
from bridge.ingest import restore  # noqa: E402
from tests.ingest.test_capture import LibraryCase  # noqa: E402


def body(text):
    return SimpleNamespace(body=text.encode())


def fetcher(url, **kwargs):
    if "api/read/json" in url:
        post = {"id": "77", "regular-title": "Blue chair", "tags": ["chairs"], "date-gmt": "2024-05-01 10:00:00 GMT",
                "photo-caption": "<p>Blue chair</p><p>Oak and lacquer, 1962.</p>"}
        return body("var tumblr_api_read = " + json.dumps({"posts": [post], "tumblelog": {"title": "b"}}) + ";")
    if "PinResource" in url:
        pin = {"grid_title": "Quiet harbor", "description": "Boats at dusk", "link_domain": "example.com",
               "created_at": "Mon, 20 Mar 2023 16:24:21 +0000", "hashtags": ["#sea"]}
        return body(json.dumps({"resource_response": {"data": pin}}))
    raise OSError("unreachable")


class RestoreDetailsTests(LibraryCase):
    def add(self, service, ref, url, title="", manual="[]", collection=""):
        self.conn.execute(
            "INSERT INTO entries (uid, title, source_url, source_key, state, source_service, source_ref, manual_fields,"
            " collection, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'captured', ?, ?, ?, ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (f"u{ref}", title, url, url, service, ref, manual, collection))
        return self.conn.execute("SELECT id FROM entries WHERE uid = ?", (f"u{ref}",)).fetchone()[0]

    def entry(self, entry_id):
        return dict(self.conn.execute(
            "SELECT title, description, publisher, posted_at, updated_at FROM entries WHERE id = ?", (entry_id,)).fetchone())

    def tags(self, entry_id):
        return [row[0] for row in self.conn.execute(
            "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id WHERE et.entry_id = ?", (entry_id,))]

    def test_tumblr_and_pinterest_entries_get_their_source_details(self):
        post = self.add("tumblr", "77", "https://blog.tumblr.com/post/77/slug")
        pin = self.add("pinterest", "1001", "https://www.pinterest.com/pin/1001/", title="IMG_8841.jpg")
        self.conn.execute("INSERT INTO tags (name) VALUES ('chair')")
        self.assertEqual(restore.details(self.conn, fetcher), 2)
        self.assertEqual(self.entry(post), {
            "title": "Blue chair", "description": "Blue chair\nOak and lacquer, 1962.", "publisher": "",
            "posted_at": "2024-05-01", "updated_at": "2026-01-01T00:00:00"})
        self.assertEqual(self.entry(pin), {
            "title": "Quiet harbor", "description": "Boats at dusk", "publisher": "example.com",
            "posted_at": "2023-03-20", "updated_at": "2026-01-01T00:00:00"})
        self.assertEqual((self.tags(post), self.tags(pin)), (["chair"], []))

    def test_a_placeholder_title_is_replaced_but_hand_written_and_real_titles_are_kept(self):
        placeholder = self.add("pinterest", "1", "https://www.pinterest.com/pin/1/", title="Harbors", collection="Places / Harbors")
        edited = self.add("pinterest", "2", "https://www.pinterest.com/pin/2/", manual='["title"]')
        real = self.add("pinterest", "3", "https://www.pinterest.com/pin/3/", title="Kept")
        restore.details(self.conn, fetcher)
        titles = [self.entry(entry)["title"] for entry in (placeholder, edited, real)]
        self.assertEqual(titles, ["Quiet harbor", "", "Kept"])
        self.assertEqual(self.entry(real)["description"], "Boats at dusk")

    def test_each_entry_is_read_once(self):
        self.add("pinterest", "4", "https://www.pinterest.com/pin/4/", title="Kept")
        calls = []

        def counting(url, **kwargs):
            calls.append(url)
            return fetcher(url, **kwargs)

        restore.details(self.conn, counting)
        restore.details(self.conn, counting)
        self.assertEqual(len(calls), 1)

    def test_an_unreadable_source_waits_then_is_tried_again(self):
        entry = self.add("pinterest", "5", "https://www.pinterest.com/pin/5/")

        def broken(url, **kwargs):
            raise OSError("down")

        self.assertEqual(restore.details(self.conn, broken), 0)
        self.assertEqual(self.entry(entry)["title"], "")
        self.assertEqual(restore.details(self.conn, fetcher), 0)
        self.conn.execute("UPDATE entry_checks SET checked_at = '2000-01-01T00:00:00'")
        self.assertEqual(restore.details(self.conn, fetcher), 1)
        self.assertEqual(self.entry(entry)["title"], "Quiet harbor")

    def test_a_service_that_pushes_back_is_skipped_for_the_rest_of_the_pass(self):
        for ref in ("6", "7"):
            self.add("pinterest", ref, f"https://www.pinterest.com/pin/{ref}/")
        calls = []

        def limited(url, **kwargs):
            calls.append(url)
            raise FetchError("http_status", "HTTP 429", 429)

        self.assertEqual(restore.details(self.conn, limited), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entry_checks").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
