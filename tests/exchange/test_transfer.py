"""Tests for library export and import."""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import db  # noqa: E402
from bridge.core import storage  # noqa: E402
from bridge.exchange import transfer  # noqa: E402
from tests.core.test_db import NOW  # noqa: E402


def use_library(folder):
    """Point the app at a library folder and return a migrated connection."""
    os.environ["HYPERBRIDGE_DATA_DIR"] = folder
    return db.init_library()


class TransferCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.environ.pop, "HYPERBRIDGE_DATA_DIR", None)
        self.laptop = Path(self._tmp.name, "laptop")
        self.main = Path(self._tmp.name, "main")
        self.zip_path = Path(self._tmp.name, "library.zip")

    def seed_laptop(self):
        """Two captured entries with files, a tag, a set and a followed source."""
        conn = use_library(str(self.laptop))
        uids = []
        for index, title in enumerate(("First", "Second")):
            uid = storage.new_uid()
            uids.append(uid)
            entry_id = conn.execute(
                "INSERT INTO entries (uid, title, source_key, state, swatches, created_at, updated_at)"
                " VALUES (?, ?, ?, 'captured', '[\"#ff0000\"]', ?, ?)", (uid, title, f"key{index}", NOW, NOW),
            ).lastrowid
            path = storage.asset_path(uid, "original", 0, "png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image-" + title.encode())
            conn.execute("INSERT INTO assets (entry_id, position, kind, path, width, height, bytes) VALUES (?, 0, 'original', ?, 4, 3, 10)",
                         (entry_id, storage.relative_path(path)))
            conn.execute("INSERT INTO tags (name) VALUES (?)", (f"tag{index}",))
            conn.execute("INSERT INTO entry_tags (entry_id, tag_id) VALUES (?, ?)", (entry_id, index + 1))
        conn.execute("INSERT INTO entries (uid, state, created_at, updated_at) VALUES (?, 'pending', ?, ?)", (storage.new_uid(), NOW, NOW))
        conn.execute("INSERT INTO sets (name, description, created_at) VALUES ('Posters', 'big', ?)", (NOW,))
        conn.execute("INSERT INTO set_entries (set_id, entry_id, placed_at) VALUES (1, 1, ?)", (NOW,))
        conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES ('channel', 'https://www.are.na/a/b', 'B', ?)", (NOW,))
        summary = transfer.export_library(conn, self.zip_path)
        conn.close()
        return uids, summary


class ExportImportTests(TransferCase):
    def test_export_skips_pending_entries_and_counts(self):
        _, summary = self.seed_laptop()
        self.assertEqual(summary, {"entries": 2, "sets": 1})
        with zipfile.ZipFile(self.zip_path) as archive:
            self.assertIn("library.json", archive.namelist())
            self.assertEqual(len([n for n in archive.namelist() if n.startswith("assets/")]), 2)

    def test_import_brings_entries_files_tags_sets_and_sources(self):
        uids, _ = self.seed_laptop()
        conn = use_library(str(self.main))
        result = transfer.import_library(conn, self.zip_path)
        self.assertEqual((result["added"], result["skipped"], result["sets"]), (2, 0, 1))
        row = conn.execute("SELECT id, title, swatches FROM entries WHERE uid = ?", (uids[0],)).fetchone()
        self.assertEqual((row["title"], row["swatches"]), ("First", '["#ff0000"]'))
        asset = conn.execute("SELECT path FROM assets WHERE entry_id = ?", (row["id"],)).fetchone()
        self.assertEqual((self.main / asset["path"]).read_bytes(), b"image-First")
        self.assertEqual(conn.execute("SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ?", (row["id"],)).fetchone()[0], "tag0")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM set_entries").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM followed_sources").fetchone()[0], 1)
        self.assertEqual([r[0] for r in conn.execute("SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'first'")], [row["id"]])
        conn.close()

    def test_importing_twice_adds_nothing_new(self):
        self.seed_laptop()
        conn = use_library(str(self.main))
        transfer.import_library(conn, self.zip_path)
        again = transfer.import_library(conn, self.zip_path)
        self.assertEqual((again["added"], again["skipped"]), (0, 2))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM set_entries").fetchone()[0], 1)
        conn.close()

    def test_entry_with_the_same_source_is_not_duplicated_and_joins_the_set(self):
        uids, _ = self.seed_laptop()
        conn = use_library(str(self.main))
        conn.execute("INSERT INTO entries (uid, title, source_key, state, created_at, updated_at) VALUES (?, 'Mine', 'key0', 'captured', ?, ?)",
                     (storage.new_uid(), NOW, NOW))
        result = transfer.import_library(conn, self.zip_path)
        self.assertEqual((result["added"], result["skipped"]), (1, 1))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM set_entries").fetchone()[0], 1)
        conn.close()


class EditSyncTests(TransferCase):
    def edit_laptop(self, stamp="2999-01-01T00:00:00"):
        """Retitle, retag and unset the first laptop entry, then re-export."""
        conn = use_library(str(self.laptop))
        conn.execute("UPDATE entries SET title = 'Renamed', updated_at = ? WHERE id = 1", (stamp,))
        conn.execute("DELETE FROM entry_tags WHERE entry_id = 1")
        conn.execute("INSERT INTO tags (name) VALUES ('fresh')")
        conn.execute("INSERT INTO entry_tags (entry_id, tag_id) SELECT 1, id FROM tags WHERE name = 'fresh'")
        conn.execute("DELETE FROM set_entries WHERE entry_id = 1")
        transfer.export_library(conn, self.zip_path)
        conn.close()

    def tags_of(self, conn, uid):
        return {r[0] for r in conn.execute(
            "SELECT t.name FROM entries e JOIN entry_tags et ON et.entry_id = e.id JOIN tags t ON t.id = et.tag_id WHERE e.uid = ?", (uid,))}

    def test_a_newer_copy_replaces_title_tags_and_sets(self):
        uids, _ = self.seed_laptop()
        conn = use_library(str(self.main))
        self.addCleanup(conn.close)
        transfer.import_library(conn, self.zip_path)
        self.edit_laptop()
        result = transfer.import_library(conn, self.zip_path, update=True)
        self.assertEqual((result["added"], result["updated"]), (0, 1))
        row = conn.execute("SELECT id, title, updated_at FROM entries WHERE uid = ?", (uids[0],)).fetchone()
        self.assertEqual((row["title"], row["updated_at"]), ("Renamed", "2999-01-01T00:00:00"))
        self.assertEqual(self.tags_of(conn, uids[0]), {"fresh"})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM set_entries WHERE entry_id = ?", (row["id"],)).fetchone()[0], 0)
        self.assertEqual(transfer.import_library(conn, self.zip_path, update=True)["updated"], 0)

    def test_without_update_edits_are_ignored(self):
        uids, _ = self.seed_laptop()
        conn = use_library(str(self.main))
        self.addCleanup(conn.close)
        transfer.import_library(conn, self.zip_path)
        self.edit_laptop()
        result = transfer.import_library(conn, self.zip_path)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(conn.execute("SELECT title FROM entries WHERE uid = ?", (uids[0],)).fetchone()[0], "First")

    def test_a_locally_newer_entry_is_kept(self):
        uids, _ = self.seed_laptop()
        conn = use_library(str(self.main))
        self.addCleanup(conn.close)
        transfer.import_library(conn, self.zip_path)
        self.edit_laptop(stamp="2998-01-01T00:00:00")
        conn.execute("UPDATE entries SET title = 'Mine', updated_at = '2999-06-01T00:00:00' WHERE uid = ?", (uids[0],))
        self.assertEqual(transfer.import_library(conn, self.zip_path, update=True)["updated"], 0)
        self.assertEqual(conn.execute("SELECT title FROM entries WHERE uid = ?", (uids[0],)).fetchone()[0], "Mine")

    def test_editing_through_the_library_bumps_the_edit_time(self):
        from bridge.library import library, sets
        self.seed_laptop()
        conn = use_library(str(self.laptop))
        self.addCleanup(conn.close)
        conn.execute("UPDATE entries SET updated_at = '2000-01-01T00:00:00'")
        library.add_tags([2], "extra")
        self.assertGreater(conn.execute("SELECT updated_at FROM entries WHERE id = 2").fetchone()[0], "2000-01-01T00:00:00")
        sets.remove(1, 1)
        self.assertGreater(conn.execute("SELECT updated_at FROM entries WHERE id = 1").fetchone()[0], "2000-01-01T00:00:00")


class SafetyTests(TransferCase):
    def test_non_library_and_newer_files_are_refused(self):
        conn = use_library(str(self.main))
        bad = Path(self._tmp.name, "bad.zip")
        bad.write_bytes(b"not a zip")
        with self.assertRaises(transfer.TransferError):
            transfer.import_library(conn, bad)
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("library.json", json.dumps({"format": 1, "schema": 999, "entries": []}))
        with self.assertRaises(transfer.TransferError):
            transfer.import_library(conn, bad)
        conn.close()

    def test_member_paths_outside_the_entry_folder_are_ignored(self):
        conn = use_library(str(self.main))
        uid = storage.new_uid()
        record = {"uid": uid, "title": "Evil", "state": "captured", "tags": [], "assets": [
            {"position": 0, "kind": "original", "path": "../../escape.png"},
            {"position": 1, "kind": "original", "path": f"assets/{uid[:2]}/{uid}/original-1.png", "width": 1, "height": 1},
        ]}
        evil = Path(self._tmp.name, "evil.zip")
        with zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("library.json", json.dumps({"format": 1, "schema": 1, "entries": [record]}))
            archive.writestr("../../escape.png", b"x")
            archive.writestr(f"assets/{uid[:2]}/{uid}/original-1.png", b"ok")
        result = transfer.import_library(conn, evil)
        self.assertEqual(result["added"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 1)
        self.assertFalse(Path(self._tmp.name, "escape.png").exists())
        conn.close()


if __name__ == "__main__":
    unittest.main()
