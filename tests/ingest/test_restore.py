"""Tests for restoring lost titles from Tumblr and Pinterest."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import restore  # noqa: E402
from tests.ingest.test_capture import LibraryCase  # noqa: E402


def body(text):
    return SimpleNamespace(body=text.encode())


def fetcher(url, **kwargs):
    if "api/read/json" in url:
        post = {"id": "77", "regular-title": "Blue chair", "tags": []}
        return body("var tumblr_api_read = " + json.dumps({"posts": [post], "tumblelog": {"title": "b"}}) + ";")
    if "PinResource" in url:
        return body(json.dumps({"resource_response": {"data": {"grid_title": "Quiet harbor"}}}))
    raise OSError("unreachable")


class RestoreTitleTests(LibraryCase):
    def add(self, service, ref, url, title="", manual="[]"):
        self.conn.execute(
            "INSERT INTO entries (uid, title, source_url, source_key, state, source_service, source_ref, manual_fields,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 'captured', ?, ?, ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (f"u{ref}", title, url, url, service, ref, manual))
        return self.conn.execute("SELECT id FROM entries WHERE uid = ?", (f"u{ref}",)).fetchone()[0]

    def title(self, entry_id):
        return self.conn.execute("SELECT title FROM entries WHERE id = ?", (entry_id,)).fetchone()[0]

    def test_untitled_tumblr_and_pinterest_entries_get_their_source_title(self):
        post = self.add("tumblr", "77", "https://blog.tumblr.com/post/77/slug")
        pin = self.add("pinterest", "1001", "https://www.pinterest.com/pin/1001/", title="IMG_8841.jpg")
        self.assertEqual(restore.titles(self.conn, fetcher), 2)
        self.assertEqual((self.title(post), self.title(pin)), ("Blue chair", "Quiet harbor"))

    def test_hand_written_and_real_titles_are_left_alone(self):
        edited = self.add("pinterest", "1", "https://www.pinterest.com/pin/1/", manual='["title"]')
        real = self.add("pinterest", "2", "https://www.pinterest.com/pin/2/", title="Kept")
        self.assertEqual(restore.titles(self.conn, fetcher), 0)
        self.assertEqual((self.title(edited), self.title(real)), ("", "Kept"))

    def test_an_unreadable_source_is_skipped_without_failing(self):
        entry = self.add("pinterest", "3", "https://www.pinterest.com/pin/3/")

        def broken(url, **kwargs):
            raise OSError("down")

        self.assertEqual(restore.titles(self.conn, broken), 0)
        self.assertEqual(self.title(entry), "")


if __name__ == "__main__":
    unittest.main()
