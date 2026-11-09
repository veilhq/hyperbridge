"""Tests for entry detail, field edits and discard."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import library  # noqa: E402
import storage  # noqa: E402
from tests.test_db import LibraryCase  # noqa: E402


class LibraryOpsCase(LibraryCase):
    def add_asset(self, entry_id, kind="original", position=0, data=b"\x89PNG", suffix=".png"):
        uid = self.conn.execute("SELECT uid FROM entries WHERE id = ?", (entry_id,)).fetchone()[0]
        path = storage.asset_path(uid, kind, position, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        cursor = self.conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path, width, height) VALUES (?, ?, ?, ?, 10, 20)",
            (entry_id, position, kind, storage.relative_path(path)),
        )
        return cursor.lastrowid


class GetEntryTests(LibraryOpsCase):
    def test_missing_entry_is_none(self):
        self.assertIsNone(library.get_entry(999))

    def test_returns_fields_tags_and_sets(self):
        entry = self.add_entry(title="Poster", creator="Ada")
        self.conn.execute("INSERT INTO tags (name) VALUES ('type')")
        self.conn.execute("INSERT INTO entry_tags (entry_id, tag_id) VALUES (?, 1)", (entry,))
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Posters', '2026-01-01')")
        self.conn.execute("INSERT INTO set_entries (set_id, entry_id, placed_at) VALUES (1, ?, '2026-01-01')", (entry,))
        result = library.get_entry(entry)
        self.assertEqual(result["title"], "Poster")
        self.assertEqual(result["creator"], "Ada")
        self.assertEqual(result["tags"], ["type"])
        self.assertEqual(result["sets"], [{"id": 1, "name": "Posters"}])
        self.assertEqual(result["manual"], [])

    def test_assets_prefer_original_over_thumbnail_per_position(self):
        entry = self.add_entry()
        self.add_asset(entry, "thumbnail", 0, suffix=".webp")
        original = self.add_asset(entry, "original", 0)
        shot = self.add_asset(entry, "screenshot", 1)
        assets = library.get_entry(entry)["assets"]
        self.assertEqual([a["id"] for a in assets], [original, shot])
        self.assertEqual([a["kind"] for a in assets], ["original", "screenshot"])

    def test_bad_manual_fields_are_ignored(self):
        entry = self.add_entry()
        self.conn.execute("UPDATE entries SET manual_fields = 'not json' WHERE id = ?", (entry,))
        self.assertEqual(library.get_entry(entry)["manual"], [])


class AssetUriTests(LibraryOpsCase):
    def test_returns_data_uri(self):
        entry = self.add_entry()
        asset = self.add_asset(entry, data=b"abc", suffix=".png")
        self.assertEqual(library.get_asset_uri(asset), "data:image/png;base64,YWJj")

    def test_missing_row_or_file_is_none(self):
        self.assertIsNone(library.get_asset_uri(42))
        entry = self.add_entry()
        asset = self.add_asset(entry)
        path = storage.entry_dir(self.conn.execute("SELECT uid FROM entries").fetchone()[0]) / "original-0.png"
        path.unlink()
        self.assertIsNone(library.get_asset_uri(asset))

    def test_path_outside_data_folder_is_refused(self):
        entry = self.add_entry()
        self.conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path) VALUES (?, 0, 'original', '../outside.png')", (entry,)
        )
        asset = self.conn.execute("SELECT id FROM assets").fetchone()[0]
        self.assertIsNone(library.get_asset_uri(asset))


class UpdateEntryTests(LibraryOpsCase):
    def test_changed_fields_become_manual(self):
        entry = self.add_entry(title="Old", creator="Ada")
        result = library.update_entry(entry, {"title": "New", "creator": "Ada", "year": " 2024 "})
        self.assertEqual(result["title"], "New")
        self.assertEqual(result["year"], "2024")
        self.assertEqual(sorted(result["manual"]), ["title", "year"])

    def test_unchanged_save_marks_nothing(self):
        entry = self.add_entry(title="Same")
        result = library.update_entry(entry, {"title": "Same"})
        self.assertEqual(result["manual"], [])

    def test_failed_entry_becomes_captured(self):
        entry = self.add_entry()
        self.conn.execute("UPDATE entries SET state = 'failed' WHERE id = ?", (entry,))
        self.assertEqual(library.update_entry(entry, {"title": "Filled"})["state"], "captured")

    def test_pending_entry_stays_pending(self):
        entry = self.add_entry()
        self.assertEqual(library.update_entry(entry, {"title": "x"})["state"], "pending")

    def test_unknown_keys_are_ignored_and_values_capped(self):
        entry = self.add_entry()
        library.update_entry(entry, {"state": "failed", "uid": "x", "title": "a" * 900})
        result = library.get_entry(entry)
        self.assertEqual(len(result["title"]), 500)
        self.assertEqual(result["state"], "pending")

    def test_edit_is_searchable(self):
        entry = self.add_entry(title="Old")
        library.update_entry(entry, {"title": "Brutalist"})
        self.assertEqual(self.search("brutalist"), [entry])

    def test_missing_entry_is_none(self):
        self.assertIsNone(library.update_entry(999, {"title": "x"}))


class DiscardTests(LibraryOpsCase):
    def test_removes_row_files_and_folder(self):
        entry = self.add_entry()
        self.add_asset(entry)
        uid = self.conn.execute("SELECT uid FROM entries").fetchone()[0]
        folder = storage.entry_dir(uid)
        self.assertTrue(folder.exists())
        self.assertTrue(library.discard_entry(entry))
        self.assertFalse(folder.exists())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 0)

    def test_missing_entry_returns_false(self):
        self.assertFalse(library.discard_entry(999))


if __name__ == "__main__":
    unittest.main()


class EntriesFilesTests(LibraryOpsCase):
    def test_collects_files_across_entries_and_skips_unknown(self):
        first = self.add_entry()
        second = self.add_entry()
        self.add_asset(first)
        self.add_asset(second)
        files = library.entries_files([first, second, 999])
        self.assertEqual(len(files), 2)
