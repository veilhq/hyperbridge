"""Tests for saved colors: hex normalizing, one row per hex, names, and source image links."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.library import colors  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_accepts_short_and_long_forms_with_or_without_hash(self):
        self.assertEqual(colors.normalize("#ff8800"), "#FF8800")
        self.assertEqual(colors.normalize(" f80 "), "#FF8800")
        self.assertEqual(colors.normalize("#AbC"), "#AABBCC")

    def test_refuses_anything_else(self):
        for value in ("", None, "#ff88", "#gg0000", "red", "#ff880000"):
            self.assertIsNone(colors.normalize(value))


class SavedColorTests(LibraryOpsCase):
    def test_save_without_a_source(self):
        result = colors.save_color("f80", "  rust   orange ")
        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual((result["color"]["hex"], result["color"]["name"], result["color"]["entry_id"]), ("#FF8800", "rust orange", None))

    def test_save_refuses_a_bad_hex(self):
        self.assertFalse(colors.save_color("nope")["ok"])
        self.assertEqual(colors.list_colors(), [])

    def test_saving_a_hex_again_keeps_one_row_and_fills_gaps(self):
        entry = self.add_entry("A")
        first = colors.save_color("#112233")["color"]
        again = colors.save_color("112233", "Ink", entry)
        self.assertFalse(again["created"])
        self.assertEqual(again["color"]["id"], first["id"])
        self.assertEqual((again["color"]["name"], again["color"]["entry_id"]), ("Ink", entry))
        kept = colors.save_color("#112233", "Other", self.add_entry("B"))["color"]
        self.assertEqual((kept["name"], kept["entry_id"]), ("Ink", entry))
        self.assertEqual(len(colors.list_colors()), 1)

    def test_unknown_source_is_dropped(self):
        self.assertIsNone(colors.save_color("#000000", entry_id=999)["color"]["entry_id"])

    def test_deleting_the_source_image_keeps_the_color(self):
        entry = self.add_entry("A")
        saved = colors.save_color("#445566", entry_id=entry)["color"]
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry,))
        self.assertEqual([(item["id"], item["entry_id"]) for item in colors.list_colors()], [(saved["id"], None)])

    def test_list_is_newest_first(self):
        old = colors.save_color("#000001")["color"]["id"]
        colors.save_color("#000002")
        self.conn.execute("UPDATE saved_colors SET created_at = '1999-01-01T00:00:00' WHERE id = ?", (old,))
        self.assertEqual([item["hex"] for item in colors.list_colors()], ["#000002", "#000001"])

    def test_rename_and_delete(self):
        saved = colors.save_color("#ABCDEF", "Sky")["color"]["id"]
        self.assertEqual(colors.rename_color(saved, "  ")["color"]["name"], "")
        self.assertEqual(colors.rename_color(saved, "Pale sky")["color"]["name"], "Pale sky")
        self.assertFalse(colors.rename_color(999, "X")["ok"])
        self.assertTrue(colors.delete_color(saved))
        self.assertFalse(colors.delete_color(saved))
        self.assertEqual(colors.list_colors(), [])


if __name__ == "__main__":
    unittest.main()
