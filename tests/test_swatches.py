"""Tests for swatch extraction, hue families, backfill and grouped listing."""

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hyperbridge  # noqa: E402
import swatches  # noqa: E402
from tests.test_library import LibraryOpsCase  # noqa: E402


def png(color):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, "PNG")
    return buffer.getvalue()


class SwatchTests(LibraryOpsCase):
    def test_extract_returns_the_dominant_color(self):
        self.assertEqual(swatches.extract(png((255, 0, 0)))[0], "#ff0000")
        self.assertEqual(swatches.extract(b"not an image"), [])

    def test_family_names_hues_and_neutrals(self):
        self.assertEqual(swatches.family("#ff0000"), "Red")
        self.assertEqual(swatches.family("#00ff00"), "Green")
        self.assertEqual(swatches.family("#0000ff"), "Blue")
        self.assertEqual(swatches.family("#808080"), "Neutral")
        self.assertEqual(swatches.entry_family("[]"), swatches.NO_COLOR)

    def test_backfill_fills_only_entries_without_swatches(self):
        blank = self.add_entry("A")
        self.add_asset(blank, data=png((0, 0, 255)))
        done = self.add_entry("B")
        self.add_asset(done, data=png((255, 0, 0)))
        self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(["#123456"]), done))
        self.assertEqual(swatches.backfill(self.conn), 1)
        self.assertEqual(library_swatches(self.conn, blank)[0], "#0000ff")
        self.assertEqual(library_swatches(self.conn, done), ["#123456"])

    def test_list_groups_by_color_year_and_source(self):
        red, blue = self.add_entry("Red"), self.add_entry("Blue")
        self.conn.execute("UPDATE entries SET swatches = ?, year = '2020', domain = 'b.com' WHERE id = ?",
                          (json.dumps(["#ff0000"]), red))
        self.conn.execute("UPDATE entries SET swatches = ?, year = '2024', domain = 'a.com' WHERE id = ?",
                          (json.dumps(["#0000ff"]), blue))
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        labels = lambda group: [e["group"] for e in api.list_entries(group=group)["entries"]]
        self.assertEqual(labels("color"), ["Red", "Blue"])
        self.assertEqual(labels("year"), ["2024", "2020"])
        self.assertEqual(sorted(labels("source")), ["a.com", "b.com"])
        self.assertEqual(api.list_entries()["years"], ["2020", "2024"])
        self.assertEqual(api.list_entries()["entries"][0]["group"], "")


def library_swatches(conn, entry_id):
    return json.loads(conn.execute("SELECT swatches FROM entries WHERE id = ?", (entry_id,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
