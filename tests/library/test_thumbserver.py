"""Tests for the loopback thumbnail server and the paging that feeds the grid."""

import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hyperbridge  # noqa: E402
from bridge.core import thumbserver  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as err:
        return err.code, b"", err.headers


class ThumbServerTests(LibraryOpsCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(thumbserver.stop)

    def thumbnail(self, title="A"):
        entry = self.add_entry(title)
        asset = self.add_asset(entry, kind="thumbnail", data=b"RIFFxxxxWEBP", suffix=".webp")
        path = self.conn.execute("SELECT path FROM assets WHERE id = ?", (asset,)).fetchone()[0]
        return entry, path

    def test_serves_a_stored_thumbnail_and_validates_with_its_etag(self):
        _, path = self.thumbnail()
        thumbserver.start()
        status, body, headers = fetch(thumbserver.url_for(path))
        self.assertEqual((status, body, headers["Content-Type"]), (200, b"RIFFxxxxWEBP", "image/webp"))
        again = fetch(thumbserver.url_for(path), {"If-None-Match": headers["ETag"]})
        self.assertEqual(again[0], 304)

    def test_refuses_a_wrong_token_and_paths_outside_the_assets_folder(self):
        _, path = self.thumbnail()
        base = thumbserver.start()
        self.assertEqual(fetch(base.replace(base.rstrip("/").rsplit("/", 1)[1], "wrong") + path)[0], 404)
        self.assertEqual(fetch(base + "../hyperbridge.db")[0], 404)
        self.assertEqual(fetch(base + "assets/missing.webp")[0], 404)
        self.assertIsNone(thumbserver.url_for("hyperbridge.db"))

    def test_no_url_while_the_server_is_off(self):
        _, path = self.thumbnail()
        self.assertIsNone(thumbserver.url_for(path))


class PagingTests(LibraryOpsCase):
    def test_pages_and_totals_come_from_the_database_in_order(self):
        ids = [self.add_entry(f"Entry {number}") for number in range(5)]
        for position, entry in enumerate(ids):
            self.conn.execute("UPDATE entries SET created_at = ? WHERE id = ?", (f"2026-01-0{position + 1}T00:00:00", entry))
        api = hyperbridge.HyperbridgeAPI()
        page = api.list_entries("", 1, 2)
        self.assertEqual(page["total"], 5)
        self.assertEqual([entry["title"] for entry in page["entries"]], ["Entry 3", "Entry 2"])

    def test_known_thumbnails_are_not_sent_again(self):
        entry = self.add_entry("A")
        self.add_asset(entry, kind="thumbnail", data=b"RIFFxxxxWEBP", suffix=".webp")
        api = hyperbridge.HyperbridgeAPI()
        first = api.list_entries()["entries"][0]
        self.assertTrue(first["thumb"] and not first["keep"])
        again = api.list_entries("", 0, 60, None, "", "", "", "", [entry])["entries"][0]
        self.assertEqual((again["thumb"], again["keep"]), (None, True))


if __name__ == "__main__":
    unittest.main()
