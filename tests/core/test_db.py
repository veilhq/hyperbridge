"""Tests for migrations, the full-text index and storage paths."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import db  # noqa: E402
from bridge.core import storage  # noqa: E402

NOW = "2026-01-01T00:00:00"


class LibraryCase(unittest.TestCase):
    """Base case: each test gets a fresh library folder and a migrated connection."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["HYPERBRIDGE_DATA_DIR"] = self._tmp.name
        self.addCleanup(os.environ.pop, "HYPERBRIDGE_DATA_DIR", None)
        self.conn = db.init_library()
        self.addCleanup(self.conn.close)

    def add_entry(self, title="Poster", **fields):
        uid = storage.new_uid()
        values = {"title": title, "description": "", "domain": "", "creator": "", "publisher": ""}
        values.update(fields)
        cursor = self.conn.execute(
            "INSERT INTO entries (uid, title, description, domain, creator, publisher, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, values["title"], values["description"], values["domain"],
             values["creator"], values["publisher"], NOW, NOW),
        )
        return cursor.lastrowid

    def search(self, term):
        rows = self.conn.execute(
            "SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?", (term,)
        ).fetchall()
        return [row[0] for row in rows]


class MigrationTests(LibraryCase):
    def test_applies_all_migrations_and_sets_version(self):
        expected = len(db.list_migrations())
        self.assertEqual(db.schema_version(self.conn), expected)

    def test_is_idempotent(self):
        before = db.schema_version(self.conn)
        self.assertEqual(db.migrate(self.conn), before)

    def test_uses_wal_and_foreign_keys(self):
        self.assertEqual(self.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_expected_tables_exist(self):
        names = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("entries", "assets", "sets", "set_entries", "tags", "entry_tags", "jobs", "entries_fts"):
            self.assertIn(table, names)

    def test_failed_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "0001_ok.sql").write_text("CREATE TABLE a (id INTEGER);", encoding="utf-8")
            Path(folder, "0002_bad.sql").write_text(
                "CREATE TABLE b (id INTEGER);\nCREATE TABLE a (id INTEGER);", encoding="utf-8"
            )
            conn = db.connect(Path(folder) / "t.db")
            with self.assertRaises(sqlite3.OperationalError):
                db.migrate(conn, Path(folder))
            self.assertEqual(db.schema_version(conn), 1)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertNotIn("b", tables)
            conn.close()

    def test_gap_in_versions_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "0002_late.sql").write_text("SELECT 1;", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                db.list_migrations(Path(folder))


class SchemaTests(LibraryCase):
    def test_state_check_rejects_unknown_value(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO entries (uid, state, created_at, updated_at) VALUES (?, 'bogus', ?, ?)",
                (storage.new_uid(), NOW, NOW),
            )

    def test_source_key_is_unique_when_set_but_repeatable_when_null(self):
        for _ in range(2):
            self.conn.execute(
                "INSERT INTO entries (uid, created_at, updated_at) VALUES (?, ?, ?)",
                (storage.new_uid(), NOW, NOW),
            )
        self.conn.execute(
            "INSERT INTO entries (uid, source_key, created_at, updated_at) VALUES (?, 'k', ?, ?)",
            (storage.new_uid(), NOW, NOW),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO entries (uid, source_key, created_at, updated_at) VALUES (?, 'k', ?, ?)",
                (storage.new_uid(), NOW, NOW),
            )

    def test_set_and_tag_names_are_case_insensitive_unique(self):
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Posters', ?)", (NOW,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('posters', ?)", (NOW,))
        self.conn.execute("INSERT INTO tags (name) VALUES ('Type')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO tags (name) VALUES ('type')")

    def test_deleting_entry_cascades(self):
        entry = self.add_entry()
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('S', ?)", (NOW,))
        self.conn.execute("INSERT INTO set_entries (set_id, entry_id, placed_at) VALUES (1, ?, ?)", (entry, NOW))
        self.conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path) VALUES (?, 0, 'original', 'x')", (entry,)
        )
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry,))
        for table in ("set_entries", "assets"):
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertEqual(count, 0, table)


class SearchTests(LibraryCase):
    def test_insert_is_searchable_with_diacritics_folded(self):
        entry = self.add_entry(title="Café menu poster")
        self.assertEqual(self.search("cafe"), [entry])

    def test_update_refreshes_index(self):
        entry = self.add_entry(title="Old name")
        self.conn.execute("UPDATE entries SET title = 'New name' WHERE id = ?", (entry,))
        self.assertEqual(self.search("old"), [])
        self.assertEqual(self.search("new"), [entry])

    def test_delete_removes_from_index(self):
        entry = self.add_entry(title="Gone")
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry,))
        self.assertEqual(self.search("gone"), [])

    def test_tags_are_searchable_and_follow_changes(self):
        entry = self.add_entry(title="Untitled")
        self.conn.execute("INSERT INTO tags (name) VALUES ('brutalist')")
        self.conn.execute("INSERT INTO entry_tags (entry_id, tag_id) VALUES (?, 1)", (entry,))
        self.assertEqual(self.search("tags:brutalist"), [entry])
        self.conn.execute("UPDATE tags SET name = 'swiss' WHERE id = 1")
        self.assertEqual(self.search("tags:brutalist"), [])
        self.assertEqual(self.search("tags:swiss"), [entry])
        self.conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry,))
        self.assertEqual(self.search("tags:swiss"), [])

    def test_deleting_a_tag_clears_it_from_the_index(self):
        entry = self.add_entry(title="Untitled")
        self.conn.execute("INSERT INTO tags (name) VALUES ('brutalist')")
        self.conn.execute("INSERT INTO entry_tags (entry_id, tag_id) VALUES (?, 1)", (entry,))
        self.conn.execute("DELETE FROM tags WHERE id = 1")
        self.assertEqual(self.search("tags:brutalist"), [])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["HYPERBRIDGE_DATA_DIR"] = self._tmp.name
        self.addCleanup(os.environ.pop, "HYPERBRIDGE_DATA_DIR", None)

    def test_entry_dir_is_sharded_by_first_two_characters(self):
        uid = "ab" + "0" * 30
        self.assertEqual(
            storage.entry_dir(uid), Path(self._tmp.name).resolve() / "assets" / "ab" / uid
        )

    def test_asset_path_names_kind_and_position(self):
        uid = storage.new_uid()
        path = storage.asset_path(uid, "thumbnail", 2, "webp")
        self.assertEqual(path.name, "thumbnail-2.webp")
        self.assertEqual(storage.relative_path(path), f"assets/{uid[:2]}/{uid}/thumbnail-2.webp")

    def test_bad_inputs_are_rejected(self):
        uid = storage.new_uid()
        with self.assertRaises(ValueError):
            storage.entry_dir("../escape")
        with self.assertRaises(ValueError):
            storage.asset_path(uid, "bogus", 0, "png")
        with self.assertRaises(ValueError):
            storage.asset_path(uid, "original", -1, "png")
        with self.assertRaises(ValueError):
            storage.asset_path(uid, "original", 0, "../png")


if __name__ == "__main__":
    unittest.main()
