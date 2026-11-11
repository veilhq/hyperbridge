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

BOARD = "https://www.pinterest.com/someone/moodboard/"


def pin(number, pin_id=None):
    return {"type": "pin", "id": pin_id or str(1000 + number), "images": {
        "474x": {"url": f"https://i.pinimg.com/474x/aa/{number}.jpg"},
        "orig": {"url": f"https://i.pinimg.com/originals/aa/{number}.jpg", "width": 1200, "height": 800}}}


def json_response(data):
    return SimpleNamespace(body=json.dumps({"resource_response": data}).encode(), content_type="application/json", final_url="")


def fake_pinterest(calls):
    """Board with 2 sections (pins 1-2 and 3) plus a loose pin 4, so 4 pins in all."""
    def fetch(url, headers=None):
        calls.append((url, headers))
        options = json.loads(parse_qs(urlsplit(url).query)["data"][0])["options"]
        if "/BoardResource/" in url:
            return json_response({"data": {"id": "42", "name": "Moodboard", "pin_count": 4}})
        if "/BoardSectionsResource/" in url:
            return json_response({"data": [{"id": "s1", "slug": "faces", "title": "Faces"}, {"id": "s2", "slug": "hands", "title": "Hands"}]})
        if "/BoardSectionPinsResource/" in url:
            if options["section_id"] == "s1":
                if "bookmarks" not in options:
                    return json_response({"data": [pin(1), {"type": "story"}], "bookmark": "next"})
                return json_response({"data": [pin(2)], "bookmark": "-end-"})
            return json_response({"data": [pin(3), pin(2)], "bookmark": "-end-"})
        return json_response({"data": [pin(1), pin(4, "e1_abc")], "bookmark": "-end-"})
    return fetch


class BoardLinkTests(unittest.TestCase):
    def test_only_board_links_are_recognised(self):
        self.assertEqual(pinterest.board_ref(BOARD), ("someone", "moodboard", ""))
        self.assertEqual(pinterest.board_ref(BOARD + "faces/"), ("someone", "moodboard", "faces"))
        self.assertEqual(pinterest.board_ref("https://pinterest.co.uk/someone/moodboard"), ("someone", "moodboard", ""))
        self.assertIsNone(pinterest.board_ref("https://www.pinterest.com/pin/12345/"))
        self.assertIsNone(pinterest.board_ref("https://www.pinterest.com/someone/"))
        self.assertIsNone(pinterest.board_ref("https://example.com/someone/moodboard"))


class BoardPinTests(unittest.TestCase):
    def test_sections_are_pulled_with_names_and_loose_pins_added(self):
        calls = []
        name, pins = pinterest.board_pins(("someone", "moodboard", ""), fake_pinterest(calls))
        self.assertEqual(name, "Moodboard")
        self.assertEqual([item["url"] for item in pins], [f"https://i.pinimg.com/originals/aa/{n}.jpg" for n in (1, 2, 3, 4)])
        self.assertEqual([item["section"] for item in pins], ["Faces", "Faces", "Hands", ""])
        self.assertEqual([item["id"] for item in pins], ["1001", "1002", "1003", ""])
        self.assertTrue(all("X-Pinterest-PWS-Handler" in headers for _, headers in calls))

    def test_a_section_link_pulls_only_that_section(self):
        _, pins = pinterest.board_pins(("someone", "moodboard", "hands"), fake_pinterest([]))
        self.assertEqual({item["section"] for item in pins}, {"Hands"})
        self.assertEqual(len(pins), 2)

    def test_unknown_board_yields_no_pins(self):
        def fetch(url, headers=None):
            return json_response({"data": None})
        self.assertEqual(pinterest.board_pins(("a", "b", ""), fetch), ("", []))


class FetchHeaderTests(unittest.TestCase):
    def test_credentials_headers_are_refused(self):
        with self.assertRaises(fetchguard.FetchError):
            fetchguard.safe_fetch("https://example.com/", headers={"Cookie": "a=b"}, resolver=lambda host: ["93.184.216.34"])


class DiscoverBoardTests(LibraryCase):
    def test_board_pins_become_candidates_with_board_and_section(self):
        result = discover.discover(self.conn, BOARD, fake_pinterest([]))
        self.assertEqual(result["title"], "Moodboard")
        self.assertEqual(len(result["candidates"]), 4)
        first = result["candidates"][0]
        self.assertEqual(first["url"], "https://i.pinimg.com/originals/aa/1.jpg")
        self.assertEqual((first["width"], first["height"]), (1200, 800))
        self.assertEqual(first["thumb"], "https://i.pinimg.com/474x/aa/1.jpg")
        self.assertEqual(first["collection"], "Moodboard / Faces")
        self.assertEqual(first["page_url"], "https://www.pinterest.com/pin/1001/")
        loose = result["candidates"][3]
        self.assertEqual((loose["collection"], loose["page_url"]), ("Moodboard", BOARD.rstrip("/")))

    def test_saved_entries_keep_the_board_and_section(self):
        url = "https://i.pinimg.com/originals/aa/1.jpg"
        details = {url: {"page_url": "https://www.pinterest.com/pin/1001/", "source_service": "pinterest",
                         "source_ref": "1001", "collection": "Moodboard / Faces"}}
        set_id = self.conn.execute("INSERT INTO sets (name, description, created_at) VALUES ('s', '', 'now')").lastrowid
        discover.add_candidates(self.conn, [url], BOARD, set_id, details)
        row = self.conn.execute("SELECT source_url, source_service, source_ref, collection FROM entries").fetchone()
        self.assertEqual(tuple(row), ("https://www.pinterest.com/pin/1001/", "pinterest", "1001", "Moodboard / Faces"))


if __name__ == "__main__":
    unittest.main()
