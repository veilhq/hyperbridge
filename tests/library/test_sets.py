"""Tests for sets and for saving assets out of the library."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import db  # noqa: E402
from bridge.library import library  # noqa: E402
from bridge.library import sets  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


class SetTests(LibraryOpsCase):
    def test_create_trims_and_rejects_blank_or_duplicate(self):
        self.assertEqual(sets.create_set("  Posters  ")["set"]["name"], "Posters")
        self.assertFalse(sets.create_set("   ")["ok"])
        self.assertEqual(sets.create_set("posters")["error"], "That set exists.")

    def test_description_is_stored_trimmed_and_editable(self):
        made = sets.create_set("Posters", "  Gig   posters  ")["set"]
        self.assertEqual(made["description"], "Gig posters")
        self.assertEqual(sets.rename_set(made["id"], "Posters", "New")["set"]["description"], "New")
        self.assertEqual(sets.rename_set(made["id"], "Prints")["set"]["description"], "New")
        self.assertEqual(sets.list_sets()[0]["description"], "New")
        self.assertEqual(len(sets.create_set("Long", "x" * 500)["set"]["description"]), sets.MAX_DESCRIPTION)

    def test_tags_are_cleaned_and_editable(self):
        made = sets.create_set("Posters", "", " brutalist  poster, Concrete,concrete ,, ")["set"]
        self.assertEqual(made["tags"], ["brutalist poster", "Concrete"])
        self.assertEqual(sets.rename_set(made["id"], "Posters", None, ["swiss"])["set"]["tags"], ["swiss"])
        self.assertEqual(sets.rename_set(made["id"], "Prints")["set"]["tags"], ["swiss"])
        self.assertEqual(sets.list_sets()[0]["tags"], ["swiss"])
        self.assertEqual(len(sets.clean_tags([str(index) for index in range(40)])), sets.MAX_TAGS)

    def test_list_counts_entries_and_orders_by_name(self):
        a, b = self.add_entry("A"), self.add_entry("B")
        zed = sets.create_set("Zed")["set"]["id"]
        alpha = sets.create_set("alpha")["set"]["id"]
        sets.place(a, zed)
        sets.place(b, zed)
        self.assertEqual([(s["name"], s["count"]) for s in sets.list_sets()], [("alpha", 0), ("Zed", 2)])
        self.assertEqual(alpha, 2)

    def test_list_carries_pin_palette_and_change_time(self):
        entry = self.add_entry("A")
        target = sets.create_set("S")["set"]["id"]
        empty = sets.list_sets()[0]
        self.assertEqual((empty["pinned"], empty["palette"], empty["cover_path"]), (False, [], None))
        sets.place(entry, target)
        conn = db.connect()
        try:
            conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", ('["#112233", "#445566"]', entry))
        finally:
            conn.close()
        placed = sets.list_sets()[0]
        self.assertEqual(placed["palette"], ["#112233", "#445566"])
        self.assertGreaterEqual(placed["updated"], empty["updated"])

    def test_chosen_cover_wins_while_in_the_set_and_falls_back_after(self):
        older, newer = self.add_entry("Old"), self.add_entry("New")
        older_thumb = self.add_asset(older, "thumbnail", 0, suffix=".webp")
        self.add_asset(newer, "thumbnail", 0, suffix=".webp")
        target = sets.create_set("S")["set"]["id"]
        self.conn.commit()
        sets.place(older, target)
        sets.place(newer, target)
        self.conn.execute("UPDATE set_entries SET placed_at = '2020-01-01' WHERE entry_id = ?", (older,))
        self.conn.commit()
        newest_path = sets.list_sets()[0]["cover_path"]
        self.assertIsNone(sets.list_sets()[0]["cover_entry_id"])
        self.assertTrue(sets.set_cover(target, older))
        chosen = sets.list_sets()[0]
        older_path = self.conn.execute("SELECT path FROM assets WHERE id = ?", (older_thumb,)).fetchone()[0]
        self.assertEqual((chosen["cover_entry_id"], chosen["cover_path"]), (older, older_path))
        sets.remove(older, target)
        fallen = sets.list_sets()[0]
        self.assertEqual((fallen["cover_entry_id"], fallen["cover_path"]), (None, newest_path))

    def test_cover_must_be_in_the_set_and_can_be_cleared(self):
        inside, outside = self.add_entry("In"), self.add_entry("Out")
        target = sets.create_set("S")["set"]["id"]
        sets.place(inside, target)
        self.assertFalse(sets.set_cover(target, outside))
        self.assertFalse(sets.set_cover(999, inside))
        self.assertTrue(sets.set_cover(target, inside))
        self.assertTrue(sets.set_cover(target, None))
        stored = self.conn.execute("SELECT cover_uid FROM sets WHERE id = ?", (target,)).fetchone()[0]
        self.assertEqual(stored, "")

    def test_pin_toggles_and_checks_id(self):
        target = sets.create_set("S")["set"]["id"]
        self.assertTrue(sets.set_pinned(target, True))
        self.assertTrue(sets.list_sets()[0]["pinned"])
        self.assertTrue(sets.set_pinned(target, False))
        self.assertFalse(sets.list_sets()[0]["pinned"])
        self.assertFalse(sets.set_pinned(999, True))

    def test_place_is_idempotent_and_checks_ids(self):
        entry = self.add_entry()
        target = sets.create_set("S")["set"]["id"]
        self.assertTrue(sets.place(entry, target))
        self.assertTrue(sets.place(entry, target))
        self.assertEqual(sets.list_sets()[0]["count"], 1)
        self.assertFalse(sets.place(999, target))
        self.assertFalse(sets.place(entry, 999))

    def test_remove_keeps_entry(self):
        entry = self.add_entry()
        target = sets.create_set("S")["set"]["id"]
        sets.place(entry, target)
        self.assertTrue(sets.remove(entry, target))
        self.assertFalse(sets.remove(entry, target))
        self.assertIsNotNone(library.get_entry(entry))

    def test_unsorted_lists_and_counts_entries_in_no_set(self):
        import hyperbridge

        placed, loose = self.add_entry("Placed"), self.add_entry("Loose")
        sets.place(placed, sets.create_set("S")["set"]["id"])
        api = hyperbridge.HyperbridgeAPI()
        listed = api.list_entries(unsorted=True)
        self.assertEqual(([e["id"] for e in listed["entries"]], listed["total"]), ([loose], 1))
        self.assertEqual(api.list_entries()["total"], 2)
        self.assertEqual(api.get_stats(), {"entries": 2, "unsorted": 1})

    def test_place_and_remove_many_count_what_changed(self):
        first, second = self.add_entry(), self.add_entry()
        target = sets.create_set("S")["set"]["id"]
        self.assertEqual(sets.place_many([first, second, 999], target), 2)
        self.assertEqual(sets.place_many([first], 999), 0)
        self.assertEqual(sets.list_sets()[0]["count"], 2)
        self.assertEqual(sets.remove_many([first, 999], target), 1)
        self.assertEqual(sets.list_sets()[0]["count"], 1)

    def test_rename_and_delete(self):
        first = sets.create_set("One")["set"]["id"]
        sets.create_set("Two")
        self.assertEqual(sets.rename_set(first, "Three")["set"]["name"], "Three")
        self.assertEqual(sets.rename_set(first, "two")["error"], "That set exists.")
        self.assertFalse(sets.rename_set(999, "X")["ok"])
        entry = self.add_entry()
        sets.place(entry, first)
        self.assertTrue(sets.delete_set(first))
        self.assertFalse(sets.delete_set(first))
        self.assertEqual(library.get_entry(entry)["sets"], [])

    def test_entry_lists_its_sets_with_ids(self):
        entry = self.add_entry()
        target = sets.create_set("S")["set"]["id"]
        sets.place(entry, target)
        self.assertEqual(library.get_entry(entry)["sets"], [{"id": target, "name": "S"}])


class SaveFilesTests(LibraryOpsCase):
    def test_asset_file_names_after_title_and_position(self):
        entry = self.add_entry("My Poster!")
        asset = self.add_asset(entry, position=1, suffix=".jpg")
        path, name = library.asset_file(asset)
        self.assertTrue(path.is_file())
        self.assertEqual(name, "My-Poster-2.jpg")

    def test_missing_asset_is_none(self):
        self.assertIsNone(library.asset_file(999))

    def test_entry_files_one_per_position_preferring_original(self):
        entry = self.add_entry("P")
        self.add_asset(entry, kind="thumbnail", position=0, suffix=".webp")
        self.add_asset(entry, kind="original", position=0, suffix=".png")
        self.add_asset(entry, kind="original", position=1, suffix=".png")
        self.assertEqual([name for _, name in library.entry_files(entry)], ["P-1.png", "P-2.png"])

    def test_copy_files_never_overwrites(self):
        entry = self.add_entry("P")
        self.add_asset(entry, data=b"one")
        files = library.entry_files(entry)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(library.copy_files(files, folder), 1)
            self.assertEqual(library.copy_files(files, folder), 1)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["P-1-2.png", "P-1.png"])

    def test_copy_to_missing_folder_copies_nothing(self):
        self.assertEqual(library.copy_files([], "C:/definitely/not/here"), 0)


if __name__ == "__main__":
    unittest.main()
