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


class DeletionTests(TransferCase):
    def setUp(self):
        super().setUp()
        self.uids, _ = self.seed_laptop()
        self.conn = use_library(str(self.main))
        self.addCleanup(self.conn.close)
        transfer.import_library(self.conn, self.zip_path)

    def exists(self, uid):
        return self.conn.execute("SELECT COUNT(*) FROM entries WHERE uid = ?", (uid,)).fetchone()[0]

    def test_a_deletion_removes_the_entry_its_files_and_is_remembered(self):
        folder = storage.entry_dir(self.uids[0])
        self.assertTrue(folder.exists())
        removed = transfer.apply_deletions(self.conn, [{"uid": self.uids[0], "deleted_at": "2999-01-01T00:00:00"}])
        self.assertEqual(removed, 1)
        self.assertEqual(self.exists(self.uids[0]), 0)
        self.assertFalse(folder.exists())
        self.assertEqual(transfer.list_deletions(self.conn), [{"uid": self.uids[0], "deleted_at": "2999-01-01T00:00:00"}])

    def test_an_entry_edited_after_the_deletion_is_kept(self):
        self.conn.execute("UPDATE entries SET updated_at = '2999-01-01T00:00:00' WHERE uid = ?", (self.uids[0],))
        self.assertEqual(transfer.apply_deletions(self.conn, [{"uid": self.uids[0], "deleted_at": "2998-01-01T00:00:00"}]), 0)
        self.assertEqual(self.exists(self.uids[0]), 1)

    def test_a_deletion_for_an_unknown_entry_is_passed_on_and_junk_is_ignored(self):
        other = storage.new_uid()
        transfer.apply_deletions(self.conn, [{"uid": other, "deleted_at": "2999-01-01T00:00:00"}, {"uid": "../x", "deleted_at": "1"}, "junk"])
        self.assertEqual([item["uid"] for item in transfer.list_deletions(self.conn)], [other])

    def test_discarding_an_entry_records_the_deletion_and_importing_it_again_clears_it(self):
        from bridge.library import library
        row = self.conn.execute("SELECT id FROM entries WHERE uid = ?", (self.uids[1],)).fetchone()
        self.assertTrue(library.discard_entry(row["id"]))
        self.assertEqual([item["uid"] for item in transfer.list_deletions(self.conn)], [self.uids[1]])
        transfer.import_library(self.conn, self.zip_path)
        self.assertEqual(self.exists(self.uids[1]), 1)
        self.assertEqual(transfer.list_deletions(self.conn), [])


class SetSyncTests(TransferCase):
    def setUp(self):
        super().setUp()
        self.uids, _ = self.seed_laptop()
        self.conn = use_library(str(self.main))
        self.addCleanup(self.conn.close)
        transfer.import_library(self.conn, self.zip_path)
        self.laptop_conn = use_library(str(self.laptop))
        self.addCleanup(self.laptop_conn.close)
        self.conn = use_library(str(self.main))
        self.addCleanup(self.conn.close)

    def names(self, conn):
        return [row[0] for row in conn.execute("SELECT name FROM sets ORDER BY name")]

    def test_sets_get_a_stable_id_and_the_same_one_on_both_machines(self):
        theirs = self.laptop_conn.execute("SELECT uid FROM sets").fetchone()[0]
        self.assertEqual(self.conn.execute("SELECT uid FROM sets").fetchone()[0], theirs)

    def test_a_rename_replaces_the_old_name_instead_of_adding_a_second_set(self):
        self.laptop_conn.execute("UPDATE sets SET name = 'Prints', description = 'new', updated_at = '2999-01-01T00:00:00'")
        changed = transfer.merge_set_heads(self.conn, transfer.list_set_heads(self.laptop_conn), update=True)
        self.assertEqual(changed, 1)
        self.assertEqual(self.names(self.conn), ["Prints"])
        self.assertEqual(self.conn.execute("SELECT description FROM sets").fetchone()[0], "new")
        self.assertEqual(transfer.merge_set_heads(self.conn, transfer.list_set_heads(self.laptop_conn), update=True), 0)

    def test_a_locally_newer_rename_is_kept(self):
        self.laptop_conn.execute("UPDATE sets SET name = 'Prints', updated_at = '2998-01-01T00:00:00'")
        self.conn.execute("UPDATE sets SET name = 'Mine', updated_at = '2999-01-01T00:00:00'")
        transfer.merge_set_heads(self.conn, transfer.list_set_heads(self.laptop_conn), update=True)
        self.assertEqual(self.names(self.conn), ["Mine"])

    def test_sets_that_only_share_a_name_are_matched_and_adopt_one_id(self):
        self.conn.execute("UPDATE sets SET uid = 'a' || substr(uid, 2)")
        transfer.merge_set_heads(self.conn, transfer.list_set_heads(self.laptop_conn), update=True)
        self.assertEqual(self.names(self.conn), ["Posters"])
        self.assertEqual(self.conn.execute("SELECT uid FROM sets").fetchone()[0], self.laptop_conn.execute("SELECT uid FROM sets").fetchone()[0])

    def test_a_deleted_set_is_removed_and_not_recreated(self):
        uid = self.conn.execute("SELECT uid FROM sets").fetchone()[0]
        self.laptop_conn.execute("DELETE FROM sets")
        self.laptop_conn.execute("INSERT INTO set_deletions (uid, deleted_at) VALUES (?, '2999-01-01T00:00:00')", (uid,))
        self.assertEqual(transfer.apply_set_deletions(self.conn, transfer.list_set_deletions(self.laptop_conn)), 1)
        self.assertEqual(self.names(self.conn), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 2)
        old = [{"uid": uid, "name": "Posters", "description": "", "created_at": "", "updated_at": "2000-01-01T00:00:00"}]
        transfer.merge_set_heads(self.conn, old, update=True)
        self.assertEqual(self.names(self.conn), [])

    def test_a_set_edited_after_its_deletion_comes_back(self):
        uid = self.conn.execute("SELECT uid FROM sets").fetchone()[0]
        self.conn.execute("DELETE FROM sets")
        self.conn.execute("INSERT INTO set_deletions (uid, deleted_at) VALUES (?, '2000-01-01T00:00:00')", (uid,))
        transfer.merge_set_heads(self.conn, transfer.list_set_heads(self.laptop_conn), update=True)
        self.assertEqual(self.names(self.conn), ["Posters"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM set_deletions").fetchone()[0], 0)

    def test_deleting_or_renaming_through_the_app_records_it(self):
        from bridge.library import sets
        os.environ["HYPERBRIDGE_DATA_DIR"] = str(self.main)
        set_id, uid = self.conn.execute("SELECT id, uid FROM sets").fetchone()
        self.conn.execute("UPDATE sets SET updated_at = '2000-01-01T00:00:00'")
        sets.rename_set(set_id, "Renamed")
        self.assertGreater(self.conn.execute("SELECT updated_at FROM sets").fetchone()[0], "2000-01-01T00:00:00")
        self.assertTrue(sets.delete_set(set_id))
        self.assertEqual([item["uid"] for item in transfer.list_set_deletions(self.conn)], [uid])


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
