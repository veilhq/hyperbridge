"""Tests for reading a public Pinterest board and offering its pins as Discover candidates."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import fetchguard  # noqa: E402
from bridge.ingest import discover, pinterest  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402
from tests.ingest.test_capture import png_bytes  # noqa: E402

BOARD = "https://www.pinterest.com/someone/moodboard/"


def pin(number):
    return {"type": "pin", "images": {
        "474x": {"url": f"https://i.pinimg.com/474x/aa/{number}.jpg"},
        "orig": {"url": f"https://i.pinimg.com/originals/aa/{number}.jpg", "width": 1200, "height": 800}}}


def json_response(data):
    return SimpleNamespace(body=json.dumps({"resource_response": data}).encode(), content_type="application/json", final_url="")


def fake_pinterest(calls):
    def fetch(url, headers=None):
        if "i.pinimg.com" in url:
            return SimpleNamespace(body=png_bytes(200, 150), content_type="image/png", final_url=url)
        calls.append((url, headers))
        options = json.loads(parse_qs(urlsplit(url).query)["data"][0])["options"]
        if "/BoardResource/" in url:
            return json_response({"data": {"id": "42", "name": "Moodboard"}})
        if "bookmarks" not in options:
            return json_response({"data": [pin(1), pin(2), {"type": "story"}], "bookmark": "next"})
        return json_response({"data": [pin(2), pin(3)], "bookmark": "-end-"})
    return fetch


class BoardLinkTests(unittest.TestCase):
    def test_only_board_links_are_recognised(self):
        self.assertEqual(pinterest.board_ref(BOARD), ("someone", "moodboard"))
        self.assertEqual(pinterest.board_ref("https://pinterest.co.uk/someone/moodboard"), ("someone", "moodboard"))
        self.assertIsNone(pinterest.board_ref("https://www.pinterest.com/pin/12345/"))
        self.assertIsNone(pinterest.board_ref("https://www.pinterest.com/someone/"))
        self.assertIsNone(pinterest.board_ref("https://example.com/someone/moodboard"))


class BoardPinTests(unittest.TestCase):
    def test_pages_are_followed_and_duplicates_dropped(self):
        calls = []
        name, pins = pinterest.board_pins(("someone", "moodboard"), fake_pinterest(calls))
        self.assertEqual(name, "Moodboard")
        self.assertEqual([item["url"] for item in pins], [f"https://i.pinimg.com/originals/aa/{n}.jpg" for n in (1, 2, 3)])
        self.assertTrue(all("X-Pinterest-PWS-Handler" in headers for _, headers in calls))

    def test_unknown_board_yields_no_pins(self):
        def fetch(url, headers=None):
            return json_response({"data": None})
        self.assertEqual(pinterest.board_pins(("a", "b"), fetch), ("", []))


class FetchHeaderTests(unittest.TestCase):
    def test_credentials_headers_are_refused(self):
        with self.assertRaises(fetchguard.FetchError):
            fetchguard.safe_fetch("https://example.com/", headers={"Cookie": "a=b"}, resolver=lambda host: ["93.184.216.34"])


class DiscoverBoardTests(LibraryCase):
    def test_board_pins_become_candidates_with_full_size_urls(self):
        result = discover.discover(self.conn, BOARD, fake_pinterest([]))
        self.assertEqual(result["title"], "Moodboard")
        self.assertEqual(len(result["candidates"]), 3)
        first = result["candidates"][0]
        self.assertEqual(first["url"], "https://i.pinimg.com/originals/aa/1.jpg")
        self.assertEqual((first["width"], first["height"]), (1200, 800))
        self.assertTrue(first["thumb"].startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
